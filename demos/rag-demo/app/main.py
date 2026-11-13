"""واجهة FastAPI لديمو RAG: رفع PDF والسؤال عنه مع ذكر المصدر."""
import logging
import os
import re
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from . import rag
from .providers import ProviderError, QuotaError

MAX_UPLOAD_MB = float(os.getenv("MAX_UPLOAD_MB", "5"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "40"))
MAX_DOCS_PER_SESSION = int(os.getenv("MAX_DOCS_PER_SESSION", "3"))
QUESTIONS_PER_HOUR = int(os.getenv("QUESTIONS_PER_HOUR", "30"))
UPLOADS_PER_HOUR = int(os.getenv("UPLOADS_PER_HOUR", "6"))
DAILY_QUESTION_CAP = int(os.getenv("DAILY_QUESTION_CAP", "200"))  # سقف عام يحمي فاتورة الـ API
RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "24"))

STATIC = Path(__file__).parent / "static"
SESSION_RE = re.compile(r"^[a-f0-9-]{16,64}$")

@asynccontextmanager
async def lifespan(_app):
    rag.init_db()
    rag.cleanup_old(RETENTION_HOURS)
    yield


app = FastAPI(title="RAG Demo", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


@app.exception_handler(QuotaError)
def quota_error(_request, _exc):
    """رسالة واضحة للزائر عند نفاد الحصة المجانية، بدل خطأ 500."""
    return JSONResponse({"detail": "النسخة التجريبية استهلكت حصتها المجانية مؤقتاً. حاول بعد دقيقة، أو غداً إن استمر."}, 429)


@app.exception_handler(ProviderError)
def provider_error(_request, exc):
    logging.getLogger("uvicorn.error").error("خطأ من مزود النموذج: %s", exc)
    return JSONResponse({"detail": "خدمة الذكاء الاصطناعي غير متاحة مؤقتاً، حاول بعد قليل."}, 503)

_hits: dict[str, deque] = defaultdict(deque)
_daily = {"day": time.strftime("%Y-%m-%d"), "count": 0}


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")


def _rate_limit(key: str, limit: int, window: int = 3600):
    now = time.time()
    q = _hits[key]
    while q and q[0] < now - window:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(429, "تجاوزت حد الاستخدام في النسخة التجريبية، حاول بعد قليل.")
    q.append(now)


def _session(x_session_id: str | None) -> str:
    if not x_session_id or not SESSION_RE.match(x_session_id):
        raise HTTPException(400, "جلسة غير صالحة، أعد تحميل الصفحة.")
    return x_session_id


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/documents")
def documents(x_session_id: str | None = Header(None)):
    return rag.list_docs(_session(x_session_id))


@app.delete("/api/documents")
def clear(x_session_id: str | None = Header(None)):
    rag.delete_docs(_session(x_session_id))
    return {"ok": True}


@app.post("/api/upload")
def upload(request: Request, file: UploadFile = File(...), x_session_id: str | None = Header(None)):
    sid = _session(x_session_id)
    _rate_limit(f"up:{_client_ip(request)}", UPLOADS_PER_HOUR)
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "يُقبل ملف PDF فقط.")
    data = file.file.read(int(MAX_UPLOAD_MB * 1024 * 1024) + 1)
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"الحد الأقصى لحجم الملف {MAX_UPLOAD_MB:g} ميغابايت.")
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, "الملف ليس PDF صالحاً.")
    if len(rag.list_docs(sid)) >= MAX_DOCS_PER_SESSION:
        raise HTTPException(400, f"الحد الأقصى {MAX_DOCS_PER_SESSION} ملفات. امسح الملفات الحالية أولاً.")
    rag.cleanup_old(RETENTION_HOURS)
    try:
        return rag.ingest(sid, Path(file.filename).name[:120], data, MAX_PAGES)
    except ValueError as e:
        raise HTTPException(400, str(e))


class Question(BaseModel):
    question: str = Field(min_length=2, max_length=500)


@app.post("/api/ask")
def ask(body: Question, request: Request, x_session_id: str | None = Header(None)):
    sid = _session(x_session_id)
    _rate_limit(f"q:{_client_ip(request)}", QUESTIONS_PER_HOUR)
    today = time.strftime("%Y-%m-%d")
    if _daily["day"] != today:
        _daily.update(day=today, count=0)
    if _daily["count"] >= DAILY_QUESTION_CAP:
        raise HTTPException(429, "بلغت النسخة التجريبية حدها اليومي، عد غداً.")
    _daily["count"] += 1
    return rag.answer(sid, body.question.strip())
