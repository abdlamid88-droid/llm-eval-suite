"""مزود متوافق مع OpenAI (Ollama / vLLM) عبر نقل HTTP وهمي: لا شبكة ولا نموذج حقيقي."""
import importlib
import json

import httpx
import pytest


@pytest.fixture()
def openai_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://ollama.test/v1")
    monkeypatch.setenv("EMBED_MODEL", "bge-m3")
    monkeypatch.setenv("EMBED_DIM", "4")
    monkeypatch.setenv("CHAT_MODEL", "qwen-test")
    import app.providers as providers
    p = importlib.reload(providers)
    yield p
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("EMBED_DIM", "768")
    importlib.reload(providers)


def use_transport(p, handler):
    p._http = httpx.Client(base_url="http://ollama.test/v1", transport=httpx.MockTransport(handler))


def test_embeddings_are_ordered_by_index_and_normalized(openai_provider):
    def handler(req):
        body = json.loads(req.content)
        data = [{"index": i, "embedding": [float(i + 1), 0, 0, 0]} for i in range(len(body["input"]))]
        return httpx.Response(200, json={"data": list(reversed(data))})
    use_transport(openai_provider, handler)
    vecs = openai_provider.embed(["a", "b", "c"], is_query=False)
    assert [round(v[0], 3) for v in vecs] == [1.0, 1.0, 1.0]
    assert len(vecs) == 3


def test_wrong_dimension_gives_actionable_error(openai_provider):
    use_transport(openai_provider, lambda req: httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0] * 1024}]}))
    with pytest.raises(openai_provider.ProviderError, match="1024"):
        openai_provider.embed(["a"], is_query=True)


def test_rate_limit_maps_to_quota_error(openai_provider):
    use_transport(openai_provider, lambda req: httpx.Response(429, text="slow down"))
    with pytest.raises(openai_provider.QuotaError):
        openai_provider.chat("sys", "user")


def test_chat_sends_system_prompt_and_model(openai_provider):
    seen = {}
    def handler(req):
        seen.update(json.loads(req.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": " ok "}}]})
    use_transport(openai_provider, handler)
    assert openai_provider.chat("SYSTEM", "USER") == "ok"
    assert seen["model"] == "qwen-test"
    assert seen["messages"][0] == {"role": "system", "content": "SYSTEM"}


def test_unreachable_server_is_provider_error(openai_provider):
    def handler(req):
        raise httpx.ConnectError("refused")
    use_transport(openai_provider, handler)
    with pytest.raises(openai_provider.ProviderError):
        openai_provider.chat("s", "u")
