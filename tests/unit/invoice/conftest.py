"""إعداد اختبارات قارئ الفواتير: Gemini وهمي يعيد فاتورة مهيكلة جاهزة."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

DEMO = Path(__file__).resolve().parents[3] / "demos" / "invoice-demo"
sys.path.insert(0, str(DEMO))
os.environ.update(GEMINI_API_KEY="test-key", EXTRACTS_PER_HOUR="1000", DAILY_EXTRACT_CAP="1000")

SAMPLE_PNG = (DEMO / "app" / "static" / "sample-invoice.png").read_bytes()

JOURNAL_OK = [
    {"account": "607 - مشتريات", "debit": 120000, "credit": 0},
    {"account": "4456 - TVA", "debit": 22800, "credit": 0},
    {"account": "401 - موردو المخزونات", "debit": 0, "credit": 142800},
]


def invoice(**overrides):
    base = dict(
        is_invoice=True, vendor_name="SARL EL BAHDJA FOURNITURES", invoice_number="FA-2026-0147",
        date="2026-11-03", currency="DZD", total_amount=142800, tax_amount=22800, category="مشتريات",
        nif="000216098765432", rc="16B0987654", article_imposition="16012345678", nis="000216010203040",
        items=[dict(description="Ramettes", quantity=40, unit_price=750, total=30000),
               dict(description="Toner", quantity=12, unit_price=4500, total=54000),
               dict(description="Classeurs", quantity=60, unit_price=600, total=36000)],
        journal_entry=JOURNAL_OK, uncertain_fields=[], notes="",
    )
    base.update(overrides)
    return base


class FakeModels:
    def __init__(self):
        self.next = invoice()
        self.error = None
        self.errors = []  # أخطاء تُرفع بالترتيب قبل النجاح (لاختبار إعادة المحاولة)
        self.calls = []

    def generate_content(self, model, contents, config):
        self.calls.append({"model": model, "mime": contents[0].inline_data.mime_type, "schema": config.response_schema})
        if self.errors:
            raise self.errors.pop(0)
        if self.error:
            raise self.error
        from app.extractor import Invoice
        return SimpleNamespace(parsed=Invoice(**self.next), text="")


@pytest.fixture()
def gemini(monkeypatch):
    from app import extractor
    monkeypatch.setattr(extractor, "RETRY_DELAY", 0, raising=False)
    fake = FakeModels()
    monkeypatch.setattr(extractor, "_client", SimpleNamespace(models=fake))
    return fake


@pytest.fixture()
def client(gemini):
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c


def upload(client, data=SAMPLE_PNG, name="f.png", prefix="/invoices", **form):
    return client.post(f"{prefix}/api/extract", files={"file": (name, data)},
                       data={"invoice_type": "purchase", "lang": "ar", **form})
