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


def analyze_fundamental(bundle: dict[str, Any]) -> dict[str, Any]:
    info: dict[str, Any] = bundle["info"]
    inc: pd.DataFrame = bundle["income_stmt"]
    q_inc: pd.DataFrame = bundle["quarterly_income"]
    bal: pd.DataFrame = bundle["balance_sheet"]
    q_bal: pd.DataFrame = bundle["quarterly_balance"]
    cf: pd.DataFrame = bundle["cashflow"]
    q_cf: pd.DataFrame = bundle["quarterly_cashflow"]

    is_bist: bool = bundle["is_bist"]
    trade_curr: str = bundle["currency"]
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
    rev_ttm = _ttm_val(q_inc, inc, ["Total Revenue", "Operating Revenue"])
    gp_ttm = _ttm_val(q_inc, inc, ["Gross Profit"])
    ebit_ttm = _ttm_val(q_inc, inc, ["EBIT", "Operating Income", "Total Operating Income As Reported"])
    ebitda_ttm = _ttm_val(q_inc, inc, ["EBITDA", "Normalized EBITDA"])
    ni_ttm = _ttm_val(q_inc, inc, ["Net Income", "Net Income Common Stockholders", "Net Income From Continuing Operation Net Minority Interest"])
    int_exp_ttm = _ttm_val(q_inc, inc, ["Interest Expense", "Interest Expense Non Operating"])
    ocf_ttm = _ttm_val(q_cf, cf, ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"])
    capex_ttm = _ttm_val(q_cf, cf, ["Capital Expenditure", "Purchase Of PPE"])
    fcf_ttm = _ttm_val(q_cf, cf, ["Free Cash Flow"])
    if fcf_ttm is None and ocf_ttm is not None and capex_ttm is not None:
        fcf_ttm = ocf_ttm - abs(capex_ttm)

    # Yillik t (0) ve t-1 (1)
    rev_0 = _row_val(inc, ["Total Revenue", "Operating Revenue"], 0)
    rev_1 = _row_val(inc, ["Total Revenue", "Operating Revenue"], 1)
    gp_0 = _row_val(inc, ["Gross Profit"], 0)
    gp_1 = _row_val(inc, ["Gross Profit"], 1)
    ebit_0 = _row_val(inc, ["EBIT", "Operating Income", "Total Operating Income As Reported"], 0)
    ebit_1 = _row_val(inc, ["EBIT", "Operating Income", "Total Operating Income As Reported"], 1)
    ebitda_0 = _row_val(inc, ["EBITDA", "Normalized EBITDA"], 0)
    ni_0 = _row_val(inc, ["Net Income", "Net Income Common Stockholders", "Net Income From Continuing Operation Net Minority Interest"], 0)
    ni_1 = _row_val(inc, ["Net Income", "Net Income Common Stockholders", "Net Income From Continuing Operation Net Minority Interest"], 1)
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
    equity_0 = _row_val(bal, ["Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest"], 0)
    liab_latest = _row_val(bal_latest, ["Total Liabilities Net Minority Interest"], 0)
    liab_0 = _row_val(bal, ["Total Liabilities Net Minority Interest"], 0)
    liab_1 = _row_val(bal, ["Total Liabilities Net Minority Interest"], 1)
    curr_assets_latest = _row_val(bal_latest, ["Current Assets"], 0)
    curr_liab_latest = _row_val(bal_latest, ["Current Liabilities"], 0)
    curr_assets_0 = _row_val(bal, ["Current Assets"], 0)
    curr_assets_1 = _row_val(bal, ["Current Assets"], 1)
    curr_liab_0 = _row_val(bal, ["Current Liabilities"], 0)
    curr_liab_1 = _row_val(bal, ["Current Liabilities"], 1)
    cash_latest = _row_val(bal_latest, ["Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents", "Cash Financial"], 0)
    total_debt_latest = _row_val(bal_latest, ["Total Debt"], 0)
    net_debt_latest = _row_val(bal_latest, ["Net Debt"], 0)
    if net_debt_latest is None and total_debt_latest is not None and cash_latest is not None:
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
    rev_growth_yoy = _pct_growth(rev_0, rev_1)
    ni_growth_yoy = _pct_growth(ni_0, ni_1)
    ebit_growth_yoy = _pct_growth(ebit_0, ebit_1)
    inv_growth_yoy = _pct_growth(inv_0, inv_1)
    rec_growth_yoy = _pct_growth(rec_0, rec_1)
    dilution_pct = _pct_growth(shares_0, shares_1)

    # Ceyreklik YoY buyume (son ceyrek vs 4 ceyrek once)
    q_rev_yoy = None
    q_ni_yoy = None
    if q_inc is not None and not q_inc.empty and q_inc.shape[1] >= 5:
        q_rev_yoy = _pct_growth(_row_val(q_inc, ["Total Revenue", "Operating Revenue"], 0), _row_val(q_inc, ["Total Revenue", "Operating Revenue"], 4))
        q_ni_yoy = _pct_growth(_row_val(q_inc, ["Net Income"], 0), _row_val(q_inc, ["Net Income"], 4))

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
    beneish = {"score": None, "status": "Finans dışı uygulanır" if is_financial else "Yetersiz Veri", "applicable": not is_financial}
    if not is_financial and all(v is not None and v > 0 for v in (rev_0, rev_1, assets_0, assets_1)):
        dsri = _div(_div(rec_0, rev_0), _div(rec_1, rev_1)) if (rec_0 is not None and rec_1 is not None and rec_1 > 0) else 1.0
        gmi = _div(gm_1, gm_0) if (gm_0 and gm_1 and gm_0 > 0) else 1.0
        aqi_num = 1.0 - _div((curr_assets_0 or 0.0) + (ppe_0 or 0.0), assets_0) if (curr_assets_0 is not None and ppe_0 is not None) else None
        aqi_den = 1.0 - _div((curr_assets_1 or 0.0) + (ppe_1 or 0.0), assets_1) if (curr_assets_1 is not None and ppe_1 is not None) else None
        aqi = _div(aqi_num, aqi_den) if (aqi_num is not None and aqi_den and aqi_den > 0) else 1.0
        sgi = _div(rev_0, rev_1) or 1.0
        dep_rate_0 = _div(dep_0, (ppe_0 or 0.0) + (dep_0 or 0.0)) if (dep_0 and ppe_0) else None
        dep_rate_1 = _div(dep_1, (ppe_1 or 0.0) + (dep_1 or 0.0)) if (dep_1 and ppe_1) else None
        depi = _div(dep_rate_1, dep_rate_0) if (dep_rate_0 and dep_rate_1 and dep_rate_0 > 0) else 1.0
        sgai = _div(_div(sga_0, rev_0), _div(sga_1, rev_1)) if (sga_0 and sga_1 and sga_1 > 0) else 1.0
        lvgi = _div(_div(liab_0, assets_0), _div(liab_1, assets_1)) if (liab_0 and liab_1 and liab_1 > 0) else 1.0
        tata = _div((ni_0 - ocf_0), assets_0) if (ni_0 is not None and ocf_0 is not None) else 0.0

        # En az 3 gercek cekirdek oran (DSRI/GMI/TATA/SGI) mevcutsa hesapla
        m_val = -4.84 + 0.920 * dsri + 0.528 * gmi + 0.404 * aqi + 0.892 * sgi + 0.115 * depi - 0.172 * sgai + 4.679 * tata - 0.327 * lvgi
        m_round = _safe(m_val, 2)
        if m_round is not None:
            status = "Manipülasyon Riski Düşük (< -1.78)" if m_round < -1.78 else "Agresif Muhasebe Uyarısı (> -1.78)"
            beneish = {"score": m_round, "status": status, "applicable": True, "tata": _safe(tata, 3)}

    # --- 9. Cok Yilli Finansal Ozet Tablosu (Son 4 Yil) ---
    history_table = []
    if inc is not None and not inc.empty:
        cols = min(4, inc.shape[1])
        for i in range(cols):
            dt = inc.columns[i]
            yr = dt.strftime("%Y") if hasattr(dt, "strftime") else str(dt)[:4]
            r_i = _row_val(inc, ["Total Revenue", "Operating Revenue"], i)
            ebitda_i = _row_val(inc, ["EBITDA", "Normalized EBITDA"], i)
            ebit_i = _row_val(inc, ["EBIT", "Operating Income"], i)
            ni_i = _row_val(inc, ["Net Income", "Net Income Common Stockholders"], i)
            ocf_i = _row_val(cf, ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"], i) if (cf is not None and i < cf.shape[1]) else None
            capex_i = _row_val(cf, ["Capital Expenditure", "Purchase Of PPE"], i) if (cf is not None and i < cf.shape[1]) else None
            fcf_i = _row_val(cf, ["Free Cash Flow"], i) if (cf is not None and i < cf.shape[1]) else None
            if fcf_i is None and ocf_i is not None and capex_i is not None:
                fcf_i = ocf_i - abs(capex_i)
            nd_i = _row_val(bal, ["Net Debt"], i) if (bal is not None and i < bal.shape[1]) else None
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
    f_score = 0.0
    if is_financial:
        # Banka / Sigorta / Finans ozel puanlama (Borc/Cari Oran cezasi yok!)
        # a) ROE (30 puan)
        if roe is not None:
            if roe >= 0.25:
                f_score += 30
            elif roe >= 0.18:
                f_score += 24
            elif roe >= 0.12:
                f_score += 16
            elif roe > 0:
                f_score += 8
        # b) Degerleme: PD/DD vs ROE ve F/K (25 puan)
        if pb is not None:
            if pb <= 1.2 and (roe is not None and roe >= 0.15):
                f_score += 15
            elif pb <= 2.0:
                f_score += 11
            elif pb <= 3.5:
                f_score += 6
        if pe is not None and pe > 0:
            if pe <= 8:
                f_score += 10
            elif pe <= 15:
                f_score += 7
            elif pe <= 22:
                f_score += 3
        # c) Buyume (25 puan)
        if rev_growth_yoy is not None:
            f_score += 12 if rev_growth_yoy >= 20 else (8 if rev_growth_yoy >= 5 else (3 if rev_growth_yoy > 0 else 0))
        if ni_growth_yoy is not None:
            f_score += 13 if ni_growth_yoy >= 20 else (8 if ni_growth_yoy >= 5 else (3 if ni_growth_yoy > 0 else 0))
        # d) Kârlilik istikrari & Piotroski kismi (20 puan)
        if net_margin is not None and net_margin > 0.15:
            f_score += 10
        elif net_margin is not None and net_margin > 0.05:
            f_score += 5
        if piotroski_score is not None and piotroski_avail > 0:
            f_score += (piotroski_score / piotroski_avail) * 10
        else:
            f_score += 5
    else:
        # Standart Sirketler (Sanayi / Teknoloji / Perakende / Enerji)
        # a) Karlilik & Sermaye Verimliligi (25 puan)
        eff = roic if roic is not None else (roce if roce is not None else roe)
        if eff is not None:
            if eff >= 0.20:
                f_score += 15
            elif eff >= 0.14:
                f_score += 12
            elif eff >= 0.09:
                f_score += 8
            elif eff > 0:
                f_score += 4
        else:
            f_score += 6
        if ebit_margin is not None:
            if ebit_margin >= 0.18:
                f_score += 10
            elif ebit_margin >= 0.10:
                f_score += 7
            elif ebit_margin >= 0.04:
                f_score += 4
        elif gross_margin is not None and gross_margin >= 0.30:
            f_score += 6

        # b) Nakit Kalitesi (20 puan)
        if ocf_ttm is not None and ocf_ttm > 0:
            f_score += 7
            if ocf_to_ni is not None and ocf_to_ni >= 0.9:
                f_score += 6
            elif ocf_to_ni is not None and ocf_to_ni >= 0.65:
                f_score += 3
        if fcf_ttm is not None and fcf_ttm > 0:
            f_score += 7
        elif fcf_ttm is None and ocf_ttm and ocf_ttm > 0:
            f_score += 3

        # c) Bilanco Saglamligi (20 puan)
        if net_debt_to_ebitda is not None:
            if net_debt_to_ebitda < 0:
                f_score += 10  # Net nakit!
            elif net_debt_to_ebitda <= 1.5:
                f_score += 8
            elif net_debt_to_ebitda <= 2.8:
                f_score += 5
            elif net_debt_to_ebitda <= 4.0:
                f_score += 2
        elif net_debt_latest is not None and net_debt_latest < 0:
            f_score += 10
        else:
            f_score += 4

        if current_ratio is not None:
            if current_ratio >= 1.5:
                f_score += 5
            elif current_ratio >= 1.0:
                f_score += 3
            else:
                f_score += 1
        else:
            f_score += 2.5

        if interest_coverage is not None:
            if interest_coverage >= 6:
                f_score += 5
            elif interest_coverage >= 3:
                f_score += 3
            elif interest_coverage >= 1.5:
                f_score += 1
        else:
            f_score += 3

        # d) Bilimsel Skorlar & Buyume (20 puan)
        if piotroski_score is not None and piotroski_avail >= 5:
            f_score += (piotroski_score / piotroski_avail) * 10
        else:
            f_score += 5
        if rev_growth_yoy is not None:
            f_score += 5 if rev_growth_yoy >= 15 else (3 if rev_growth_yoy >= 3 else (1 if rev_growth_yoy > 0 else 0))
        if ebit_growth_yoy is not None:
            f_score += 5 if ebit_growth_yoy >= 15 else (3 if ebit_growth_yoy >= 3 else (1 if ebit_growth_yoy > 0 else 0))
        elif ni_growth_yoy is not None:
            f_score += 5 if ni_growth_yoy >= 15 else (3 if ni_growth_yoy >= 3 else (1 if ni_growth_yoy > 0 else 0))

        # e) Degerleme (15 puan)
        val_pts = 0.0
        val_cnt = 0
        if ev_ebitda is not None and ev_ebitda > 0:
            val_cnt += 1
            val_pts += 15 if ev_ebitda <= 10 else (11 if ev_ebitda <= 16 else (7 if ev_ebitda <= 24 else 3))
        if fcf_yield is not None:
            val_cnt += 1
            val_pts += 15 if fcf_yield >= 0.06 else (11 if fcf_yield >= 0.035 else (6 if fcf_yield > 0 else 1))
        if pe is not None and pe > 0:
            val_cnt += 1
            val_pts += 15 if pe <= 15 else (11 if pe <= 24 else (7 if pe <= 35 else 3))
        f_score += (val_pts / val_cnt) if val_cnt > 0 else 6.0

        # Kirmizi bayrak kesintileri
        if altman["applicable"] and altman["score"] is not None and altman["score"] < 1.81:
            f_score -= 6
        if beneish["applicable"] and beneish["score"] is not None and beneish["score"] > -1.78:
            f_score -= 5

    fund_score = int(max(0, min(100, round(f_score))))

    # Kirmizi & Yesil Bayraklar
    flags_good = []
    flags_warn = []
    notes = []

    if is_bist:
        notes.append("TMS 29 (Enflasyon Muhasebesi) nedeniyle BIST hisselerinde Net Kâr/F/K yerine FAVÖK, Esas Faaliyet Kârı ve Nakit Akışı kalemleri önceliklendirilmelidir.")
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
    if not is_financial and inv_growth_yoy is not None and rev_growth_yoy is not None and (inv_growth_yoy - rev_growth_yoy) > 25:
        flags_warn.append(f"Peter Lynch Stok Uyarısı: Stok artışı (+{_safe(inv_growth_yoy, 1)}%) satış artışından (+{_safe(rev_growth_yoy, 1)}%) belirgin hızlı.")
    if not is_financial and rec_growth_yoy is not None and rev_growth_yoy is not None and (rec_growth_yoy - rev_growth_yoy) > 25:
        flags_warn.append(f"Alacak Uyarısı: Ticari alacak artışı (+{_safe(rec_growth_yoy, 1)}%) satış artışından belirgin hızlı.")
    if dilution_pct is not None and dilution_pct > 10:
        flags_warn.append(f"Hisse Seyreltmesi: Pay sayısı yıllık +{_safe(dilution_pct, 1)}% artmış.")
    if altman["applicable"] and altman["score"] is not None and altman["score"] < 1.81:
        flags_warn.append(f"Altman Z-Score ({altman['score']}) finansal sıkıntı bölgesinde (< 1.81).")
    if beneish["applicable"] and beneish["score"] is not None and beneish["score"] > -1.78:
        flags_warn.append(f"Beneish M-Score ({beneish['score']}) agresif muhasebe eşiğinin (> -1.78) üzerinde.")

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
