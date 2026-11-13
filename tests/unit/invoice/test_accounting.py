"""المنطق المحاسبي الجزائري (SCF): حتمي بالكامل، فيجب أن يُختبر بدقة."""
import pytest

from app import accounting as acc
from conftest import JOURNAL_OK, invoice


def codes(alerts):
    return {a["code"] for a in alerts}


def test_balanced_journal_is_untouched():
    rows, bal = acc.balance_journal(JOURNAL_OK, "purchase")
    assert bal == {"total_debit": 142800, "total_credit": 142800, "difference": 0, "balanced": True, "rounding_adjusted": False}


def test_rounding_difference_is_absorbed_in_supplier_account():
    j = [dict(JOURNAL_OK[0], debit=120000.4), JOURNAL_OK[1], JOURNAL_OK[2]]
    rows, bal = acc.balance_journal(j, "purchase")
    assert bal["balanced"] and bal["rounding_adjusted"]
    assert rows[2]["credit"] == 142800.4  # 401 يمتص الفرق


def test_rounding_on_sale_adjusts_customer_debit():
    j = [{"account": "411 - الزبائن", "debit": 1190.3, "credit": 0},
         {"account": "700 - مبيعات", "debit": 0, "credit": 1000},
         {"account": "4457 - TVA", "debit": 0, "credit": 190}]
    rows, bal = acc.balance_journal(j, "sale")
    assert bal["balanced"] and rows[0]["debit"] == 1190.0


def test_large_difference_is_reported_not_hidden():
    j = [dict(JOURNAL_OK[0], debit=125000), JOURNAL_OK[1], JOURNAL_OK[2]]
    rows, bal = acc.balance_journal(j, "purchase")
    assert not bal["balanced"] and bal["difference"] == 5000
    assert rows[2]["credit"] == 142800  # لم يُعدَّل بصمت


@pytest.mark.parametrize("field, value, valid", [
    ("nif", "000216098765432", True), ("nif", "00021609876543210000", True), ("nif", "12ab", False), ("nif", "", None),
    ("rc", "16B0987654", True), ("rc", "16/B/0987654", True), ("rc", "XX", False),
    ("article_imposition", "16012345678", True), ("article_imposition", "123", False),
    ("nis", "000216010203040", True), ("nis", "123", False),
])
def test_identifier_formats(field, value, valid):
    key = "article" if field == "article_imposition" else field
    assert acc.validate_identifiers({field: value})[key]["valid"] is valid


@pytest.mark.parametrize("total, expected", [
    (99_000, set()),
    (100_001, {"CASH_TVA"}),
    (300_001, {"CASH_TVA", "CASH_CHARGE"}),
])
def test_cash_thresholds(total, expected):
    inv = invoice(total_amount=total, tax_amount=round(total - total / 1.19, 2), items=[])
    ids = acc.validate_identifiers(inv)
    _, bal = acc.balance_journal(JOURNAL_OK, "purchase")
    assert codes(acc.tax_alerts(inv, ids, bal)) & {"CASH_TVA", "CASH_CHARGE"} == expected


def test_unusual_tva_rate_is_flagged():
    inv = invoice(total_amount=1150, tax_amount=150, items=[])  # 15%
    _, bal = acc.balance_journal(JOURNAL_OK, "purchase")
    assert "TVA_RATE" in codes(acc.tax_alerts(inv, acc.validate_identifiers(inv), bal))


@pytest.mark.parametrize("ht, tax", [(1000, 190), (1000, 90)])
def test_standard_tva_rates_are_accepted(ht, tax):
    inv = invoice(total_amount=ht + tax, tax_amount=tax, items=[])
    _, bal = acc.balance_journal(JOURNAL_OK, "purchase")
    assert "TVA_RATE" not in codes(acc.tax_alerts(inv, acc.validate_identifiers(inv), bal))


def test_items_not_matching_total_is_flagged():
    inv = invoice(items=[dict(description="x", quantity=1, unit_price=100, total=100)])
    _, bal = acc.balance_journal(JOURNAL_OK, "purchase")
    assert "MATH_DISCREPANCY" in codes(acc.tax_alerts(inv, acc.validate_identifiers(inv), bal))


def test_pc_compta_rows_format():
    rows = acc.pc_compta_rows(JOURNAL_OK, invoice(), "purchase")
    assert [r["Compte"] for r in rows] == ["607000", "445600", "401000"]
    assert {r["Journal"] for r in rows} == {"HA"} and rows[0]["Date"] == "03/11/2026"
    assert acc.pc_compta_rows(JOURNAL_OK, invoice(), "sale")[0]["Journal"] == "VE"
