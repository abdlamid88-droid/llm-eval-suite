"""اختبارات حية على الديموهات المنشورة (صندوق أسود عبر HTTP). تستهلك حصة Gemini، فتُشغَّل يدوياً أو أسبوعياً."""
import json
import os
import re
import secrets
from pathlib import Path

import httpx
import pytest

BASE_URL = os.getenv("BASE_URL", "https://abdelhmid-vostro-1015.tailc599d9.ts.net").rstrip("/")
RAG_URL = os.getenv("RAG_URL", BASE_URL).rstrip("/")
INVOICES_URL = os.getenv("INVOICES_URL", f"{BASE_URL}/invoices").rstrip("/")
AGENT_URL = os.getenv("AGENT_URL", f"{BASE_URL}/agent").rstrip("/")

CATALOG_PRICES = set(json.loads((Path(__file__).parent / "agent_catalog_prices.json").read_text())["prices_dzd"])
PRICE_RE = re.compile(r"(\d{1,3}(?:[,\s ]\d{3})+|\d{3,7})(?:[.,]\d+)?\s*(?:دج|DZD|DA)\b")


def prices_in(text: str) -> set[float]:
    """كل مبلغ متبوع بعملة في نص الرد."""
    return {float(re.sub(r"[,\s ]", "", m.group(1))) for m in PRICE_RE.finditer(text)}


def _skip_on_rate_limit(response: httpx.Response):
    """الديموهات محمية بحد للطلبات وسقف يومي؛ بلوغه حماية تعمل كما يجب لا خطأ في المنتج."""
    if response.status_code == 429:
        pytest.skip(f"حد الاستخدام في الديمو: {response.json().get('detail', '')}")


@pytest.fixture(scope="session")
def http():
    with httpx.Client(timeout=60, follow_redirects=True, event_hooks={"response": [lambda r: r.read()]}) as c:
        yield c


def _require(http, url):
    try:
        if http.get(url, timeout=15).status_code != 200:
            pytest.skip(f"الديمو غير متاح: {url}")
    except httpx.HTTPError as e:
        pytest.skip(f"الديمو غير متاح: {url} ({e.__class__.__name__})")


@pytest.fixture(scope="session")
def rag(http):
    _require(http, f"{RAG_URL}/health")
    return RAG_URL


@pytest.fixture(scope="session")
def invoices(http):
    _require(http, f"{INVOICES_URL}/health")
    return INVOICES_URL


@pytest.fixture(scope="session")
def agent(http):
    _require(http, f"{AGENT_URL}/health")
    return AGENT_URL


@pytest.fixture()
def chat(http, agent):
    """محادثة جديدة بجلسة مستقلة؛ تعيد نص كل الردود مجمّعاً."""
    session = secrets.token_hex(16)

    def send(message: str) -> str:
        r = http.post(f"{agent}/api/chat", json={"session": session, "message": message})
        _skip_on_rate_limit(r)
        assert r.status_code == 200, r.text
        return "\n".join(m["text"] for m in r.json()["replies"])
    return send
