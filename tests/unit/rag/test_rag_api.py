"""عقد الـ API لديمو RAG: الاستشهاد، والرفض، وعزل الجلسات، والحدود."""
from conftest import REFUSAL, make_pdf

PDF = make_pdf([
    "Company profile and general introduction about our services.",
    "Invoice number 77: the invoice total amount is 4500 dollars due in March.",
])


def upload(client, session, data=PDF, name="doc.pdf"):
    return client.post("/api/upload", headers=session, files={"file": (name, data, "application/pdf")})


def test_upload_reports_pages_and_chunks(client, session):
    r = upload(client, session)
    assert r.status_code == 200
    assert r.json()["pages"] == 2 and r.json()["chunks"] >= 2


def test_answer_cites_the_right_page(client, session):
    upload(client, session)
    j = client.post("/api/ask", headers=session, json={"question": "what is the invoice total amount"}).json()
    assert "[ص 2]" in j["answer"]
    assert j["sources"][0]["page"] == 2


def test_out_of_document_question_is_refused_without_sources(client, session):
    upload(client, session)
    j = client.post("/api/ask", headers=session, json={"question": "who won the football cup"}).json()
    assert j["answer"] == REFUSAL
    assert j["sources"] == []


def test_sessions_are_isolated(client, session):
    import secrets
    upload(client, session)
    other = {"X-Session-Id": secrets.token_hex(16)}
    assert client.get("/api/documents", headers=other).json() == []
    j = client.post("/api/ask", headers=other, json={"question": "invoice total amount"}).json()
    assert j["sources"] == []


def test_clear_documents(client, session):
    upload(client, session)
    assert client.delete("/api/documents", headers=session).json() == {"ok": True}
    assert client.get("/api/documents", headers=session).json() == []


def test_invalid_session_is_rejected(client):
    assert client.get("/api/documents", headers={"X-Session-Id": "x"}).status_code == 400
    assert client.get("/api/documents").status_code == 400


def test_non_pdf_is_rejected(client, session):
    assert upload(client, session, data=b"hello", name="a.pdf").status_code == 400
    assert upload(client, session, name="a.txt").status_code == 400


def test_max_documents_per_session(client, session, monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "MAX_DOCS_PER_SESSION", 2)
    assert upload(client, session).status_code == 200
    assert upload(client, session).status_code == 200
    assert upload(client, session).status_code == 400


def test_question_length_is_validated(client, session):
    assert client.post("/api/ask", headers=session, json={"question": "x" * 501}).status_code == 422


def test_rate_limit_per_ip(client, session, monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "QUESTIONS_PER_HOUR", 2)
    main._hits.clear()
    codes = [client.post("/api/ask", headers=session, json={"question": "hello there"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    main._hits.clear()


def test_provider_quota_error_becomes_clear_429(client, session, monkeypatch):
    from app import providers
    def boom(*a, **k):
        raise providers.QuotaError("RESOURCE_EXHAUSTED")
    upload(client, session)
    monkeypatch.setattr(providers, "embed", boom)
    r = client.post("/api/ask", headers=session, json={"question": "invoice total"})
    assert r.status_code == 429 and "حصتها المجانية" in r.json()["detail"]
