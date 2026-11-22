from __future__ import annotations

import math
from typing import Any

import pandas as pd


def _safe(val: Any, ndigits: int = 2) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return round(f, ndigits)
    except Exception:
        return None


def _row_val(df: pd.DataFrame, names: list[str], col_idx: int = 0) -> float | None:
    """DataFrame icinden olasi satir adlarindan ilk gecerli degeri ceker."""
    if df is None or df.empty or col_idx >= df.shape[1]:
        return None
    for name in names:
        if name in df.index:
            val = df.loc[name].iloc[col_idx]
            if pd.notna(val):
                try:
                    f = float(val)
                    if not (math.isnan(f) or math.isinf(f)):
                        return f
                except Exception:
                    continue
    return None


def _ttm_val(q_df: pd.DataFrame, a_df: pd.DataFrame, names: list[str]) -> float | None:
    """4 ceyrek mevcutsa TTM toplami, yoksa son yillik deger."""
    if q_df is not None and not q_df.empty and q_df.shape[1] >= 4:
        for name in names:
            if name in q_df.index:
                vals = q_df.loc[name].iloc[:4]
                if vals.notna().sum() == 4:
                    total = float(vals.sum())
                    if not (math.isnan(total) or math.isinf(total)):
                        return total
    return _row_val(a_df, names, 0)


def _div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    r = a / b
    if math.isnan(r) or math.isinf(r):
        return None
    return r


def _pct_growth(cur: float | None, prev: float | None) -> float | None:
    if cur is None or prev is None or prev == 0:
        return None
    return ((cur - prev) / abs(prev)) * 100.0


# Esas faaliyet kari: Yahoo'nun "EBIT" satiri (vergi oncesi kar + faiz) yatirim satis
# kazanclari gibi faaliyet disi kalemleri icerir; bu yuzden "Operating Income" onceliklidir.
OPERATING_INCOME_ROWS = ["Operating Income", "Total Operating Income As Reported", "EBIT"]
REVENUE_ROWS = ["Total Revenue", "Operating Revenue"]
NET_INCOME_ROWS = ["Net Income", "Net Income Common Stockholders", "Net Income From Continuing Operation Net Minority Interest"]
DA_CF_ROWS = ["Depreciation And Amortization", "Depreciation Amortization Depletion"]

# Beneish M-Score: gercek veriye dayanan en az bu kadar bilesen yoksa skor hesaplanmaz
BENEISH_MIN_REAL_COMPONENTS = 6

# Kur cevrimi icin yillik / ceyreklik ortalama pencereleri (takvim gunu)
FX_AVG_DAYS_ANNUAL = 365
FX_AVG_DAYS_QUARTER = 91


def _avg_fx(fx_df: pd.DataFrame | None, end: Any, days: int) -> float | None:
    """Verilen donem sonu tarihine kadar `days` gunluk ortalama kur (orn. USDTRY)."""
    if fx_df is None or fx_df.empty or end is None:
        return None
    try:
        end_ts = pd.Timestamp(end)
    except Exception:
        return None
    start_ts = end_ts - pd.Timedelta(days=days)
    window = fx_df.loc[(fx_df.index > start_ts) & (fx_df.index <= end_ts), "Close"]
    if len(window) < 5:
        return None
    val = float(window.mean())
    return val if val > 0 else None


def _usd_growth(cur: float | None, prev: float | None, cur_end: Any, prev_end: Any,
                fx_df: pd.DataFrame | None, days: int) -> float | None:
    """TRY tutarlari donem ortalama USDTRY ile dolara cevirip buyume hesaplar."""
    if cur is None or prev is None:
        return None
    fx_cur = _avg_fx(fx_df, cur_end, days)
    fx_prev = _avg_fx(fx_df, prev_end, days)
    if not fx_cur or not fx_prev:
        return None
    return _pct_growth(cur / fx_cur, prev / fx_prev)


def _col_date(df: pd.DataFrame | None, idx: int) -> Any:
    if df is None or df.empty or idx >= df.shape[1]:
        return None
    return df.columns[idx]


def _col_index_for(df: pd.DataFrame | None, date: Any) -> int | None:
    """Tablodaki ayni donem sutununun indeksi (en fazla 45 gun fark toleransi)."""
    if df is None or df.empty or date is None:
        return None
    try:
        target = pd.Timestamp(date)
        best, best_gap = None, None
        for i, c in enumerate(df.columns):
            gap = abs((pd.Timestamp(c) - target).days)
            if gap <= 45 and (best_gap is None or gap < best_gap):
                best, best_gap = i, gap
        return best
    except Exception:
        return None


def _ebitda_from_parts(op: float | None, da: float | None) -> float | None:
    """FAVOK = Esas faaliyet kari + Amortisman (faaliyet disi kazanclar haric)."""
    if op is None or da is None:
        return None
    return op + abs(da)


class _ScoreCard:
    """
    Puanlari sadece MEVCUT verilerle hesaplar.
    Eksik bir kalem ne puan kazandirir ne de kaybettirir; o kalemin agirligi
    toplamdan cikarilir ve 'veri kapsami' ayrica raporlanir.
    """

    def __init__(self) -> None:
        self.points = 0.0
        self.max_points = 0.0
        self.total_weight = 0.0
        self.missing: list[str] = []

    def add(self, label: str, points: float | None, weight: float) -> None:
        self.total_weight += weight
        if points is None:
            self.missing.append(label)
            return
        self.points += max(0.0, min(weight, points))
        self.max_points += weight

    @property
    def coverage(self) -> float:
        return (self.max_points / self.total_weight) if self.total_weight else 0.0

    def score(self, penalty: float = 0.0) -> int | None:
        if self.max_points <= 0:
            return None
        return int(max(0, min(100, round(self.points / self.max_points * 100.0 - penalty))))


def analyze_fundamental(bundle: dict[str, Any]) -> dict[str, Any]:
    info: dict[str, Any] = bundle["info"]
    inc: pd.DataFrame = bundle["income_stmt"]
    q_inc: pd.DataFrame = bundle["quarterly_income"]
    bal: pd.DataFrame = bundle["balance_sheet"]
    q_bal: pd.DataFrame = bundle["quarterly_balance"]
    cf: pd.DataFrame = bundle["cashflow"]
    q_cf: pd.DataFrame = bundle["quarterly_cashflow"]

    is_bist: bool = bundle["is_bist"]
    # Piyasa degeri ANA birimdedir (GBp ile fiyatlanan LSE hissesinde bile GBP)
    trade_curr: str = bundle.get("currency_major") or bundle["currency"]
    fin_curr: str = bundle["financial_currency"]
    fx: float = bundle["fin_to_trade_fx"] or 1.0

    sector = info.get("sector") or "Bilinmiyor"
    industry = info.get("industry") or "Bilinmiyor"
    sec_low = f"{sector} {industry}".lower()
    is_financial = any(k in sec_low for k in ("bank", "insurance", "financial services", "capital markets", "credit services"))
    is_reit = any(k in sec_low for k in ("reit", "real estate"))

    # Piyasa degerini finansal tablo para birimine hizala (orn. THYAO: TRY -> USD)
    mcap_trade = _safe(info.get("marketCap"), 0)
    mcap_fin = (mcap_trade / fx) if (mcap_trade and fx > 0) else None
    currency_adjusted = (fin_curr != trade_curr)

    # En guncel bilanco (ceyreklik varsa oncelikli, yoksa yillik)
    bal_latest = q_bal if (q_bal is not None and not q_bal.empty) else bal

    # --- Gelir & Nakit Akisi (TTM + Yillik t ve t-1) ---
    rev_ttm = _ttm_val(q_inc, inc, REVENUE_ROWS)
    gp_ttm = _ttm_val(q_inc, inc, ["Gross Profit"])
    ebit_ttm = _ttm_val(q_inc, inc, OPERATING_INCOME_ROWS)
    da_ttm = _ttm_val(q_cf, cf, DA_CF_ROWS)
    # FAVOK'u esas faaliyet kari + amortismandan kur; Yahoo'nun "EBITDA" satiri faaliyet disi
    # kazanclari da icerdigi icin sadece yedek olarak kullanilir.
    ebitda_ttm = _ebitda_from_parts(ebit_ttm, da_ttm)
    if ebitda_ttm is None:
        ebitda_ttm = _ttm_val(q_inc, inc, ["Normalized EBITDA", "EBITDA"])
    ni_ttm = _ttm_val(q_inc, inc, NET_INCOME_ROWS)
    int_exp_ttm = _ttm_val(q_inc, inc, ["Interest Expense", "Interest Expense Non Operating"])
    ocf_ttm = _ttm_val(q_cf, cf, ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"])
    capex_ttm = _ttm_val(q_cf, cf, ["Capital Expenditure", "Purchase Of PPE"])
    fcf_ttm = _ttm_val(q_cf, cf, ["Free Cash Flow"])
    if fcf_ttm is None and ocf_ttm is not None and capex_ttm is not None:
        fcf_ttm = ocf_ttm - abs(capex_ttm)

    # Yillik t (0) ve t-1 (1)
    rev_0 = _row_val(inc, REVENUE_ROWS, 0)
    rev_1 = _row_val(inc, REVENUE_ROWS, 1)
    gp_0 = _row_val(inc, ["Gross Profit"], 0)
    gp_1 = _row_val(inc, ["Gross Profit"], 1)
    ebit_0 = _row_val(inc, OPERATING_INCOME_ROWS, 0)
    ebit_1 = _row_val(inc, OPERATING_INCOME_ROWS, 1)
    ni_0 = _row_val(inc, NET_INCOME_ROWS, 0)
    ni_1 = _row_val(inc, NET_INCOME_ROWS, 1)
    tax_rate = _row_val(inc, ["Tax Rate For Calcs"], 0)
    if tax_rate is None or tax_rate < 0 or tax_rate > 0.5:
        tax_rate = 0.22

    ocf_0 = _row_val(cf, ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"], 0)
    dep_0 = _row_val(cf, ["Depreciation And Amortization", "Depreciation Amortization Depletion"], 0) or _row_val(inc, ["Reconciled Depreciation"], 0)
    dep_1 = _row_val(cf, ["Depreciation And Amortization", "Depreciation Amortization Depletion"], 1) or _row_val(inc, ["Reconciled Depreciation"], 1)
    sga_0 = _row_val(inc, ["Selling General And Administration"], 0)
    sga_1 = _row_val(inc, ["Selling General And Administration"], 1)

    # Bilanco (en guncel + yillik t ve t-1)
    assets_latest = _row_val(bal_latest, ["Total Assets"], 0)
    assets_0 = _row_val(bal, ["Total Assets"], 0)
    assets_1 = _row_val(bal, ["Total Assets"], 1)
    equity_latest = _row_val(bal_latest, ["Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest"], 0)
    liab_latest = _row_val(bal_latest, ["Total Liabilities Net Minority Interest"], 0)
    liab_0 = _row_val(bal, ["Total Liabilities Net Minority Interest"], 0)
    liab_1 = _row_val(bal, ["Total Liabilities Net Minority Interest"], 1)
    curr_assets_latest = _row_val(bal_latest, ["Current Assets"], 0)
    curr_liab_latest = _row_val(bal_latest, ["Current Liabilities"], 0)
    curr_assets_0 = _row_val(bal, ["Current Assets"], 0)
    curr_assets_1 = _row_val(bal, ["Current Assets"], 1)
    curr_liab_0 = _row_val(bal, ["Current Liabilities"], 0)
    curr_liab_1 = _row_val(bal, ["Current Liabilities"], 1)
    # Nakit = nakit + kisa vadeli yatirimlar (likit menkul kiymetler dahil)
    cash_latest = _row_val(bal_latest, ["Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents", "Cash Financial"], 0)
    total_debt_latest = _row_val(bal_latest, ["Total Debt"], 0)
    lease_latest = _row_val(bal_latest, ["Capital Lease Obligations"], 0)
    debt_assumed_zero = False
    if total_debt_latest is None and bal_latest is not None and not bal_latest.empty:
        # Yahoo, borcu olmayan sirketlerde borc satirlarini hic yazmaz
        if not any(r in bal_latest.index for r in ("Long Term Debt", "Current Debt", "Long Term Debt And Capital Lease Obligation")):
            total_debt_latest = 0.0
            debt_assumed_zero = True
    # Net borcu HER ZAMAN kendimiz hesapliyoruz. Yahoo'nun "Net Debt" satiri sadece nakdi
    # dusup kisa vadeli yatirimlari yok sayar (orn. GOOGL'u net nakitken net borclu gosterir).
    net_debt_latest = None
    if total_debt_latest is not None and cash_latest is not None:
        net_debt_latest = total_debt_latest - cash_latest

    lt_debt_0 = _row_val(bal, ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"], 0) or 0.0
    lt_debt_1 = _row_val(bal, ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"], 1)
    inv_latest = _row_val(bal_latest, ["Inventory"], 0)
    inv_0 = _row_val(bal, ["Inventory"], 0)
    inv_1 = _row_val(bal, ["Inventory"], 1)
    rec_0 = _row_val(bal, ["Accounts Receivable", "Receivables"], 0)
    rec_1 = _row_val(bal, ["Accounts Receivable", "Receivables"], 1)
    ppe_0 = _row_val(bal, ["Net PPE"], 0)
    ppe_1 = _row_val(bal, ["Net PPE"], 1)
    ret_earn_latest = _row_val(bal_latest, ["Retained Earnings"], 0) or _row_val(bal, ["Retained Earnings"], 0)
    shares_0 = _row_val(bal, ["Ordinary Shares Number", "Share Issued"], 0) or _row_val(inc, ["Diluted Average Shares", "Basic Average Shares"], 0)
    shares_1 = _row_val(bal, ["Ordinary Shares Number", "Share Issued"], 1) or _row_val(inc, ["Diluted Average Shares", "Basic Average Shares"], 1)

    # Firma Degeri (EV) — finansal tablo para biriminde tutarli hesap
    ev_fin = None
    if mcap_fin is not None:
        ev_fin = mcap_fin + (net_debt_latest or 0.0)
        if ev_fin <= 0:
            ev_fin = mcap_fin

    # --- 1. Karlilik & Sermaye Verimliligi ---
    gross_margin = _div(gp_ttm, rev_ttm)
    ebit_margin = _div(ebit_ttm, rev_ttm)
    ebitda_margin = _div(ebitda_ttm, rev_ttm)
    net_margin = _div(ni_ttm, rev_ttm)

    roe = _div(ni_ttm, equity_latest)
    if roe is None:
        roe = info.get("returnOnEquity")
    roa = _div(ni_ttm, assets_latest)

    # ROIC = NOPAT / Invested Capital
    invested_cap = _row_val(bal_latest, ["Invested Capital"], 0)
    if invested_cap is None and equity_latest is not None:
        invested_cap = equity_latest + (total_debt_latest or 0.0) - (cash_latest or 0.0)
    roic = None
    if ebit_ttm is not None and invested_cap and invested_cap > 0:
        nopat = ebit_ttm * (1.0 - tax_rate)
        roic = nopat / invested_cap

    # ROCE = EBIT / (Total Assets - Current Liabilities)
    cap_employed = (assets_latest - curr_liab_latest) if (assets_latest is not None and curr_liab_latest is not None) else None
    roce = _div(ebit_ttm, cap_employed) if (cap_employed and cap_employed > 0) else None

    # --- 2. Nakit Kalitesi ---
    ocf_to_ni = _div(ocf_ttm, ni_ttm) if (ni_ttm and ni_ttm > 0) else None
    cash_conv_ebit = _div(ocf_ttm, ebit_ttm) if (ebit_ttm and ebit_ttm > 0) else None
    fcf_margin = _div(fcf_ttm, rev_ttm)
    fcf_yield = _div(fcf_ttm, ev_fin) if (ev_fin and ev_fin > 0) else _div(fcf_ttm, mcap_fin)

    # --- 3. Borc & Likidite ---
    net_debt_to_ebitda = _div(net_debt_latest, ebitda_ttm) if (ebitda_ttm and ebitda_ttm > 0 and net_debt_latest is not None) else None
    current_ratio = _div(curr_assets_latest, curr_liab_latest)
    quick_ratio = _div((curr_assets_latest - (inv_latest or 0.0)), curr_liab_latest) if curr_assets_latest is not None else None
    interest_coverage = _div(ebit_ttm, abs(int_exp_ttm)) if (ebit_ttm is not None and int_exp_ttm and abs(int_exp_ttm) > 0) else None
    debt_to_equity = _div(total_debt_latest, equity_latest) if (equity_latest and equity_latest > 0 and total_debt_latest is not None) else None

    # --- 4. Buyume & Kirmizi Bayrak Kontrolleri ---
    # TRY raporlayan BIST sirketlerinde nominal buyume buyuk olcude enflasyonu olcer.
    # Bu yuzden buyume, donem ortalama USDTRY kuruyla dolar bazinda hesaplanir; kur verisi
    # yoksa buyume "bilinmiyor" kabul edilir (puanlamaya girmez).
    growth_in_usd = is_bist and fin_curr == "TRY"
    usdtry_df: pd.DataFrame | None = bundle.get("usdtry")

    def _annual_growth(cur: float | None, prev: float | None) -> float | None:
        if not growth_in_usd:
            return _pct_growth(cur, prev)
        return _usd_growth(cur, prev, _col_date(inc, 0), _col_date(inc, 1), usdtry_df, FX_AVG_DAYS_ANNUAL)

    rev_growth_yoy = _annual_growth(rev_0, rev_1)
    ni_growth_yoy = _annual_growth(ni_0, ni_1)
    ebit_growth_yoy = _annual_growth(ebit_0, ebit_1)
    # Stok/alacak buyumesi satis buyumesiyle KIYASLANDIGI icin ayni bazda kalmali (oran karsilastirmasi)
    inv_growth_yoy = _pct_growth(inv_0, inv_1)
    rec_growth_yoy = _pct_growth(rec_0, rec_1)
    rev_growth_nominal = _pct_growth(rev_0, rev_1)
    dilution_pct = _pct_growth(shares_0, shares_1)

    # Ceyreklik YoY buyume (son ceyrek vs 4 ceyrek once)
    q_rev_yoy = None
    q_ni_yoy = None
    if q_inc is not None and not q_inc.empty and q_inc.shape[1] >= 5:
        q_r0, q_r4 = _row_val(q_inc, REVENUE_ROWS, 0), _row_val(q_inc, REVENUE_ROWS, 4)
        q_n0, q_n4 = _row_val(q_inc, ["Net Income"], 0), _row_val(q_inc, ["Net Income"], 4)
        if growth_in_usd:
            d0, d4 = _col_date(q_inc, 0), _col_date(q_inc, 4)
            q_rev_yoy = _usd_growth(q_r0, q_r4, d0, d4, usdtry_df, FX_AVG_DAYS_QUARTER)
            q_ni_yoy = _usd_growth(q_n0, q_n4, d0, d4, usdtry_df, FX_AVG_DAYS_QUARTER)
        else:
            q_rev_yoy = _pct_growth(q_r0, q_r4)
            q_ni_yoy = _pct_growth(q_n0, q_n4)

    # --- 5. Degerleme Carpanlari (Para Birimi Tutarli!) ---
    pe = _div(mcap_fin, ni_ttm) if (ni_ttm and ni_ttm > 0) else None
    if pe is None and not currency_adjusted:
        pe = info.get("trailingPE")
    forward_pe = info.get("forwardPE") if not currency_adjusted else None
    pb = _div(mcap_fin, equity_latest) if (equity_latest and equity_latest > 0) else None
    if pb is None and not currency_adjusted:
        pb = info.get("priceToBook")
    ev_ebitda = _div(ev_fin, ebitda_ttm) if (ev_fin and ebitda_ttm and ebitda_ttm > 0) else None
    if ev_ebitda is None and not currency_adjusted:
        ev_ebitda = info.get("enterpriseToEbitda")
    ev_sales = _div(ev_fin, rev_ttm) if (ev_fin and rev_ttm and rev_ttm > 0) else None
    graham_product = (pe * pb) if (pe and pb and pe > 0 and pb > 0) else None

    peg = info.get("trailingPegRatio") or info.get("pegRatio")
    if peg is None and pe and ni_growth_yoy and ni_growth_yoy > 5:
        peg = pe / ni_growth_yoy

    # Joel Greenblatt Magic Formula
    ey_greenblatt = _div(ebit_ttm, ev_fin) if (ev_fin and ev_fin > 0) else None
    nwc = (curr_assets_latest - curr_liab_latest) if (curr_assets_latest is not None and curr_liab_latest is not None) else None
    ppe_latest = _row_val(bal_latest, ["Net PPE"], 0) or ppe_0
    roc_greenblatt = None
    if ebit_ttm is not None and nwc is not None and ppe_latest is not None:
        denom = max(nwc, 0.0) + max(ppe_latest, 0.0)
        if denom > 0:
            roc_greenblatt = ebit_ttm / denom

    # --- 6. Piotroski F-Score (0 - 9) ---
    roa_0 = _div(ni_0, assets_0)
    roa_1 = _div(ni_1, assets_1)
    cfo_roa_0 = _div(ocf_0, assets_0)
    lev_0 = _div(lt_debt_0, assets_0)
    lev_1 = _div(lt_debt_1, assets_1) if lt_debt_1 is not None else None
    cr_0 = _div(curr_assets_0, curr_liab_0)
    cr_1 = _div(curr_assets_1, curr_liab_1)
    gm_0 = _div(gp_0, rev_0)
    gm_1 = _div(gp_1, rev_1)
    at_0 = _div(rev_0, assets_0)
    at_1 = _div(rev_1, assets_1)

    piotroski_items = [
        {"name": "Pozitif Aktif Kârlılığı (ROA > 0)", "passed": bool(roa_0 is not None and roa_0 > 0), "available": roa_0 is not None},
        {"name": "Pozitif Faaliyet Nakit Akışı (OCF > 0)", "passed": bool(ocf_0 is not None and ocf_0 > 0), "available": ocf_0 is not None},
        {"name": "ROA Artışı (ROA t > t-1)", "passed": bool(roa_0 is not None and roa_1 is not None and roa_0 > roa_1), "available": roa_0 is not None and roa_1 is not None},
        {"name": "Nakit Kalitesi (OCF > Net Kâr)", "passed": bool(cfo_roa_0 is not None and roa_0 is not None and cfo_roa_0 > roa_0), "available": cfo_roa_0 is not None and roa_0 is not None},
        {"name": "Uzun Vadeli Borç/Varlık Azalmış", "passed": bool(lev_0 is not None and lev_1 is not None and lev_0 <= lev_1), "available": lev_0 is not None and lev_1 is not None},
        {"name": "Cari Oran İyileşmiş", "passed": bool(cr_0 is not None and cr_1 is not None and cr_0 > cr_1), "available": cr_0 is not None and cr_1 is not None},
        {"name": "Hisse Seyreltmesi Yok (Pay Artışı ≤ %2)", "passed": bool(shares_0 is not None and shares_1 is not None and shares_0 <= shares_1 * 1.02), "available": shares_0 is not None and shares_1 is not None},
        {"name": "Brüt Kâr Marjı Artmış", "passed": bool(gm_0 is not None and gm_1 is not None and gm_0 > gm_1), "available": gm_0 is not None and gm_1 is not None},
        {"name": "Varlık Devir Hızı Artmış", "passed": bool(at_0 is not None and at_1 is not None and at_0 > at_1), "available": at_0 is not None and at_1 is not None},
    ]
    piotroski_avail = sum(1 for x in piotroski_items if x["available"])
    piotroski_score = sum(1 for x in piotroski_items if x["passed"]) if piotroski_avail > 0 else None

    # --- 7. Altman Z-Score (Finans disi sirketler icin) ---
    altman = {"score": None, "zone": "Finans/GYO dışı uygulanır" if (is_financial or is_reit) else "Yetersiz Veri", "applicable": not (is_financial or is_reit)}
    if not is_financial and not is_reit and assets_latest and assets_latest > 0 and liab_latest and liab_latest > 0:
        x1 = _div((curr_assets_latest - curr_liab_latest) if (curr_assets_latest is not None and curr_liab_latest is not None) else None, assets_latest)
        x2 = _div(ret_earn_latest, assets_latest)
        x3 = _div(ebit_ttm, assets_latest)
        x4 = _div(mcap_fin, liab_latest)
        x5 = _div(rev_ttm, assets_latest)
        if None not in (x1, x2, x3, x4, x5):
            z = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5
            z_round = _safe(z, 2)
            if z_round is not None:
                zone = "Güvenli Bölge (> 2.99)" if z_round > 2.99 else ("Gri Bölge (1.81 – 2.99)" if z_round >= 1.81 else "Finansal Sıkıntı Riski (< 1.81)")
                altman = {"score": z_round, "zone": zone, "applicable": True}

    # --- 8. Beneish M-Score (Finans disi ve 2 yil verili) ---
    beneish = {"score": None, "status": "Finans dışı uygulanır" if is_financial else "Yetersiz Veri", "applicable": not is_financial,
               "real_components": 0, "high_growth": False}
    if not is_financial and all(v is not None and v > 0 for v in (rev_0, rev_1, assets_0, assets_1)):
        # Her bilesen icin (deger, gercek_veri_mi). Eksik bilesen 1.0 (notr) kabul edilir
        # ama gercek bilesen sayisi yeterli degilse skor HIC hesaplanmaz.
        def _comp(val: float | None) -> tuple[float, bool]:
            return (val, True) if val is not None else (1.0, False)

        dsri = _comp(_div(_div(rec_0, rev_0), _div(rec_1, rev_1)) if (rec_0 is not None and rec_1 is not None and rec_1 > 0) else None)
        gmi = _comp(_div(gm_1, gm_0) if (gm_0 and gm_1 and gm_0 > 0) else None)
        aqi_num = 1.0 - _div((curr_assets_0 or 0.0) + (ppe_0 or 0.0), assets_0) if (curr_assets_0 is not None and ppe_0 is not None) else None
        aqi_den = 1.0 - _div((curr_assets_1 or 0.0) + (ppe_1 or 0.0), assets_1) if (curr_assets_1 is not None and ppe_1 is not None) else None
        aqi = _comp(_div(aqi_num, aqi_den) if (aqi_num is not None and aqi_den and aqi_den > 0) else None)
        sgi = _comp(_div(rev_0, rev_1))
        dep_rate_0 = _div(dep_0, (ppe_0 or 0.0) + (dep_0 or 0.0)) if (dep_0 and ppe_0) else None
        dep_rate_1 = _div(dep_1, (ppe_1 or 0.0) + (dep_1 or 0.0)) if (dep_1 and ppe_1) else None
        depi = _comp(_div(dep_rate_1, dep_rate_0) if (dep_rate_0 and dep_rate_1 and dep_rate_0 > 0) else None)
        sgai = _comp(_div(_div(sga_0, rev_0), _div(sga_1, rev_1)) if (sga_0 and sga_1 and sga_1 > 0) else None)
        lvgi = _comp(_div(_div(liab_0, assets_0), _div(liab_1, assets_1)) if (liab_0 and liab_1 and liab_1 > 0) else None)
        tata_raw = _div((ni_0 - ocf_0), assets_0) if (ni_0 is not None and ocf_0 is not None) else None
        tata = (tata_raw, True) if tata_raw is not None else (0.0, False)

        comps = (dsri, gmi, aqi, sgi, depi, sgai, lvgi, tata)
        real_count = sum(1 for _, real in comps if real)
        beneish["real_components"] = real_count
        high_growth = sgi[1] and sgi[0] >= 1.5
        beneish["high_growth"] = bool(high_growth)

        # TATA (tahakkuk) ve DSRI (alacak) modelin en ayirt edici iki bileseni; ikisi de gercek olmali
        if real_count >= BENEISH_MIN_REAL_COMPONENTS and tata[1] and dsri[1]:
            m_val = (-4.84 + 0.920 * dsri[0] + 0.528 * gmi[0] + 0.404 * aqi[0] + 0.892 * sgi[0]
                     + 0.115 * depi[0] - 0.172 * sgai[0] + 4.679 * tata[0] - 0.327 * lvgi[0])
            m_round = _safe(m_val, 2)
            if m_round is not None:
                if m_round < -1.78:
                    status = "Manipülasyon Riski Düşük (< -1.78)"
                elif high_growth:
                    status = "Eşik Aşıldı — Yüksek Büyüme Etkisi (> -1.78, satış büyümesi skoru tek başına yükseltir)"
                else:
                    status = "Agresif Muhasebe Uyarısı (> -1.78)"
                beneish.update({"score": m_round, "status": status, "tata": _safe(tata[0], 3)})
        else:
            beneish["status"] = f"Yetersiz Veri ({real_count}/8 bileşen gerçek veriye dayanıyor; en az {BENEISH_MIN_REAL_COMPONENTS} + TATA + DSRI gerekli)"

    # --- 9. Cok Yilli Finansal Ozet Tablosu (Son 4 Yil) ---
    history_table = []
    if inc is not None and not inc.empty:
        cols = min(4, inc.shape[1])
        for i in range(cols):
            dt = inc.columns[i]
            yr = dt.strftime("%Y") if hasattr(dt, "strftime") else str(dt)[:4]
            # Nakit akis ve bilanco tablolarinda ayni donemin sutununu TARIHE gore bul
            # (sutun sirasi tablolar arasinda farkli olabilir)
            cf_i = _col_index_for(cf, dt)
            bal_i = _col_index_for(bal, dt)
            r_i = _row_val(inc, REVENUE_ROWS, i)
            ebit_i = _row_val(inc, OPERATING_INCOME_ROWS, i)
            da_i = _row_val(cf, DA_CF_ROWS, cf_i) if cf_i is not None else None
            ebitda_i = _ebitda_from_parts(ebit_i, da_i)
            if ebitda_i is None:
                ebitda_i = _row_val(inc, ["Normalized EBITDA", "EBITDA"], i)
            ni_i = _row_val(inc, ["Net Income", "Net Income Common Stockholders"], i)
            ocf_i = _row_val(cf, ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"], cf_i) if cf_i is not None else None
            capex_i = _row_val(cf, ["Capital Expenditure", "Purchase Of PPE"], cf_i) if cf_i is not None else None
            fcf_i = _row_val(cf, ["Free Cash Flow"], cf_i) if cf_i is not None else None
            if fcf_i is None and ocf_i is not None and capex_i is not None:
                fcf_i = ocf_i - abs(capex_i)
            nd_i = None
            if bal_i is not None:
                td_i = _row_val(bal, ["Total Debt"], bal_i)
                cash_i = _row_val(bal, ["Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents"], bal_i)
                if td_i is not None and cash_i is not None:
                    nd_i = td_i - cash_i
            history_table.append(
                {
                    "year": yr,
                    "revenue": _safe(r_i, 0),
                    "ebitda": _safe(ebitda_i, 0),
                    "ebit": _safe(ebit_i, 0),
                    "net_income": _safe(ni_i, 0),
                    "ocf": _safe(ocf_i, 0),
                    "fcf": _safe(fcf_i, 0),
                    "net_debt": _safe(nd_i, 0),
                }
            )

    # --- 10. Seffaf Bilanco Puani (0 - 100) ---
    # Her kalem (etiket, puan, agirlik) olarak eklenir. Puan None ise kalem "eksik veri"
    # sayilir: puan kazandirmaz, kaybettirmez; skor mevcut kalemlerin agirligina gore olceklenir.
    card = _ScoreCard()
    loss_making = ni_ttm is not None and ni_ttm <= 0

    def _tier(val: float | None, tiers: list[tuple[float, float]], floor: float = 0.0) -> float | None:
        """tiers: [(esik, puan), ...] buyukten kucuge; val >= esik ise puan."""
        if val is None:
            return None
        for threshold, pts in tiers:
            if val >= threshold:
                return pts
        return floor

    def _tier_low(val: float | None, tiers: list[tuple[float, float]], floor: float = 0.0) -> float | None:
        """Dusuk olan iyi (F/K, FD/FAVOK gibi): val <= esik ise puan."""
        if val is None:
            return None
        for threshold, pts in tiers:
            if val <= threshold:
                return pts
        return floor

    if is_financial:
        # Banka / Sigorta / Finans ozel puanlama (Borc/Cari Oran cezasi yok!)
        card.add("ROE", _tier(roe, [(0.25, 30), (0.18, 24), (0.12, 16), (1e-9, 8)]), 30)
        if pb is not None:
            pb_pts = 15 if (pb <= 1.2 and roe is not None and roe >= 0.15) else _tier_low(pb, [(2.0, 11), (3.5, 6)])
        else:
            pb_pts = None
        card.add("PD/DD", pb_pts, 15)
        if pe is not None and pe > 0:
            pe_pts = _tier_low(pe, [(8, 10), (15, 7), (22, 3)])
        else:
            pe_pts = 0.0 if loss_making else None
        card.add("F/K", pe_pts, 10)
        card.add("Ciro büyümesi", _tier(rev_growth_yoy, [(20, 12), (5, 8), (1e-9, 3)]), 12)
        card.add("Net kâr büyümesi", _tier(ni_growth_yoy, [(20, 13), (5, 8), (1e-9, 3)]), 13)
        card.add("Net kâr marjı", _tier(net_margin, [(0.15, 10), (0.05, 5)]), 10)
        card.add("Piotroski", (piotroski_score / piotroski_avail) * 10 if (piotroski_score is not None and piotroski_avail > 0) else None, 10)
    else:
        # Standart Sirketler (Sanayi / Teknoloji / Perakende / Enerji)
        # a) Karlilik & Sermaye Verimliligi (25)
        eff = roic if roic is not None else (roce if roce is not None else roe)
        card.add("Sermaye getirisi (ROIC/ROCE/ROE)", _tier(eff, [(0.20, 15), (0.14, 12), (0.09, 8), (1e-9, 4)]), 15)
        if ebit_margin is not None:
            margin_pts = _tier(ebit_margin, [(0.18, 10), (0.10, 7), (0.04, 4)])
        elif gross_margin is not None:
            margin_pts = 6.0 if gross_margin >= 0.30 else 0.0
        else:
            margin_pts = None
        card.add("Faaliyet marjı", margin_pts, 10)

        # b) Nakit Kalitesi (20)
        card.add("Pozitif faaliyet nakit akışı", (7.0 if ocf_ttm > 0 else 0.0) if ocf_ttm is not None else None, 7)
        if ocf_to_ni is not None:
            conv_pts = _tier(ocf_to_ni, [(0.9, 6), (0.65, 3)])
        else:
            conv_pts = 0.0 if loss_making else None
        card.add("Nakit dönüşümü (OCF/Net kâr)", conv_pts, 6)
        card.add("Pozitif serbest nakit akışı", (7.0 if fcf_ttm > 0 else 0.0) if fcf_ttm is not None else None, 7)

        # c) Bilanco Saglamligi (20)
        if net_debt_latest is not None and net_debt_latest < 0:
            nd_pts = 10.0  # Net nakit
        elif net_debt_to_ebitda is not None:
            nd_pts = _tier_low(net_debt_to_ebitda, [(1.5, 8), (2.8, 5), (4.0, 2)])
        elif net_debt_latest is not None and ebitda_ttm is not None and ebitda_ttm <= 0:
            nd_pts = 0.0  # Borclu ve FAVOK negatif
        else:
            nd_pts = None
        card.add("Net borç / FAVÖK", nd_pts, 10)
        card.add("Cari oran", _tier(current_ratio, [(1.5, 5), (1.0, 3)], floor=1.0), 5)

        debt_free = total_debt_latest is not None and total_debt_latest == 0
        if interest_coverage is not None:
            ic_pts = _tier(interest_coverage, [(6, 5), (3, 3), (1.5, 1)])
        elif debt_free or (net_debt_latest is not None and net_debt_latest < 0 and not int_exp_ttm):
            ic_pts = 5.0  # Borcsuz / net nakit: faiz riski yok, tam puan
        elif ebit_ttm is not None and ebit_ttm <= 0 and int_exp_ttm:
            ic_pts = 0.0
        else:
            ic_pts = None
        card.add("Faiz karşılama", ic_pts, 5)

        # d) Bilimsel Skorlar & Buyume (20)
        card.add("Piotroski", (piotroski_score / piotroski_avail) * 10 if (piotroski_score is not None and piotroski_avail >= 5) else None, 10)
        card.add("Ciro büyümesi", _tier(rev_growth_yoy, [(15, 5), (3, 3), (1e-9, 1)]), 5)
        profit_growth = ebit_growth_yoy if ebit_growth_yoy is not None else ni_growth_yoy
        card.add("Kâr büyümesi", _tier(profit_growth, [(15, 5), (3, 3), (1e-9, 1)]), 5)

        # e) Degerleme (15) — mevcut carpanlarin ortalamasi
        val_scores: list[float] = []
        if ev_ebitda is not None and ev_ebitda > 0:
            val_scores.append(_tier_low(ev_ebitda, [(10, 15), (16, 11), (24, 7)], floor=3))
        if fcf_yield is not None:
            val_scores.append(_tier(fcf_yield, [(0.06, 15), (0.035, 11), (1e-9, 6)], floor=1))
        if pe is not None and pe > 0:
            val_scores.append(_tier_low(pe, [(15, 15), (24, 11), (35, 7)], floor=3))
        if val_scores:
            val_pts = sum(val_scores) / len(val_scores)
        else:
            val_pts = 0.0 if loss_making else None
        card.add("Değerleme", val_pts, 15)

    # Kirmizi bayrak kesintisi: sadece Altman. Beneish M-Score yuksek buyumede yanlis alarm
    # verebildigi icin puandan dusulmez, yalnizca uyari olarak gosterilir.
    penalty = 0.0
    if not is_financial and altman["applicable"] and altman["score"] is not None and altman["score"] < 1.81:
        penalty += 6.0

    scored = card.score(penalty)
    fund_score = scored if scored is not None else 0
    data_coverage_pct = int(round(card.coverage * 100))
    missing_inputs = card.missing

    # Kirmizi & Yesil Bayraklar
    flags_good = []
    flags_warn = []
    notes = []

    if is_bist:
        notes.append("TMS 29 (Enflasyon Muhasebesi) nedeniyle BIST hisselerinde Net Kâr/F/K yerine FAVÖK, Esas Faaliyet Kârı ve Nakit Akışı kalemleri önceliklendirilmelidir.")
    if growth_in_usd:
        if rev_growth_yoy is None and rev_growth_nominal is not None:
            notes.append("Büyüme oranları enflasyon etkisini dışlamak için dolar bazında hesaplanır; dönem kur verisi bulunamadığından büyüme puanlamaya dahil edilmedi.")
        else:
            notes.append("Büyüme oranları enflasyon etkisini dışlamak için dönem ortalama USD/TRY kuruyla dolar bazında hesaplandı (nominal TL büyümesi değildir).")
    if debt_assumed_zero:
        notes.append("Bilançoda finansal borç kalemi bulunmadığından şirket borçsuz kabul edildi.")
    if lease_latest:
        notes.append("Toplam borç ve net borç, kira (leasing) yükümlülüklerini de içerir.")
    if data_coverage_pct < 100:
        missing_txt = ", ".join(missing_inputs[:8]) + ("…" if len(missing_inputs) > 8 else "")
        notes.append(f"Bilanço puanı verinin %{data_coverage_pct}'i ile hesaplandı; eksik kalemler puana dahil edilmedi: {missing_txt}.")
    if data_coverage_pct < 50:
        flags_warn.append(f"Düşük veri kapsamı (%{data_coverage_pct}): Bilanço puanı güvenilir değil.")
    if currency_adjusted:
        notes.append(f"Şirket finansallarını {fin_curr} cinsinden raporluyor; piyasa değeri ve çarpanlar güncel kur ({_safe(fx, 2)}) ile {fin_curr} bazında hizalanarak hesaplandı.")
    if is_financial:
        notes.append("Finans/Banka sektörü algılandı: Cari Oran, Net Borç/FAVÖK ve Altman Z-Score yerine Özsermaye Kârlılığı (ROE) ve PD/DD odaklı puanlama uygulandı.")
    elif is_reit:
        notes.append("Gayrimenkul / GYO sektörü algılandı: Yeniden değerleme kârı yerine kira nakit akışı ve NAD iskontosu ek olarak incelenmelidir.")

    if roic is not None and roic >= 0.15:
        flags_good.append(f"Yüksek sermaye getirisi: ROIC %{_safe(roic * 100, 1)} (kaliteli bileşik büyüme işareti).")
    if ocf_to_ni is not None and ocf_to_ni >= 0.9 and ocf_ttm and ocf_ttm > 0:
        flags_good.append(f"Güçlü nakit dönüşümü: Faaliyet Nakit Akışı / Net Kâr = {_safe(ocf_to_ni, 2)}x.")
    if not is_financial and net_debt_latest is not None and net_debt_latest < 0:
        flags_good.append("Şirket Net Nakit pozisyonunda (nakit ve benzerleri toplam borçtan fazla).")
    elif not is_financial and net_debt_to_ebitda is not None and net_debt_to_ebitda > 3.5:
        flags_warn.append(f"Yüksek borçluluk: Net Borç / FAVÖK = {_safe(net_debt_to_ebitda, 2)}x (> 3.5x riskli).")
    if piotroski_score is not None and piotroski_score >= 7:
        flags_good.append(f"Piotroski F-Score çok güçlü ({piotroski_score}/{piotroski_avail}).")
    elif piotroski_score is not None and piotroski_avail >= 7 and piotroski_score <= 3:
        flags_warn.append(f"Piotroski F-Score zayıf ({piotroski_score}/{piotroski_avail}) — temel momentum bozulmuş.")
    if not is_financial and ni_ttm and ni_ttm > 0 and ocf_ttm is not None and ocf_ttm < 0:
        flags_warn.append("Kâr/Nakit Uyumsuzluğu: Net Kâr pozitifken Faaliyet Nakit Akışı negatif (tahakkuk uyarısı).")
    # Stok/alacak, satis buyumesiyle AYNI (nominal) bazda karsilastirilir
    if not is_financial and inv_growth_yoy is not None and rev_growth_nominal is not None and (inv_growth_yoy - rev_growth_nominal) > 25:
        flags_warn.append(f"Peter Lynch Stok Uyarısı: Stok artışı (+{_safe(inv_growth_yoy, 1)}%) satış artışından (+{_safe(rev_growth_nominal, 1)}%) belirgin hızlı.")
    if not is_financial and rec_growth_yoy is not None and rev_growth_nominal is not None and (rec_growth_yoy - rev_growth_nominal) > 25:
        flags_warn.append(f"Alacak Uyarısı: Ticari alacak artışı (+{_safe(rec_growth_yoy, 1)}%) satış artışından belirgin hızlı.")
    if dilution_pct is not None and dilution_pct > 10:
        flags_warn.append(f"Hisse Seyreltmesi: Pay sayısı yıllık +{_safe(dilution_pct, 1)}% artmış.")
    if altman["applicable"] and altman["score"] is not None and altman["score"] < 1.81:
        flags_warn.append(f"Altman Z-Score ({altman['score']}) finansal sıkıntı bölgesinde (< 1.81).")
    if beneish["applicable"] and beneish["score"] is not None and beneish["score"] > -1.78:
        if beneish["high_growth"]:
            flags_warn.append(f"Beneish M-Score ({beneish['score']}) eşiğin üzerinde; ancak yüksek satış büyümesi skoru tek başına yükseltir — alacak ve tahakkuk kalemlerini ayrıca kontrol edin (puandan düşülmedi).")
        else:
            flags_warn.append(f"Beneish M-Score ({beneish['score']}) agresif muhasebe eşiğinin (> -1.78) üzerinde (bilgi amaçlı, puandan düşülmedi).")

    # Bilanço kontrol listesi
    checklist = [
        {
            "label": "Sermaye Verimliliği (ROIC / ROE)",
            "status": "pass" if ((roic or roe or 0) >= 0.15) else ("warn" if ((roic or roe or 0) >= 0.08) else "fail"),
            "value": f"ROIC: {_safe(roic * 100, 1)}% | ROE: {_safe(roe * 100, 1)}%" if (roic is not None and roe is not None) else (f"ROE: {_safe(roe * 100, 1)}%" if roe is not None else "Veri yok"),
        },
        {
            "label": "Nakit Kalitesi (OCF / Net Kâr)",
            "status": "pass" if (ocf_to_ni is not None and ocf_to_ni >= 0.85) else ("warn" if (ocf_ttm is not None and ocf_ttm > 0) else "fail"),
            "value": f"{_safe(ocf_to_ni, 2)}x" if ocf_to_ni is not None else ("Pozitif OCF" if (ocf_ttm and ocf_ttm > 0) else "Negatif / Veri yok"),
        },
        {
            "label": "Serbest Nakit Akışı (FCF) & Getirisi",
            "status": "pass" if (fcf_ttm is not None and fcf_ttm > 0 and (fcf_yield or 0) >= 0.03) else ("warn" if (fcf_ttm is not None and fcf_ttm > 0) else "fail"),
            "value": f"FCF Getirisi: {_safe(fcf_yield * 100, 2)}%" if fcf_yield is not None else ("Negatif FCF" if (fcf_ttm is not None and fcf_ttm < 0) else "Veri yok"),
        },
        {
            "label": "Borçluluk (Net Borç / FAVÖK)",
            "status": "warn" if is_financial else ("pass" if (net_debt_to_ebitda is not None and net_debt_to_ebitda <= 2.0) or (net_debt_latest is not None and net_debt_latest < 0) else ("warn" if (net_debt_to_ebitda is not None and net_debt_to_ebitda <= 3.5) else "fail")),
            "value": "Finans sektöründe uygulanmaz" if is_financial else ("Net Nakit" if (net_debt_latest is not None and net_debt_latest < 0) else (f"{_safe(net_debt_to_ebitda, 2)}x" if net_debt_to_ebitda is not None else "Veri yok")),
        },
        {
            "label": "Kısa Vadeli Likidite (Cari / Asit-Test)",
            "status": "warn" if is_financial else ("pass" if (current_ratio is not None and current_ratio >= 1.3) else ("warn" if (current_ratio is not None and current_ratio >= 1.0) else "fail")),
            "value": "Finans sektöründe uygulanmaz" if is_financial else (f"Cari: {_safe(current_ratio, 2)} | Asit-Test: {_safe(quick_ratio, 2)}" if current_ratio is not None else "Veri yok"),
        },
        {
            "label": "Piotroski F-Score (Finansal Sağlık)",
            "status": "pass" if (piotroski_score is not None and piotroski_score >= 7) else ("warn" if (piotroski_score is not None and piotroski_score >= 5) else "fail"),
            "value": f"{piotroski_score} / {piotroski_avail}" if piotroski_score is not None else "Veri yok",
        },
        {
            "label": "Altman Z-Score & Beneish M-Score",
            "status": "warn" if (is_financial or is_reit) else ("pass" if ((altman["score"] or 0) > 2.99 and (beneish["score"] or -9) < -1.78) else ("fail" if ((altman["score"] is not None and altman["score"] < 1.81) or (beneish["score"] is not None and beneish["score"] > -1.78)) else "warn")),
            "value": f"Z: {altman['score']} | M: {beneish['score']}" if (altman["applicable"] and altman["score"] is not None) else altman["zone"],
        },
        {
            "label": "Değerleme (FD/FAVÖK, F/K, PEG)",
            "status": "pass" if ((ev_ebitda and 0 < ev_ebitda <= 14) or (pe and 0 < pe <= 18)) else ("warn" if ((ev_ebitda and ev_ebitda <= 26) or (pe and pe <= 32)) else "fail"),
            "value": f"F/K: {_safe(pe, 1) if pe else '—'} | FD/FAVÖK: {_safe(ev_ebitda, 1) if ev_ebitda else '—'} | PD/DD: {_safe(pb, 2) if pb else '—'}",
        },
    ]

    return {
        "score": fund_score,
        "data_coverage_pct": data_coverage_pct,
        "missing_inputs": missing_inputs,
        "growth_basis": "USD" if growth_in_usd else "nominal",
        "sector": sector,
        "industry": industry,
        "is_financial": is_financial,
        "is_reit": is_reit,
        "financial_currency": fin_curr,
        "currency_adjusted": currency_adjusted,
        "market_cap_trade": mcap_trade,
        "market_cap_fin": _safe(mcap_fin, 0),
        "enterprise_value_fin": _safe(ev_fin, 0),
        "profitability": {
            "gross_margin_pct": _safe(gross_margin * 100, 2) if gross_margin is not None else None,
            "ebit_margin_pct": _safe(ebit_margin * 100, 2) if ebit_margin is not None else None,
            "ebitda_margin_pct": _safe(ebitda_margin * 100, 2) if ebitda_margin is not None else None,
            "net_margin_pct": _safe(net_margin * 100, 2) if net_margin is not None else None,
            "roe_pct": _safe(roe * 100, 2) if roe is not None else None,
            "roa_pct": _safe(roa * 100, 2) if roa is not None else None,
            "roic_pct": _safe(roic * 100, 2) if roic is not None else None,
            "roce_pct": _safe(roce * 100, 2) if roce is not None else None,
        },
        "cash_quality": {
            "ocf_ttm": _safe(ocf_ttm, 0),
            "fcf_ttm": _safe(fcf_ttm, 0),
            "ocf_to_ni": _safe(ocf_to_ni, 2),
            "cash_conv_ebit_pct": _safe(cash_conv_ebit * 100, 1) if cash_conv_ebit is not None else None,
            "fcf_margin_pct": _safe(fcf_margin * 100, 2) if fcf_margin is not None else None,
            "fcf_yield_pct": _safe(fcf_yield * 100, 2) if fcf_yield is not None else None,
        },
        "balance_health": {
            "net_debt": _safe(net_debt_latest, 0),
            "total_debt": _safe(total_debt_latest, 0),
            "lease_liabilities": _safe(lease_latest, 0),
            "cash": _safe(cash_latest, 0),
            "net_debt_to_ebitda": _safe(net_debt_to_ebitda, 2),
            "current_ratio": _safe(current_ratio, 2),
            "quick_ratio": _safe(quick_ratio, 2),
            "interest_coverage": _safe(interest_coverage, 2),
            "debt_to_equity": _safe(debt_to_equity, 2),
        },
        "growth": {
            "rev_yoy_pct": _safe(rev_growth_yoy, 2),
            "ebit_yoy_pct": _safe(ebit_growth_yoy, 2),
            "ni_yoy_pct": _safe(ni_growth_yoy, 2),
            "q_rev_yoy_pct": _safe(q_rev_yoy, 2),
            "q_ni_yoy_pct": _safe(q_ni_yoy, 2),
            "inv_yoy_pct": _safe(inv_growth_yoy, 2),
            "rec_yoy_pct": _safe(rec_growth_yoy, 2),
            "dilution_pct": _safe(dilution_pct, 2),
        },
        "valuation": {
            "pe": _safe(pe, 2),
            "forward_pe": _safe(forward_pe, 2),
            "pb": _safe(pb, 2),
            "ev_ebitda": _safe(ev_ebitda, 2),
            "ev_sales": _safe(ev_sales, 2),
            "peg": _safe(peg, 2),
            "graham_product": _safe(graham_product, 2),
            "magic_ey_pct": _safe(ey_greenblatt * 100, 2) if ey_greenblatt is not None else None,
            "magic_roc_pct": _safe(roc_greenblatt * 100, 2) if roc_greenblatt is not None else None,
        },
        "scores": {
            "piotroski": {
                "score": piotroski_score,
                "available": piotroski_avail,
                "items": piotroski_items,
            },
            "altman": altman,
            "beneish": beneish,
        },
        "history_table": history_table,
        "checklist": checklist,
        "flags_good": flags_good,
        "flags_warn": flags_warn,
        "notes": notes,
    }
