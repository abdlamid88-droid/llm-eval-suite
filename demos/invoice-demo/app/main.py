"""ديمو «قارئ الفواتير الذكي»: رفع فاتورة ← استخراج ← قيد SCF ← تحقق جبائي ← تصدير Excel/PC Compta.
لا يُحفظ أي ملف ولا أي نتيجة على الخادم (Stateless).
"""
import csv
import io
import logging
import os
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from pydantic import BaseModel
from pypdf import PdfReader

from . import accounting
from .extractor import ProviderError, QuotaError, extract

log = logging.getLogger("uvicorn.error")

MAX_UPLOAD_MB = float(os.getenv("MAX_UPLOAD_MB", "5"))
MAX_PDF_PAGES = int(os.getenv("MAX_PDF_PAGES", "3"))
EXTRACTS_PER_HOUR = int(os.getenv("EXTRACTS_PER_HOUR", "10"))
DAILY_EXTRACT_CAP = int(os.getenv("DAILY_EXTRACT_CAP", "150"))

STATIC = Path(__file__).parent / "static"
_hits: dict[str, deque] = defaultdict(deque)
_daily = {"day": time.strftime("%Y-%m-%d"), "count": 0}

app = FastAPI(title="Invoice Reader Demo", docs_url=None, redoc_url=None, openapi_url=None)
router = APIRouter()


@app.exception_handler(QuotaError)
def quota_error(_request, _exc):
    return JSONResponse({"detail": "النسخة التجريبية استهلكت حصتها المجانية مؤقتاً. حاول بعد دقيقة، أو غداً إن استمر."}, 429)


@app.exception_handler(ProviderError)
def provider_error(_request, exc):
    log.error("خطأ من Gemini: %s", exc)
    return JSONResponse({"detail": "تعذر تحليل الفاتورة الآن، حاول بعد قليل."}, 503)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")


def _rate_limit(key: str, limit: int, window: int = 3600):
    now = time.time()
    q = _hits[key]
    while q and q[0] < now - window:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(429, "تجاوزت حد الاستخدام في النسخة التجريبية، حاول بعد قليل.")
    q.append(now)


def _sniff_mime(data: bytes) -> str | None:
    if data.startswith(b"%PDF"):
        return "application/pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


@router.get("/")
def index():
    return FileResponse(STATIC / "index.html")


# بدون شرطة أخيرة: نخدم الصفحة مباشرة بدل إعادة توجيه قد تنتهي على http
@app.get("/invoices", include_in_schema=False)
def index_no_slash():
    return FileResponse(STATIC / "index.html")


@router.get("/sample-invoice.png")
def sample():
    return FileResponse(STATIC / "sample-invoice.png", media_type="image/png")


@router.get("/health")
def health():
    return {"ok": True}


@router.post("/api/extract")
def extract_invoice(
    request: Request,
    file: UploadFile = File(...),
    invoice_type: str = Form("purchase"),
    lang: str = Form("ar"),
):
    if invoice_type not in ("purchase", "sale") or lang not in ("ar", "fr"):
        raise HTTPException(400, "خيارات غير صالحة.")
    data = file.file.read(int(MAX_UPLOAD_MB * 1024 * 1024) + 1)
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"الحد الأقصى لحجم الملف {MAX_UPLOAD_MB:g} ميغابايت.")
    mime = _sniff_mime(data)
    if not mime:
        raise HTTPException(400, "يُقبل فقط: صورة (JPG، PNG، WebP) أو ملف PDF.")
    if mime == "application/pdf":
        try:
            pages = len(PdfReader(io.BytesIO(data)).pages)
        except Exception:
            raise HTTPException(400, "تعذرت قراءة ملف PDF.")
        if pages > MAX_PDF_PAGES:
            raise HTTPException(400, f"الحد الأقصى في النسخة التجريبية {MAX_PDF_PAGES} صفحات.")

    _rate_limit(f"x:{_client_ip(request)}", EXTRACTS_PER_HOUR)
    today = time.strftime("%Y-%m-%d")
    if _daily["day"] != today:
        _daily.update(day=today, count=0)
    if _daily["count"] >= DAILY_EXTRACT_CAP:
        raise HTTPException(429, "بلغت النسخة التجريبية حدها اليومي، عد غداً.")
    _daily["count"] += 1

    started = time.perf_counter()
    inv = extract(data, mime, invoice_type, lang)
    if not inv.get("is_invoice", True):
        raise HTTPException(422, "لا تبدو هذه الوثيقة فاتورة. جرّب صورة فاتورة أوضح.")

    journal, balance = accounting.balance_journal(inv.pop("journal_entry", []), invoice_type)
    ids = accounting.validate_identifiers(inv)
    return {
        "invoice": inv,
        "invoice_type": invoice_type,
        "journal": journal,
        "balance": balance,
        "identifiers": ids,
        "alerts": accounting.tax_alerts(inv, ids, balance),
        "seconds": round(time.perf_counter() - started, 1),
    }


class ExportBody(BaseModel):
    invoice: dict
    invoice_type: str = "purchase"
    journal: list[dict]


def _check_export(body: ExportBody):
    if body.invoice_type not in ("purchase", "sale") or len(body.journal) > 50 or len(body.invoice.get("items") or []) > 200:
        raise HTTPException(400, "بيانات غير صالحة.")


@router.post("/api/export/pccompta")
def export_pccompta(body: ExportBody):
    _check_export(body)
    rows = accounting.pc_compta_rows(body.journal, body.invoice, body.invoice_type)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["Date", "Journal", "Compte", "Auxiliaire", "N_Piece", "Libelle", "Debit", "Credit"], delimiter=";")
    w.writeheader()
    w.writerows(rows)
    return Response(
        ("﻿" + buf.getvalue()).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="pc_compta_journal.csv"'},
    )


@router.post("/api/export/xlsx")
def export_xlsx(body: ExportBody):
    _check_export(body)
    inv = body.invoice
    head = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor="0F6E56")

    def header(ws, cols):
        ws.append(cols)
        for c in ws[ws.max_row]:
            c.font, c.fill = head, fill
            c.alignment = Alignment(horizontal="center")

    wb = Workbook()
    ws = wb.active
    ws.title = "الفاتورة"
    ws.sheet_view.rightToLeft = True
    header(ws, ["الحقل", "القيمة"])
    for label, key in [("الطرف الآخر", "vendor_name"), ("رقم الفاتورة", "invoice_number"), ("التاريخ", "date"),
                       ("العملة", "currency"), ("الإجمالي TTC", "total_amount"), ("الرسم TVA", "tax_amount"),
                       ("التصنيف", "category"), ("NIF", "nif"), ("RC", "rc"), ("Article", "article_imposition"), ("NIS", "nis")]:
        ws.append([label, inv.get(key, "")])
    ws.append([])
    header(ws, ["الوصف", "الكمية", "سعر الوحدة", "المجموع"])
    for it in inv.get("items") or []:
        ws.append([it.get("description", ""), it.get("quantity", 0), it.get("unit_price", 0), it.get("total", 0)])
    for col, width in zip("ABCD", (38, 14, 16, 16)):
        ws.column_dimensions[col].width = width

    wj = wb.create_sheet("القيد المحاسبي")
    wj.sheet_view.rightToLeft = True
    header(wj, ["الحساب", "مدين", "دائن"])
    for e in body.journal:
        wj.append([e.get("account", ""), e.get("debit", 0), e.get("credit", 0)])
    n = wj.max_row
    wj.append(["المجموع", f"=SUM(B2:B{n})", f"=SUM(C2:C{n})"])
    wj[wj.max_row][0].font = Font(bold=True)
    wj.column_dimensions["A"].width = 42
    wj.column_dimensions["B"].width = wj.column_dimensions["C"].width = 16

    wp = wb.create_sheet("PC Compta")
    rows = accounting.pc_compta_rows(body.journal, inv, body.invoice_type)
    header(wp, ["Date", "Journal", "Compte", "Auxiliaire", "N_Piece", "Libelle", "Debit", "Credit"])
    for r in rows:
        wp.append(list(r.values()))
    wp.column_dimensions["F"].width = 40

    for sheet in (ws, wj, wp):
        for row in sheet.iter_rows():
            for c in row:
                if isinstance(c.value, float):
                    c.number_format = "#,##0.00"

    out = io.BytesIO()
    wb.save(out)
    return Response(
        out.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="facture_scf.xlsx"'},
    )


# يعمل التطبيق سواء مرّر Tailscale المسار /invoices كما هو أو حذفه
app.include_router(router)
app.include_router(router, prefix="/invoices")
