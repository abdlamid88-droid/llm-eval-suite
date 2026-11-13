"""إعداد اختبارات ديمو RAG: نموذج وهمي حتمي بدل Gemini، وقاعدة PostgreSQL + pgvector حقيقية."""
import hashlib
import io
import os
import re
import sys
from pathlib import Path

import pytest

DEMO = Path(__file__).resolve().parents[3] / "demos" / "rag-demo"
sys.path.insert(0, str(DEMO))

os.environ.setdefault("DATABASE_URL", os.getenv("TEST_DATABASE_URL", "postgresql://rag_demo:rag_demo@localhost:5432/rag_demo"))
os.environ.update(LLM_PROVIDER="gemini", GEMINI_API_KEY="test-key", EMBED_DIM="768",
                  QUESTIONS_PER_HOUR="1000", UPLOADS_PER_HOUR="1000")

REFUSAL = "لم أجد هذه المعلومة في الوثيقة."


def fake_embed(texts, is_query):
    """تضمين حتمي بالكلمات: يكفي لاختبار أن الاسترجاع يجد المقطع الصحيح."""
    out = []
    for t in texts:
        v = [0.0] * 768
        for w in re.findall(r"\w+", t.lower()):
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 768] += 1.0
        out.append(v)
    from app import providers
    return [providers._normalize([x + 1e-6 for x in v]) for v in out]


def fake_chat(system, user):
    """يجيب من أول مقطع إن شارك السؤالَ كلمةً مهمة، وإلا يرفض: يحاكي النموذج المنضبط."""
    context, _, question = user.rpartition("السؤال:")
    q_words = {w for w in re.findall(r"\w+", question.lower()) if len(w) > 3}
    first = re.search(r"\[ص (\d+) — [^\]]+\]\n(.+?)(?:\n\n\[ص|\Z)", context, re.S)
    if first and q_words & set(re.findall(r"\w+", first.group(2).lower())):
        return f"{first.group(2)[:80]} [ص {first.group(1)}]"
    return REFUSAL


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient
    from app import providers, rag
    from app.main import app
    monkeypatch.setattr(providers, "embed", fake_embed)
    monkeypatch.setattr(providers, "chat", fake_chat)
    with TestClient(app) as c:
        with rag.connect() as conn:
            conn.execute("TRUNCATE documents CASCADE")
        yield c


def make_pdf(pages: list[str]) -> bytes:
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for text in pages:
        y = 760
        for line in text.split("\n"):
            c.drawString(60, y, line)
            y -= 18
        c.showPage()
    c.save()
    return buf.getvalue()


@pytest.fixture()
def session():
    import secrets
    return {"X-Session-Id": secrets.token_hex(16)}
