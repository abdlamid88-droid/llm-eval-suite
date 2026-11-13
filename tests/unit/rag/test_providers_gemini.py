"""استدعاء Gemini في ديمو RAG: إعادة المحاولة وتحويل الأخطاء (BUG-007)."""
import pytest
from google.genai import errors

from app import providers


@pytest.fixture(autouse=True)
def no_delay(monkeypatch):
    monkeypatch.setattr(providers, "RETRY_DELAY", 0, raising=False)


class Flaky:
    def __init__(self, *failures):
        self.failures = list(failures)
        self.calls = 0

    def __call__(self, **kwargs):
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return "ok"


def test_network_error_is_retried_once():
    fn = Flaky(OSError("[Errno 101] Network is unreachable"))
    assert providers._gemini_call(fn) == "ok" and fn.calls == 2


def test_persistent_network_error_becomes_provider_error():
    fn = Flaky(OSError("down"), OSError("down"))
    with pytest.raises(providers.ProviderError):
        providers._gemini_call(fn)
    assert fn.calls == 2


def test_quota_is_not_retried():
    fn = Flaky(errors.ClientError(429, {"error": {"code": 429, "message": "q", "status": "RESOURCE_EXHAUSTED"}}))
    with pytest.raises(providers.QuotaError):
        providers._gemini_call(fn)
    assert fn.calls == 1


def test_server_error_is_retried():
    fn = Flaky(errors.ServerError(503, {"error": {"code": 503, "message": "x", "status": "UNAVAILABLE"}}))
    assert providers._gemini_call(fn) == "ok" and fn.calls == 2
