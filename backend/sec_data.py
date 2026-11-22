"""
ABD SEC XBRL (EDGAR "company facts") verisi.

ABD'de 10-K/10-Q veren sirketler icin bilanconun ana kaynagi SEC'tir: resmi, ucretsiz ve
Yahoo'daki bos donem / gecikme / tanim farki sorunlarini tasimaz. Yahoo yedek kaynak olarak kalir.

* SEC, istek yapan uygulamanin tanimlanmasini ister: SEC_USER_AGENT ortam degiskeniyle
  "UygulamaAdi iletisim@ornek.com" biciminde kendi bilginizi verebilirsiniz.
* Dosyalar `.cache/sec/` altinda diskte onbelleklenir (ag ve SEC'e yuk azaltilir).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache" / "sec"
TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
TICKER_TTL = 7 * 24 * 3600
FACTS_TTL = 12 * 3600
HTTP_TIMEOUT = 20
FORMS = {"10-K", "10-Q", "10-K/A", "10-Q/A", "10-KT"}
# Akis kalemi en guncel bilanco tarihinden bu kadar gun eskiyse kullanilmaz (eski etiket)
MAX_FLOW_LAG_DAYS = 45

_LOCK = threading.Lock()


def _user_agent() -> str:
    return os.environ.get("SEC_USER_AGENT") or "HisseRontgen/1.0"


def _fetch_json(url: str, cache_file: Path, ttl: int) -> Any | None:
    with _LOCK:
        if cache_file.exists() and (time.time() - cache_file.stat().st_mtime) < ttl:
            try:
                return json.loads(cache_file.read_text(encoding="utf-8"))
            except Exception:
                pass
    req = urllib.request.Request(url, headers={"User-Agent": _user_agent(), "Accept-Encoding": "identity"})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
        data = json.loads(raw)
    except Exception:
        # Ag hatasinda varsa eski onbellegi kullan
        if cache_file.exists():
            try:
                return json.loads(cache_file.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None
    with _LOCK:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_file.with_suffix(".tmp")
        tmp.write_text(raw, encoding="utf-8")
        os.replace(tmp, cache_file)
    return data


def cik_for(ticker: str) -> int | None:
    data = _fetch_json(TICKER_URL, CACHE_DIR / "company_tickers.json", TICKER_TTL)
    if not data:
        return None
    t = ticker.upper().replace(".", "-")
    for row in data.values():
        if str(row.get("ticker", "")).upper() == t:
            return int(row["cik_str"])
    return None


# ---------------------------------------------------------------- XBRL yardimcilari

def _d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def _facts(us: dict, concept: str) -> list[dict]:
    node = us.get(concept)
    if not node:
        return []
    units = node.get("units", {})
    xs = units.get("USD") or units.get("shares") or []
    return [x for x in xs if x.get("form") in FORMS]


def _instant(us: dict, concepts: list[str], date: str) -> tuple[float | None, str | None]:
    for c in concepts:
        xs = [x for x in _facts(us, c) if "start" not in x and x["end"] == date]
        if xs:
            return float(max(xs, key=lambda x: x["filed"])["val"]), c
    return None, None


def _ttm(us: dict, concepts: list[str], bal_date: str) -> tuple[float | None, str | None]:
    """
    Son 12 ay: 10-Q'lar yil basindan itibaren KUMULATIF raporladigi icin
    TTM = son yillik + bu yilin kumulatifi - gecen yilin ayni donem kumulatifi.
    """
    for c in concepts:
        xs = [x for x in _facts(us, c) if "start" in x]
        if not xs:
            continue
        end = max(x["end"] for x in xs)
        if (_d(bal_date) - _d(end)).days > MAX_FLOW_LAG_DAYS:
            continue  # etiket artik kullanilmiyor
        cur = sorted((x for x in xs if x["end"] == end), key=lambda x: (_d(x["end"]) - _d(x["start"])).days)
        ytd = cur[-1]
        dur = (_d(ytd["end"]) - _d(ytd["start"])).days
        if dur > 350:
            return float(ytd["val"]), end
        annual = [x for x in xs if 350 < (_d(x["end"]) - _d(x["start"])).days < 380 and x["end"] < end]
        if not annual:
            continue
        fy = max(annual, key=lambda x: (x["end"], x["filed"]))
        target = _d(end) - dt.timedelta(days=364)
        prior = [x for x in xs if abs((_d(x["end"]) - target).days) < 12
                 and abs((_d(x["end"]) - _d(x["start"])).days - dur) < 12]
        if not prior:
            continue
        pr = max(prior, key=lambda x: x["filed"])
        return float(fy["val"]) + float(ytd["val"]) - float(pr["val"]), end
    return None, None


def _maturities(us: dict) -> dict[str, float]:
    keys = {
        "next12": "LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths",
        "rem": "LongTermDebtMaturitiesRepaymentsOfPrincipalRemainderOfFiscalYear",
        "y2": "LongTermDebtMaturitiesRepaymentsOfPrincipalInYearTwo",
    }
    ends = [x["end"] for c in keys.values() for x in _facts(us, c)]
    if not ends:
        return {}
    end = max(ends)
    out = {"as_of": end}
    for k, c in keys.items():
        v = [x for x in _facts(us, c) if x["end"] == end]
        if v:
            out[k] = float(max(v, key=lambda x: x["filed"])["val"])
    return out


REVENUE = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "RevenueFromContractWithCustomerIncludingAssessedTax",
           "RevenueFromContractWithCustomerProductAndServiceExcludingAssessedTax", "SalesRevenueNet"]
OPINC = ["OperatingIncomeLoss"]
OCF = ["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"]
CAPEX = ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"]
DA = ["DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet", "DepreciationAndAmortization",
      "Depreciation"]
CASH = ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"]
ST_INV = ["ShortTermInvestments", "MarketableSecuritiesCurrent", "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
          "AvailableForSaleSecuritiesDebtSecurities"]
CONVERTIBLE = ["ConvertibleNotesPayable", "ConvertibleDebtNoncurrent", "ConvertibleLongTermNotesPayable",
               "ConvertibleSeniorNotesNoncurrent"]


def _instant_or_parts(us: dict, base: str, date: str) -> float | None:
    """Toplam etiket yoksa kisa + uzun vadeli parcalari toplar (orn. OperatingLeaseLiabilityCurrent)."""
    total, _ = _instant(us, [base], date)
    if total is not None:
        return total
    cur, _ = _instant(us, [base + "Current"], date)
    non, _ = _instant(us, [base + "Noncurrent"], date)
    if cur is None and non is None:
        return None
    return (cur or 0.0) + (non or 0.0)


def _convertible(us: dict, date: str) -> float | None:
    """Donustururulebilir borc: bilinen etiketler, yoksa adinda 'Convertible' gecen borc etiketleri."""
    val, _ = _instant(us, CONVERTIBLE, date)
    if val is not None:
        return val
    best = None
    for concept in us:
        if "Convertible" in concept and ("Notes" in concept or "Debt" in concept) and "Conversion" not in concept                 and ("Payable" in concept or "Noncurrent" in concept or concept.endswith("Debt")):
            v, _ = _instant(us, [concept], date)
            if v is not None and v > 0:
                best = max(best or 0.0, v)
    return best


def extract(facts_json: dict) -> dict[str, Any] | None:
    """Company facts JSON'undan bilanco ozeti cikarir (dolar cinsinden)."""
    us = (facts_json or {}).get("facts", {}).get("us-gaap")
    if not us:
        return None  # 20-F (IFRS) veren yabanci sirket ya da veri yok
    assets = [x for x in _facts(us, "Assets") if "start" not in x]
    if not assets:
        return None
    bd = max(x["end"] for x in assets)

    cash, _ = _instant(us, CASH, bd)
    st_inv, _ = _instant(us, ST_INV, bd)

    # Toplam finansal borc (kiralar haric): once toplam etiketleri, yoksa kisa + uzun vade
    debt, debt_tag = _instant(us, ["DebtLongtermAndShorttermCombinedAmount", "LongTermDebt"], bd)
    if debt is not None and debt_tag == "LongTermDebt":
        cp, _ = _instant(us, ["CommercialPaper"], bd)
        stb, _ = _instant(us, ["ShortTermBorrowings"], bd)
        debt += (cp or 0.0) + (stb or 0.0)
    if debt is None:
        cur, _ = _instant(us, ["DebtCurrent"], bd)  # DebtCurrent ticari senetleri de kapsar
        if cur is None:
            ltc, _ = _instant(us, ["LongTermDebtCurrent", "NotesPayableCurrent"], bd)
            cp, _ = _instant(us, ["CommercialPaper"], bd)
            stb, _ = _instant(us, ["ShortTermBorrowings"], bd)
            if any(v is not None for v in (ltc, cp, stb)):
                cur = (ltc or 0.0) + (cp or 0.0) + (stb or 0.0)
        lt, _ = _instant(us, ["LongTermDebtNoncurrent", "LongTermNotesAndLoans", "LongTermDebtAndCapitalLeaseObligations",
                              "ConvertibleNotesPayableNoncurrent"], bd)
        if cur is not None or lt is not None:
            debt = (cur or 0.0) + (lt or 0.0)
    op_lease = _instant_or_parts(us, "OperatingLeaseLiability", bd)
    fin_lease = _instant_or_parts(us, "FinanceLeaseLiability", bd)
    conv = _convertible(us, bd)

    rev, rev_end = _ttm(us, REVENUE, bd)
    op, _ = _ttm(us, OPINC, bd)
    ocf, _ = _ttm(us, OCF, bd)
    capex, _ = _ttm(us, CAPEX, bd)
    da, _ = _ttm(us, DA, bd)
    gp, _ = _ttm(us, ["GrossProfit"], bd)
    ni, _ = _ttm(us, ["NetIncomeLoss", "ProfitLoss"], bd)
    interest, _ = _ttm(us, ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt"], bd)

    mat = _maturities(us)
    due12 = None
    due24 = None
    if mat:
        first = mat.get("next12", 0.0) or 0.0
        first += mat.get("rem", 0.0) or 0.0
        due12 = first
        due24 = first + (mat.get("y2", 0.0) or 0.0)

    leases = None
    if op_lease is not None or fin_lease is not None:
        leases = (op_lease or 0.0) + (fin_lease or 0.0)
    return {
        "source": "SEC EDGAR XBRL",
        "balance_date": bd,
        "ttm_through": rev_end,
        "revenue_ttm": rev,
        "operating_income_ttm": op,
        "ocf_ttm": ocf,
        "capex_ttm": capex,
        "fcf_ttm": (ocf - abs(capex)) if (ocf is not None and capex is not None) else None,
        "da_ttm": da,
        "gross_profit_ttm": gp,
        "net_income_ttm": ni,
        "interest_expense_ttm": interest,
        "cash_and_st": (cash or 0.0) + (st_inv or 0.0) if cash is not None else None,
        "debt_ex_leases": debt,
        "lease_liabilities": leases,
        "convertible_debt": conv,
        "debt_due_12m": due12,
        "debt_due_24m": due24,
        "maturities_as_of": mat.get("as_of") if mat else None,
    }


def fetch_sec_summary(ticker: str) -> dict[str, Any] | None:
    cik = cik_for(ticker)
    if cik is None:
        return None
    data = _fetch_json(FACTS_URL.format(cik=cik), CACHE_DIR / f"CIK{cik:010d}.json", FACTS_TTL)
    if not data:
        return None
    try:
        return extract(data)
    except Exception:
        return None
