"""عقد الـ API لقارئ الفواتير: الملفات، والمسارات، والتصدير، وأخطاء المزود."""
import csv
import io

import pytest
from openpyxl import load_workbook
from pypdf import PdfWriter

from conftest import invoice, upload


def pdf(pages):
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(100, 100)
    b = io.BytesIO()
    w.write(b)
    return b.getvalue()


@pytest.mark.parametrize("path", ["/", "/invoices", "/invoices/", "/invoices/sample-invoice.png", "/invoices/health"])
def test_routes_work_with_and_without_prefix(client, path):
    assert client.get(path).status_code == 200


def test_extraction_returns_balanced_journal_and_alerts(client, gemini):
    j = upload(client).json()
    assert j["balance"]["balanced"]
    assert {a["code"] for a in j["alerts"]} == {"CASH_TVA"}
    assert all(v["valid"] for v in j["identifiers"].values())
    assert gemini.calls[-1]["mime"] == "image/png" and gemini.calls[-1]["schema"].__name__ == "Invoice"


def test_works_without_prefix_too(client):
    assert upload(client, prefix="").status_code == 200


def test_file_type_is_sniffed_from_content_not_name(client):
    assert upload(client, data=b"not an image", name="evil.png").status_code == 400


def test_pdf_page_limit(client, gemini):
    assert upload(client, data=pdf(5), name="a.pdf").status_code == 400
    assert upload(client, data=pdf(1), name="a.pdf").status_code == 200
    assert gemini.calls[-1]["mime"] == "application/pdf"


def test_size_limit(client):
    assert upload(client, data=b"\x89PNG\r\n\x1a\n" + b"0" * (6 * 1024 * 1024)).status_code == 413


def test_non_invoice_document_is_rejected(client, gemini):
    gemini.next = invoice(is_invoice=False, journal_entry=[])
    assert upload(client).status_code == 422


def test_invalid_options(client):
    assert upload(client, invoice_type="refund").status_code == 400


def test_quota_error_is_clear_429(client, gemini):
    from google.genai import errors
    gemini.error = errors.ClientError(429, {"error": {"code": 429, "message": "q", "status": "RESOURCE_EXHAUSTED"}})
    r = upload(client)
    assert r.status_code == 429 and "حصتها المجانية" in r.json()["detail"]


def test_rate_limit(client, monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "EXTRACTS_PER_HOUR", 2)
    main._hits.clear()
    assert [upload(client).status_code for _ in range(3)] == [200, 200, 429]
    main._hits.clear()


def test_excel_export(client):
    res = upload(client).json()
    r = client.post("/invoices/api/export/xlsx", json={"invoice": res["invoice"], "invoice_type": "purchase", "journal": res["journal"]})
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["الفاتورة", "القيد المحاسبي", "PC Compta"]
    assert wb["الفاتورة"].sheet_view.rightToLeft
    assert [c.value for c in list(wb["القيد المحاسبي"].iter_rows())[-1]] == ["المجموع", "=SUM(B2:B4)", "=SUM(C2:C4)"]


def test_pc_compta_export_is_semicolon_csv_with_bom(client):
    res = upload(client).json()
    r = client.post("/invoices/api/export/pccompta", json={"invoice": res["invoice"], "invoice_type": "purchase", "journal": res["journal"]})
    assert r.content.startswith("﻿".encode())
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";"))
    assert rows[0][:3] == ["Date", "Journal", "Compte"] and len(rows) == 4


def test_export_rejects_oversized_payload(client):
    r = client.post("/invoices/api/export/xlsx", json={"invoice": {}, "invoice_type": "purchase", "journal": [{}] * 60})
    assert r.status_code == 400
