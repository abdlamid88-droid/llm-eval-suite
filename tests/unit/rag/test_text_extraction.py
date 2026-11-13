"""استخراج النص العربي من PDF: أهم مصدر للأخطاء الصامتة في أنظمة RAG العربية."""
import pytest

from app import rag


@pytest.mark.parametrize("raw, expected", [
    ("ﻣﺮﺣﺒﺎ", "مرحبا"),          # أشكال العرض (Presentation Forms) ← حروف أصلية
    ("وتزویده", "وتزويده"),                               # ياء فارسية ← عربية
    ("ھو", "هو"),                                          # هاء فارسية ← عربية
    ("کتاب", "كتاب"),                                      # كاف فارسية ← عربية
])
def test_normalization(raw, expected):
    assert rag._norm(raw) == expected


def test_logical_text_is_not_reversed():
    assert not rag._looks_reversed("الذكاء الاصطناعي في التأمين والبيانات الصحية")


def test_visual_order_text_is_detected():
    visual = "يعانطصلاا ءاكذلا يف نيمأتلا تانايبلاو ةيحصلا"
    assert rag._looks_reversed(visual)


def test_visual_to_logical_restores_latin_runs_and_brackets():
    # كما يخرج من PDF صدّره Chrome/Google Docs: السطر معكوس والأقواس مقلوبة
    visual = "(InsurTech) تانايبلاو"
    assert rag._visual_to_logical(visual) == "والبيانات (InsurTech)"


def test_lam_alef_ligature_survives_reversal():
    # «ﻻ» حرف واحد: يجب العكس قبل التطبيع وإلا خرجت «االبتكار» بدل «الابتكار»
    visual_line = "رﺎﻜﺘﺑﻻا"
    assert rag._norm(rag._visual_to_logical(visual_line)) == "الابتكار"


def test_word_per_line_pdf_text_is_joined(monkeypatch):
    class Page:
        def extract_text(self, extraction_mode="plain"):
            return "مشروع\n \nبينة\n \nمحرك"
    assert rag._page_text(Page()) == "مشروع بينة محرك"


def test_chunks_keep_page_numbers_and_overlap(monkeypatch):
    monkeypatch.setattr(rag, "CHUNK_SIZE", 100)
    monkeypatch.setattr(rag, "CHUNK_OVERLAP", 20)
    text = " ".join(f"كلمة{i}" for i in range(80))
    chunks = rag.chunk_pages([(3, text)])
    assert all(page == 3 for page, _ in chunks)
    assert len(chunks) > 1
    # التداخل موجود (المقاطع تُقَص من الفراغات، فلا نقارن بالحرف)
    assert chunks[1][1][:12].strip() in chunks[0][1]


def test_too_many_pages_is_rejected():
    from conftest import make_pdf
    with pytest.raises(ValueError):
        rag.extract_pages(make_pdf(["a"] * 5), max_pages=3)
