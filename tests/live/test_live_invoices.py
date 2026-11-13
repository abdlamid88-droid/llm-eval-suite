"""قارئ الفواتير: استخراج الفاتورة النموذجية الوهمية بأرقامها المعروفة."""
import io

import pytest

from conftest import _skip_on_rate_limit

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def result(http, invoices):
    png = http.get(f"{invoices}/sample-invoice.png").content
    r = http.post(f"{invoices}/api/extract", files={"file": ("specimen.png", png)}, data={"invoice_type": "purchase", "lang": "ar"})
    _skip_on_rate_limit(r)
    assert r.status_code == 200, r.text
    return r.json()


def test_amounts_are_exact(result):
    inv = result["invoice"]
    assert inv["total_amount"] == pytest.approx(142800)
    assert inv["tax_amount"] == pytest.approx(22800)
    assert inv["invoice_number"].replace(" ", "") == "FA-2026-0147"


def test_all_line_items_extracted(result):
    totals = sorted(round(i["total"]) for i in result["invoice"]["items"])
    assert totals == [30000, 36000, 54000]


def test_journal_is_balanced_scf(result):
    assert result["balance"]["balanced"]
    accounts = " ".join(e["account"] for e in result["journal"])
    assert "401" in accounts and "4456" in accounts


def test_fiscal_identifiers_are_read_correctly(result):
    ids = result["identifiers"]
    assert ids["nif"]["value"] == "000216098765432" and ids["nif"]["valid"]
    assert ids["rc"]["valid"] and ids["nis"]["valid"]


def test_cash_alert_matches_the_law_threshold(result):
    codes = {a["code"] for a in result["alerts"]}
    assert "CASH_TVA" in codes          # > 100,000 دج
    assert "CASH_CHARGE" not in codes   # < 300,000 دج


def test_excel_export_from_live_result(http, invoices, result):
    from openpyxl import load_workbook
    r = http.post(f"{invoices}/api/export/xlsx", json={"invoice": result["invoice"], "invoice_type": "purchase", "journal": result["journal"]})
    assert r.status_code == 200
    assert "القيد المحاسبي" in load_workbook(io.BytesIO(r.content)).sheetnames
