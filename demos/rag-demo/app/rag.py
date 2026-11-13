"""منطق RAG: استخراج النص من PDF، التقطيع، التضمين، التخزين والاسترجاع."""
import io
import logging
import os
import re
import unicodedata

import psycopg
from pgvector import Vector
from pgvector.psycopg import register_vector
from pypdf import PdfReader

from . import providers
from .providers import EMBED_DIM

log = logging.getLogger("uvicorn.error")

DATABASE_URL = os.environ["DATABASE_URL"]
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "900"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "150"))
TOP_K = int(os.getenv("TOP_K", "5"))

SYSTEM_PROMPT = """أنت مساعد يجيب فقط من المقاطع المرفقة من وثائق المستخدم.
القواعد:
- اعتمد على المقاطع وحدها، ولا تضف معلومات من خارجها.
- بعد كل معلومة اذكر مصدرها بالشكل [ص N] حيث N رقم الصفحة.
- إن لم تجد الإجابة في المقاطع فأجب بهذه الجملة وحدها دون أي إشارة لصفحة: "لم أجد هذه المعلومة في الوثيقة."
- أجب بلغة السؤال، باختصار ووضوح."""


def connect():
    conn = psycopg.connect(DATABASE_URL, autocommit=True)
    register_vector(conn)
    return conn


def init_db():
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        try:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        except psycopg.errors.InsufficientPrivilege:
            raise RuntimeError("فعّل امتداد vector بحساب postgres الإداري (انظر README).")
    with connect() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        row = conn.execute("SELECT value FROM meta WHERE key = 'embed_signature'").fetchone()
        sig = providers.signature()
        if row and row[0] != sig:
            # تغيّر مزود أو نموذج التضمين: المتجهات القديمة لا تصلح، وبيانات الديمو مؤقتة أصلاً
            log.warning("تغيّر نموذج التضمين (%s ← %s): إعادة إنشاء الفهرس", row[0], sig)
            conn.execute("DROP TABLE IF EXISTS chunks; DROP TABLE IF EXISTS documents;")
        conn.execute(
            "INSERT INTO meta VALUES ('embed_signature', %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            (sig,),
        )
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS documents (
                id         BIGSERIAL PRIMARY KEY,
                session_id TEXT NOT NULL,
                filename   TEXT NOT NULL,
                pages      INT  NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE TABLE IF NOT EXISTS chunks (
                id          BIGSERIAL PRIMARY KEY,
                document_id BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                page        INT    NOT NULL,
                content     TEXT   NOT NULL,
                embedding   vector({EMBED_DIM}) NOT NULL
            );
            CREATE INDEX IF NOT EXISTS chunks_embedding_idx
                ON chunks USING hnsw (embedding vector_cosine_ops);
            CREATE INDEX IF NOT EXISTS documents_session_idx ON documents(session_id);
            """
        )


def cleanup_old(hours: int):
    """حذف وثائق الزوار الأقدم من المدة المحددة."""
    with connect() as conn:
        conn.execute(
            "DELETE FROM documents WHERE created_at < now() - make_interval(hours => %s)",
            (hours,),
        )


# ملفات Word العربية كثيراً ما تحفظ حروفاً فارسية/أردية متشابهة الشكل؛ نوحّدها للعربية
# حتى يطابق البحثُ ما يكتبه المستخدم بلوحة مفاتيح عربية.
_ARABIC_FIX = str.maketrans({"\u06BE": "ه", "\u06C1": "ه", "\u06CC": "ي", "\u06A9": "ك", "\u200c": ""})
_ARABIC = re.compile(r"[\u0600-\u06FF\uFB50-\uFDFF\uFE70-\uFEFF]")
_LTR_RUN = re.compile(r"[A-Za-z0-9%](?:[A-Za-z0-9%.,:/&'_+\- ]*[A-Za-z0-9%])?")
_MIRROR = str.maketrans("()[]{}<>«»", ")(][}{><»«")


def _norm(text: str) -> str:
    # NFKC يحوّل أشكال الحروف العربية المعروضة (Presentation Forms) إلى حروفها الأصلية
    return unicodedata.normalize("NFKC", text).translate(_ARABIC_FIX)


def _looks_reversed(text: str) -> bool:
    """في النص السليم تكثر الكلمات التي تبدأ بـ«ال»؛ وفي المعكوس تكثر التي تنتهي بـ«لا»."""
    logical = len(re.findall(r"(?<!\w)ال\w{2,}", text))
    reversed_ = len(re.findall(r"\w{2,}لا(?!\w)", text))
    return reversed_ > logical


def _visual_to_logical(line: str) -> str:
    """بعض ملفات PDF (من Chrome وGoogle Docs مثلاً) تحفظ العربية بترتيب العرض: نعكس السطر،
    ثم نعيد المقاطع اللاتينية والأرقام إلى اتجاهها، ونقلب الأقواس."""
    s = line[::-1]
    s = _LTR_RUN.sub(lambda m: m.group(0)[::-1], s)
    return s.translate(_MIRROR)


def _page_text(page) -> str:
    raw = page.extract_text(extraction_mode="layout") or ""
    probe = _norm(raw)
    if _ARABIC.search(probe) and _looks_reversed(probe):
        # العكس قبل التطبيع: حرف «ﻻ» المركّب يبقى حرفاً واحداً عند العكس ثم يُفك صحيحاً إلى «لا»
        raw = "\n".join(_visual_to_logical(l) if _ARABIC.search(l) else l for l in raw.splitlines())
    # نعيد النص إلى أسطر متصلة (بعض الملفات تضع كل كلمة في سطر)
    return re.sub(r"\s+", " ", _norm(raw)).strip()


def extract_pages(pdf_bytes: bytes, max_pages: int) -> list[tuple[int, str]]:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    if len(reader.pages) > max_pages:
        raise ValueError(f"الحد الأقصى في النسخة التجريبية {max_pages} صفحة.")
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        text = _page_text(page)
        if text:
            pages.append((i, text))
    return pages


def chunk_pages(pages: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """تقطيع كل صفحة إلى مقاطع متداخلة، مع الحفاظ على رقم الصفحة للاستشهاد."""
    chunks = []
    step = CHUNK_SIZE - CHUNK_OVERLAP
    for page_no, text in pages:
        start = 0
        while start < len(text):
            piece = text[start : start + CHUNK_SIZE].strip()
            if len(piece) > 40:
                chunks.append((page_no, piece))
            start += step
    return chunks


def ingest(session_id: str, filename: str, pdf_bytes: bytes, max_pages: int) -> dict:
    pages = extract_pages(pdf_bytes, max_pages)
    if not pages:
        raise ValueError("لم يُعثر على نص قابل للقراءة. هل الملف صور ممسوحة ضوئياً؟")
    chunks = chunk_pages(pages)
    vectors = providers.embed([c for _, c in chunks], is_query=False)
    with connect() as conn, conn.transaction():
        doc_id = conn.execute(
            "INSERT INTO documents (session_id, filename, pages) VALUES (%s, %s, %s) RETURNING id",
            (session_id, filename, len(pages)),
        ).fetchone()[0]
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO chunks (document_id, page, content, embedding) VALUES (%s, %s, %s, %s)",
                [(doc_id, p, c, Vector(v)) for (p, c), v in zip(chunks, vectors)],
            )
    return {"id": doc_id, "filename": filename, "pages": len(pages), "chunks": len(chunks)}


def list_docs(session_id: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, filename, pages FROM documents WHERE session_id = %s ORDER BY id",
            (session_id,),
        ).fetchall()
    return [{"id": r[0], "filename": r[1], "pages": r[2]} for r in rows]


def delete_docs(session_id: str):
    with connect() as conn:
        conn.execute("DELETE FROM documents WHERE session_id = %s", (session_id,))


def answer(session_id: str, question: str) -> dict:
    qvec = Vector(providers.embed([question], is_query=True)[0])
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT d.filename, c.page, c.content, 1 - (c.embedding <=> %s) AS score
            FROM chunks c JOIN documents d ON d.id = c.document_id
            WHERE d.session_id = %s
            ORDER BY c.embedding <=> %s
            LIMIT %s
            """,
            (qvec, session_id, qvec, TOP_K),
        ).fetchall()
    if not rows:
        return {"answer": "ارفع ملف PDF أولاً ثم اسأل عنه.", "sources": []}

    context = "\n\n".join(f"[ص {page} — {fn}]\n{content}" for fn, page, content, _ in rows)
    text = providers.chat(SYSTEM_PROMPT, f"المقاطع:\n{context}\n\nالسؤال: {question}")
    sources = [
        {"filename": fn, "page": page, "score": round(float(score), 3), "snippet": content[:280]}
        for fn, page, content, score in rows
    ]
    if text.startswith("لم أجد هذه المعلومة"):
        return {"answer": "لم أجد هذه المعلومة في الوثيقة.", "sources": []}
    return {"answer": text, "sources": sources}
