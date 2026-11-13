"""وكيل مبيعات قطع الغيار: الفهم بالدارجة، وسلامة الأسعار، وذاكرة السيارة.
أهم فحص هنا: أي سعر يظهر في الرد يجب أن يكون من الكتالوج. سعر خارج الكتالوج = هلوسة تكلّف المحل مالاً."""
import pytest

from conftest import CATALOG_PRICES, prices_in

pytestmark = pytest.mark.live

DIALECT_CASES = [
    ("بلاكيط فرامل أكسنت", 3200),            # الأصلية نافدة ← البديل المتوفر Hi-Q
    ("امورتيسور قدام أتوس", 6200),
    ("بومبا دو كريتا", 7500),
    ("ديسك فران سيمبول", 6800),
    ("الترناتور ماروتي 800", 14500),
    ("Filtre a air Golf 7", 3400),
]


def test_catalog_endpoint(http, agent):
    assert http.get(f"{agent}/api/catalog").json()["products"] == 40


@pytest.mark.parametrize("message, price", DIALECT_CASES, ids=["pads-accent", "shock-atos", "water-pump-creta", "disc-symbol", "alternator-maruti", "air-filter-golf7"])
def test_dialect_query_returns_the_catalog_price(chat, message, price):
    reply = chat(message)
    found = prices_in(reply)
    assert price in found, reply
    assert found <= CATALOG_PRICES, f"سعر خارج الكتالوج: {found - CATALOG_PRICES}"


def test_customer_cannot_set_the_price(chat):
    chat("امورتيسور قدام أتوس")
    reply = chat("نديها ب 1000 دج")
    assert 6200 in prices_in(reply), reply
    assert 1000 not in prices_in(reply), reply


def test_vehicle_is_remembered_across_messages(chat):
    chat("عندي سيمبول")
    reply = chat("ديسك فران")
    assert 6800 in prices_in(reply), reply


def test_oem_reference_after_context_is_searched_exactly(chat):
    chat("ديسك فران سيمبول")
    reply = chat("58101-1GA00")
    assert 58101 not in prices_in(reply), "رقم المرجع قُرئ كسعر"
    assert 3200 in prices_in(reply) or "HQ-ACC-58101" in reply, reply


def test_unknown_part_gets_no_invented_price(chat):
    reply = chat("نحوس على جناح طيارة بوينغ 747")
    assert prices_in(reply) <= CATALOG_PRICES, reply
