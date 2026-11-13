"""اختبارات الواجهة بـ Playwright: ما يراه الزائر فعلاً، على الحاسوب والهاتف."""
import pytest

from conftest import AGENT_URL, INVOICES_URL, RAG_URL

pytestmark = [pytest.mark.live, pytest.mark.ui]

VIEWPORTS = {"desktop": {"width": 1200, "height": 900}, "phone": {"width": 390, "height": 844}}


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture(params=list(VIEWPORTS))
def page(browser, request):
    ctx = browser.new_context(viewport=VIEWPORTS[request.param])
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    yield pg
    ctx.close()


def no_horizontal_scroll(page):
    return page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_rag_page_loads(page, rag):
    page.goto(RAG_URL + "/")
    assert page.locator("h1").inner_text() == "اسأل وثيقتك"
    assert no_horizontal_scroll(page) and not page.errors


def test_invoice_sample_flow(page, invoices):
    page.goto(INVOICES_URL)
    page.click("#sample")
    page.wait_for_selector("#result", state="visible", timeout=60_000)
    assert "متوازن" in page.locator("#balance").inner_text()
    with page.expect_download() as dl:
        page.click("#dl-xlsx")
    assert dl.value.suggested_filename.endswith(".xlsx")
    assert no_horizontal_scroll(page) and not page.errors


def test_agent_chat_flow(page, agent):
    page.goto(AGENT_URL)
    page.click("#chips button >> nth=0")
    page.wait_for_selector(".msg.in", timeout=60_000)
    assert "دج" in page.locator(".msg.in").last.inner_text()
    assert no_horizontal_scroll(page) and not page.errors
