"""طبقة المزودين: نفس الواجهة لـ Gemini ولأي خادم متوافق مع OpenAI (Ollama، vLLM، LM Studio، ...).

التبديل يتم من ملف .env فقط:
    LLM_PROVIDER=gemini   ← يستخدم GEMINI_API_KEY
    LLM_PROVIDER=openai   ← يستخدم OPENAI_BASE_URL و OPENAI_API_KEY
"""
import math
import os

import httpx

PROVIDER = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
CHAT_MODEL = os.getenv("CHAT_MODEL", "gemini-3.1-flash-lite")
EMBED_MODEL = os.getenv("EMBED_MODEL", "gemini-embedding-001")
EMBED_DIM = int(os.getenv("EMBED_DIM", "768"))
TIMEOUT = float(os.getenv("LLM_TIMEOUT", "120"))  # النماذج المحلية أبطأ، فالمهلة أطول
BATCH = 32

# بعض نماذج التضمين المحلية (مثل nomic-embed-text) تتطلب بادئة تميّز الوثيقة عن السؤال
DOC_PREFIX = os.getenv("EMBED_DOC_PREFIX", "")
QUERY_PREFIX = os.getenv("EMBED_QUERY_PREFIX", "")


class QuotaError(Exception):
    """نفدت الحصة أو تجاوزنا حد الطلبات عند المزود."""


class ProviderError(Exception):
    """المزود غير متاح أو أعاد خطأ."""


def signature() -> str:
    """بصمة فضاء المتجهات؛ إن تغيّرت لا تصلح المتجهات القديمة للبحث."""
    return f"{PROVIDER}|{EMBED_MODEL}|{EMBED_DIM}"


def _normalize(vec) -> list[float]:
    n = math.sqrt(sum(x * x for x in vec))
    return [x / n for x in vec] if n else list(vec)


def _check_dim(vectors: list[list[float]]) -> list[list[float]]:
    if vectors and len(vectors[0]) != EMBED_DIM:
        raise ProviderError(
            f"نموذج التضمين يعطي {len(vectors[0])} بُعداً بينما EMBED_DIM={EMBED_DIM}. "
            f"عدّل EMBED_DIM في .env إلى {len(vectors[0])}."
        )
    return [_normalize(v) for v in vectors]


# ───────────────────────── Gemini ─────────────────────────
if PROVIDER == "gemini":
    from google import genai
    from google.genai import errors as genai_errors
    from google.genai import types

    _gemini = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    def _gemini_call(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except genai_errors.APIError as e:
            if e.code == 429:
                raise QuotaError(str(e)) from e
            raise ProviderError(str(e)) from e
        except httpx.HTTPError as e:
            raise ProviderError(str(e)) from e

    def embed(texts: list[str], is_query: bool) -> list[list[float]]:
        task = "RETRIEVAL_QUERY" if is_query else "RETRIEVAL_DOCUMENT"
        out = []
        for i in range(0, len(texts), BATCH):
            res = _gemini_call(
                _gemini.models.embed_content,
                model=EMBED_MODEL,
                contents=texts[i : i + BATCH],
                config=types.EmbedContentConfig(task_type=task, output_dimensionality=EMBED_DIM),
            )
            out.extend(e.values for e in res.embeddings)
        return _check_dim(out)

    def chat(system: str, user: str) -> str:
        res = _gemini_call(
            _gemini.models.generate_content,
            model=CHAT_MODEL,
            contents=user,
            config=types.GenerateContentConfig(system_instruction=system, temperature=0.2),
        )
        return (res.text or "").strip()

# ─────────────── أي خادم متوافق مع OpenAI ───────────────
elif PROVIDER == "openai":
    _base = os.environ["OPENAI_BASE_URL"].rstrip("/")
    _key = os.getenv("OPENAI_API_KEY", "none")  # Ollama وvLLM المحليان لا يحتاجان مفتاحاً
    _http = httpx.Client(base_url=_base, timeout=TIMEOUT, headers={"Authorization": f"Bearer {_key}"})

    def _post(path: str, payload: dict) -> dict:
        try:
            r = _http.post(path, json=payload)
        except httpx.HTTPError as e:
            raise ProviderError(f"تعذر الاتصال بـ {_base}: {e}") from e
        if r.status_code == 429:
            raise QuotaError(r.text[:300])
        if r.status_code >= 400:
            raise ProviderError(f"{r.status_code}: {r.text[:300]}")
        return r.json()

    def embed(texts: list[str], is_query: bool) -> list[list[float]]:
        prefix = QUERY_PREFIX if is_query else DOC_PREFIX
        out = []
        for i in range(0, len(texts), BATCH):
            data = _post("/embeddings", {"model": EMBED_MODEL, "input": [prefix + t for t in texts[i : i + BATCH]]})
            out.extend(d["embedding"] for d in sorted(data["data"], key=lambda d: d["index"]))
        return _check_dim(out)

    def chat(system: str, user: str) -> str:
        data = _post(
            "/chat/completions",
            {
                "model": CHAT_MODEL,
                "temperature": 0.2,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            },
        )
        return (data["choices"][0]["message"]["content"] or "").strip()

else:
    raise RuntimeError(f"LLM_PROVIDER غير معروف: {PROVIDER!r}. القيم المقبولة: gemini أو openai")
