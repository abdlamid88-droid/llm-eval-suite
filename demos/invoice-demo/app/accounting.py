"""المنطق المحاسبي الجزائري (SCF): موازنة القيد، التحقق من المعرفات الجبائية، التنبيهات، وتصدير PC Compta.
مأخوذ من مشروع blind_invoice_mvp مع تصحيحات: لا يُخفى فرق كبير في القيد، وتصحيح عتبات الدفع النقدي.
"""
import re
from datetime import datetime

ROUNDING_TOLERANCE = 1.0  # فرق تقريب مقبول بالدينار يُمتص تلقائياً؛ ما فوقه يُبلَّغ ولا يُخفى


def to_float(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    m = re.search(r"[-+]?\d*\.?\d+", str(value).replace(",", "").replace(" ", ""))
    return float(m.group()) if m else 0.0


def balance_journal(entries: list[dict], invoice_type: str) -> tuple[list[dict], dict]:
    """يقرّب القيد ويمتص فرق التقريب الصغير في حساب الطرف الآخر (401 للمشتريات، 411 للمبيعات).
    الفرق الأكبر من حد التقريب لا يُعدَّل، بل يُعاد كحالة «غير متوازن» ليراه المستخدم."""
    rows = [
        {"account": str(e.get("account", "")).strip(), "debit": round(to_float(e.get("debit")), 2),
         "credit": round(to_float(e.get("credit")), 2)}
        for e in entries or []
    ]
    debit = round(sum(r["debit"] for r in rows), 2)
    credit = round(sum(r["credit"] for r in rows), 2)
    diff = round(debit - credit, 2)
    adjusted = False
    if rows and diff and abs(diff) <= ROUNDING_TOLERANCE:
        party = "411" if invoice_type == "sale" else "401"
        target = next((r for r in rows if r["account"].startswith(party)), rows[-1])
        if target["credit"] or (invoice_type != "sale" and not target["debit"]):
            target["credit"] = round(target["credit"] + diff, 2)
        else:
            target["debit"] = round(target["debit"] - diff, 2)
        debit = round(sum(r["debit"] for r in rows), 2)
        credit = round(sum(r["credit"] for r in rows), 2)
        adjusted = True
    return rows, {
        "total_debit": debit,
        "total_credit": credit,
        "difference": round(debit - credit, 2),
        "balanced": abs(debit - credit) < 0.005,
        "rounding_adjusted": adjusted,
    }


def _digits(s) -> str:
    return re.sub(r"[\s\-\./]", "", str(s or ""))


def validate_identifiers(data: dict) -> dict:
    """التحقق من صيغة المعرفات الجبائية الجزائرية (الصيغة فقط، لا التحقق من وجودها لدى الإدارة)."""
    out = {}

    nif = _digits(data.get("nif"))
    if not nif:
        out["nif"] = {"value": "", "valid": None, "message": "غير موجود في الفاتورة"}
    elif not nif.isdigit() or len(nif) not in (15, 20):
        out["nif"] = {"value": nif, "valid": False, "message": "يجب أن يكون 15 أو 20 رقماً"}
    else:
        out["nif"] = {"value": nif, "valid": True, "message": "صيغة صحيحة"}

    rc = _digits(data.get("rc")).upper()
    if not rc:
        out["rc"] = {"value": "", "valid": None, "message": "غير موجود في الفاتورة"}
    elif re.fullmatch(r"\d{2}[AB]\d{7}(\d{2})?", rc) or (rc.isdigit() and len(rc) in (9, 10)):
        out["rc"] = {"value": rc, "valid": True, "message": "صيغة صحيحة"}
    else:
        out["rc"] = {"value": rc, "valid": False, "message": "صيغة غير مطابقة (مثال: 16B0123456)"}

    art = _digits(data.get("article_imposition"))
    if not art:
        out["article"] = {"value": "", "valid": None, "message": "غير موجود في الفاتورة"}
    elif not art.isdigit() or len(art) not in (9, 11):
        out["article"] = {"value": art, "valid": False, "message": "يجب أن يكون 9 أو 11 رقماً"}
    else:
        out["article"] = {"value": art, "valid": True, "message": "صيغة صحيحة"}

    nis = _digits(data.get("nis"))
    if not nis:
        out["nis"] = {"value": "", "valid": None, "message": "غير موجود في الفاتورة"}
    elif not nis.isdigit() or len(nis) != 15:
        out["nis"] = {"value": nis, "valid": False, "message": "يجب أن يكون 15 رقماً"}
    else:
        out["nis"] = {"value": nis, "valid": True, "message": "صيغة صحيحة"}
    return out


def tax_alerts(data: dict, ids: dict, balance: dict) -> list[dict]:
    """تنبيهات استرشادية. القواعد القانونية تتغير بقوانين المالية، فالعبارات تحث على التحقق."""
    alerts = []
    total = to_float(data.get("total_amount"))
    tax = to_float(data.get("tax_amount"))
    ht = total - tax

    items = data.get("items") or []
    if items:
        items_ht = sum(to_float(i.get("total")) for i in items)
        if abs(items_ht - ht) > 2:
            alerts.append({"severity": "warning", "code": "MATH_DISCREPANCY",
                           "message": f"مجموع البنود ({items_ht:,.2f} دج) لا يطابق الإجمالي دون الرسم ({ht:,.2f} دج)."})

    if tax > 0 and ht > 0:
        rate = tax / ht * 100
        if not any(abs(rate - r) < 1 for r in (9, 19)):
            alerts.append({"severity": "warning", "code": "TVA_RATE",
                           "message": f"نسبة الرسم الضمنية {rate:.1f}% لا تطابق النسبتين 19% و9%. قد يكون في الإجمالي طابع أو رسوم أخرى، فراجع."})

    if not balance["balanced"]:
        alerts.append({"severity": "critical", "code": "UNBALANCED",
                       "message": f"القيد غير متوازن بفارق {balance['difference']:,.2f} دج. لم يُعدَّل تلقائياً لأن الفرق أكبر من فرق تقريب، فراجع الأرقام."})

    if total > 300_000:
        alerts.append({"severity": "critical", "code": "CASH_CHARGE",
                       "message": "الفاتورة تتجاوز 300,000 دج (TTC): إن دُفعت نقداً فلا تُقبل في خصم الأعباء (المادة 169 من قانون الضرائب المباشرة، قانون المالية 2018). تحقق من وسيلة الدفع."})
    if total > 100_000:
        alerts.append({"severity": "warning", "code": "CASH_TVA",
                       "message": "الفاتورة تتجاوز 100,000 دج (TTC): الدفع النقدي قد يمنع خصم الرسم على القيمة المضافة (المادة 30 من قانون الرسوم على رقم الأعمال). تحقق من وسيلة الدفع وآخر قانون مالية."})

    if ids["nif"]["valid"] is None:
        alerts.append({"severity": "warning", "code": "MISSING_NIF", "message": "رقم التعريف الجبائي (NIF) غير موجود في الفاتورة."})
    elif ids["nif"]["valid"] is False:
        alerts.append({"severity": "critical", "code": "INVALID_NIF", "message": f"رقم NIF بصيغة غير صحيحة: {ids['nif']['message']}."})
    if ids["rc"]["valid"] is False:
        alerts.append({"severity": "warning", "code": "INVALID_RC", "message": f"رقم السجل التجاري بصيغة غير صحيحة: {ids['rc']['message']}."})
    return alerts


def pc_compta_rows(entries: list[dict], data: dict, invoice_type: str) -> list[dict]:
    """صفوف قيد بتنسيق PC Compta: حساب من 6 خانات، تاريخ DD/MM/YYYY، يومية HA أو VE."""
    journal = "VE" if invoice_type == "sale" else "HA"
    date = str(data.get("date") or "")
    try:
        date = datetime.strptime(date.strip(), "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        pass
    number = str(data.get("invoice_number") or "")
    label = f"Facture N: {number} - {data.get('vendor_name') or ''}"
    rows = []
    for e in entries:
        m = re.match(r"^(\d+)", e["account"])
        account = m.group(1).ljust(6, "0") if m else ("700000" if journal == "VE" else "600000")
        rows.append({"Date": date, "Journal": journal, "Compte": account, "Auxiliaire": "",
                     "N_Piece": number, "Libelle": label, "Debit": e["debit"], "Credit": e["credit"]})
    return rows
