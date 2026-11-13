"""استخراج بيانات الفاتورة وتوليد القيد المحاسبي عبر Gemini بمخرجات مهيكلة (Structured Output).
الـ prompt مأخوذ من مشروع blind_invoice_mvp؛ الفرق أن الهيكل يُفرض بمخطط Pydantic فلا يتعطل تحليل JSON.
"""
import logging
import os
import time

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel, Field

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
RETRY_DELAY = float(os.getenv("RETRY_DELAY", "1.5"))
_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


class QuotaError(Exception):
    pass


class ProviderError(Exception):
    pass


class Item(BaseModel):
    description: str
    quantity: float
    unit_price: float
    total: float


class JournalLine(BaseModel):
    account: str = Field(description="رقم الحساب واسمه، مثل: 401 - موردو المخزونات")
    debit: float
    credit: float


class Invoice(BaseModel):
    is_invoice: bool = Field(description="false إن لم تكن الوثيقة فاتورة أو وصلاً")
    vendor_name: str = Field(description="الطرف الآخر: المورد في الشراء، الزبون في البيع")
    invoice_number: str
    date: str = Field(description="YYYY-MM-DD أو فارغ إن لم يوجد")
    currency: str = Field(description="رمز العملة، مثل DZD")
    total_amount: float = Field(description="الإجمالي TTC")
    tax_amount: float = Field(description="مبلغ الرسم على القيمة المضافة")
    category: str
    nif: str
    rc: str
    article_imposition: str
    nis: str
    items: list[Item]
    journal_entry: list[JournalLine]
    uncertain_fields: list[str] = Field(description="أسماء الحقول غير الواضحة في الصورة والتي تحتاج مراجعة بشرية")
    notes: str


SCF_RULES = {
    "purchase": """قواعد القيد المزدوج للمشتريات (SCF):
1. المدين: HT في حساب من الصنف 6 (مثل 607 أو 628) + TVA في 4456. الدائن: TTC في 401.
2. إن تضمنت الفاتورة حقوق طابع (Timbre) أو رسوماً ثابتة فافصلها في الحساب 64.
3. مجموع المدين يساوي مجموع الدائن تماماً.""",
    "sale": """قواعد القيد المزدوج للمبيعات (SCF):
1. المدين: TTC في 411. الدائن: HT في حساب من الصنف 7 (مثل 700 أو 706) + TVA في 4457.
2. حقل vendor_name هنا هو اسم الزبون المكتوب في الفاتورة لا اسم البائع.
3. مجموع المدين يساوي مجموع الدائن تماماً.""",
}

PROMPT = """أنت خبير محاسبة جزائري. استخرج بيانات هذه الفاتورة بدقة.
نوع الفاتورة: {kind}.
اكتب أسماء الحسابات والتصنيف والملاحظات باللغة {lang}.

{rules}

قواعد صارمة:
- استخدم فقط المبالغ والبيانات المكتوبة في الفاتورة. لا تخترع أي رقم أو معرّف.
- إن لم يظهر حقل في الفاتورة فاتركه فارغاً (أو 0 للأرقام)، ولا تخمّنه.
- إن كان حقل غير مقروء بوضوح فاذكر اسمه في uncertain_fields.
- قرّب المبالغ إلى خانتين عشريتين.
- إن لم تكن الوثيقة فاتورة فاجعل is_invoice = false واترك بقية الحقول فارغة."""


log = logging.getLogger("uvicorn.error")


def _call_gemini(**kwargs):
    """استدعاء Gemini مع إعادة محاولة واحدة للأعطال اللحظية.
    أخطاء الشبكة لا تُلتقط بنوع محدد: إصدارات مكتبة Gemini تستخدم httpx أو httpx2 حسب الإصدار،
    والتقاط httpx وحده ترك انقطاع الشبكة يصل للزائر كخطأ 500."""
    for attempt in (1, 2):
        try:
            return _client.models.generate_content(**kwargs)
        except genai_errors.APIError as e:
            if e.code == 429:
                raise QuotaError(str(e)) from e
            if attempt == 1 and (e.code or 0) >= 500:
                log.warning("Gemini %s، إعادة المحاولة", e.code)
                time.sleep(RETRY_DELAY)
                continue
            raise ProviderError(str(e)) from e
        except Exception as e:  # انقطاع الشبكة، مهلة، DNS...
            if attempt == 1:
                log.warning("تعذر الاتصال بـ Gemini (%s)، إعادة المحاولة", e.__class__.__name__)
                time.sleep(RETRY_DELAY)
                continue
            raise ProviderError(f"{e.__class__.__name__}: {e}") from e


def extract(file_bytes: bytes, mime_type: str, invoice_type: str, lang: str) -> dict:
    prompt = PROMPT.format(
        kind="مشتريات (الطرف الآخر هو المورد)" if invoice_type == "purchase" else "مبيعات (الطرف الآخر هو الزبون)",
        lang="الفرنسية" if lang == "fr" else "العربية",
        rules=SCF_RULES[invoice_type],
    )
    resp = _call_gemini(
        model=MODEL,
        contents=[types.Part.from_bytes(data=file_bytes, mime_type=mime_type), prompt],
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
            response_schema=Invoice,
        ),
    )

    parsed = resp.parsed
    if parsed is None:
        try:
            parsed = Invoice.model_validate_json(resp.text or "")
        except ValueError as e:
            raise ProviderError(f"رد غير صالح من النموذج: {e}") from e
    return parsed.model_dump()
