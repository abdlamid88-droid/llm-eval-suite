"""ديمو «اسأل وثيقتك»: الاستشهاد بالصفحة والرفض الصريح، على Gemini الحقيقي."""
import io
import re
import secrets

import pytest

from conftest import _skip_on_rate_limit

pytestmark = pytest.mark.live


def make_pdf():
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(60, 760, "Northwind Logistics - company profile and general services overview.")
    c.showPage()
    c.drawString(60, 760, "Warranty policy: all refurbished scanners carry a warranty of 18 months.")
    c.showPage()
    c.save()
    return buf.getvalue()


@pytest.fixture()
def doc(http, rag):
    headers = {"X-Session-Id": secrets.token_hex(16)}
    r = http.post(f"{rag}/api/upload", headers=headers, files={"file": ("eval.pdf", make_pdf(), "application/pdf")})
    _skip_on_rate_limit(r)
    assert r.status_code == 200, r.text
    yield headers
    http.delete(f"{rag}/api/documents", headers=headers)


def ask(http, rag, headers, q):
    r = http.post(f"{rag}/api/ask", headers=headers, json={"question": q})
    _skip_on_rate_limit(r)
    assert r.status_code == 200, r.text
    return r.json()


def test_answer_is_grounded_and_cites_correct_page(http, rag, doc):
    j = ask(http, rag, doc, "How long is the warranty on refurbished scanners?")
    assert "18" in j["answer"]
    assert re.search(r"\[ص\s*2\]", j["answer"]), j["answer"]


def test_question_outside_document_is_refused(http, rag, doc):
    j = ask(http, rag, doc, "What is the capital of Australia?")
    assert j["answer"].startswith("لم أجد هذه المعلومة"), j["answer"]
    assert "Canberra" not in j["answer"]
    assert j["sources"] == []


def test_other_sessions_cannot_read_the_document(http, rag, doc):
    other = {"X-Session-Id": secrets.token_hex(16)}
    assert http.get(f"{rag}/api/documents", headers=other).json() == []
