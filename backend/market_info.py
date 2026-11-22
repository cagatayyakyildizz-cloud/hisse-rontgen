"""Analist hedef fiyatlari, bilanco takvimi ve finansman (nakit omru / seyrelme) riski."""
from __future__ import annotations

import datetime as dt
import math
from typing import Any

import pandas as pd

# Bilanco bu kadar gun icindeyse "bilanco riski" uyarisi verilir
EARNINGS_WARN_DAYS = 7
# Analist not degisikliklerinde gosterilecek pencere (gun) ve en fazla kurum sayisi
ANALYST_LOOKBACK_DAYS = 180
ANALYST_MAX_FIRMS = 15
# Nakit omru esikleri (ay)
RUNWAY_DANGER_MONTHS = 12
RUNWAY_WARN_MONTHS = 24

RECOMMENDATION_TR = {
    "strong_buy": "Güçlü Al",
    "buy": "Al",
    "hold": "Tut",
    "underperform": "Endeks Altı",
    "sell": "Sat",
    "strong_sell": "Güçlü Sat",
    "none": "—",
}
ACTION_TR = {"up": "Not yükseltme", "down": "Not düşürme", "main": "Notu korudu", "init": "Kapsama başladı",
             "reit": "Notu teyit etti"}


def _num(v: Any) -> float | None:
    try:
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except Exception:
        return None


def _today() -> dt.date:
    return dt.date.today()


# ---------------------------------------------------------------- analist hedefleri

def analyst_view(bundle: dict[str, Any], price: float | None) -> dict[str, Any] | None:
    """
    ABD / global hisseler icin Wall Street analistlerinin hedef fiyat ozeti ve son not degisiklikleri.
    Bunlar ARACI KURUM tahminleridir; uygulamanin onerisi degildir. BIST icin None doner.
    """
    if bundle.get("is_bist"):
        return None
    info = bundle.get("info") or {}
    mean, median = _num(info.get("targetMeanPrice")), _num(info.get("targetMedianPrice"))
    high, low = _num(info.get("targetHighPrice")), _num(info.get("targetLowPrice"))
    count = info.get("numberOfAnalystOpinions")

    def _upside(target: float | None) -> float | None:
        if target is None or not price:
            return None
        return round((target / price - 1.0) * 100.0, 1)

    actions = _recent_actions(bundle.get("upgrades_downgrades"))
    if mean is None and not actions:
        return {"available": False, "note": "Bu hisse için analist hedef fiyatı bulunamadı."}

    rec_key = (info.get("recommendationKey") or "none").lower()
    return {
        "available": True,
        "currency": bundle.get("currency_major") or bundle.get("currency"),
        "analyst_count": int(count) if isinstance(count, (int, float)) and not math.isnan(count) else None,
        "recommendation": RECOMMENDATION_TR.get(rec_key, rec_key),
        "recommendation_mean": _num(info.get("recommendationMean")),  # 1 = Guclu Al ... 5 = Sat
        "target_mean": mean,
        "target_median": median,
        "target_high": high,
        "target_low": low,
        "upside_mean_pct": _upside(mean),
        "upside_median_pct": _upside(median),
        "upside_high_pct": _upside(high),
        "upside_low_pct": _upside(low),
        "recent_actions": actions,
        "note": ("Hedef fiyatlar aracı kurum analistlerinin tahminleridir; uygulamanın önerisi değildir. "
                 "Hedefler genellikle fiyat hareketinin gerisinde kalır."),
    }


def _recent_actions(df: pd.DataFrame | None) -> list[dict[str, Any]]:
    """Son ANALYST_LOOKBACK_DAYS gundeki not/hedef degisiklikleri; her kurumun en son islemi."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return []
    try:
        idx = pd.to_datetime(df.index)
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_localize(None)
        data = df.copy()
        data.index = idx
        cutoff = pd.Timestamp(_today()) - pd.Timedelta(days=ANALYST_LOOKBACK_DAYS)
        data = data[data.index >= cutoff].sort_index(ascending=False)
    except Exception:
        return []
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for ts, row in data.iterrows():
        firm = str(row.get("Firm") or "").strip()
        if not firm or firm in seen:
            continue
        seen.add(firm)
        target = _num(row.get("currentPriceTarget"))
        prior = _num(row.get("priorPriceTarget"))
        out.append({
            "date": ts.strftime("%Y-%m-%d"),
            "firm": firm,
            "to_grade": str(row.get("ToGrade") or ""),
            "from_grade": str(row.get("FromGrade") or ""),
            "action": ACTION_TR.get(str(row.get("Action") or "").lower(), str(row.get("Action") or "")),
            "target": target if target else None,
            "prior_target": prior if prior else None,
        })
        if len(out) >= ANALYST_MAX_FIRMS:
            break
    return out


# ---------------------------------------------------------------- bilanco takvimi

def earnings_info(bundle: dict[str, Any]) -> dict[str, Any]:
    """Siradaki bilanco tarihi ve kac gun kaldigi; 7 gun icindeyse uyari."""
    today = _today()
    candidates: list[dt.date] = []
    cal = bundle.get("calendar") or {}
    for d in cal.get("Earnings Date") or []:
        try:
            candidates.append(pd.Timestamp(d).date())
        except Exception:
            continue
    info = bundle.get("info") or {}
    for key in ("earningsTimestampStart", "earningsTimestamp"):
        ts = _num(info.get(key))
        if ts:
            candidates.append(dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).date())
    future = sorted(d for d in candidates if d >= today)
    past = sorted(d for d in candidates if d < today)
    nxt = future[0] if future else None
    days = (nxt - today).days if nxt else None
    warn = days is not None and days <= EARNINGS_WARN_DAYS
    return {
        "next_date": nxt.isoformat() if nxt else None,
        "days_until": days,
        "is_estimate": bool(info.get("isEarningsDateEstimate")) if nxt else None,
        "last_date": past[-1].isoformat() if past else None,
        "warning": (f"Bilanço {days} gün içinde ({nxt.isoformat()}): fiyat sert hareket edebilir; "
                    "pozisyon büyüklüğünü buna göre ayarlayın.") if warn else None,
        "eps_estimate": _num(cal.get("Earnings Average")),
        "revenue_estimate": _num(cal.get("Revenue Average")),
    }


# ---------------------------------------------------------------- finansman riski

def _share_series(bundle: dict[str, Any]) -> pd.Series:
    for key in ("quarterly_balance", "balance_sheet"):
        df = bundle.get(key)
        if isinstance(df, pd.DataFrame) and not df.empty:
            for row in ("Ordinary Shares Number", "Share Issued"):
                if row in df.index:
                    s = df.loc[row].dropna()
                    if len(s) >= 2:
                        return s.sort_index()
    return pd.Series(dtype=float)


def financing_risk(bundle: dict[str, Any], fund: dict[str, Any]) -> dict[str, Any]:
    """
    Ozellikle zarar eden / nakit yakan sirketler icin:
      * Nakit omru: (nakit + kisa vadeli yatirim) / aylik serbest nakit yakimi
      * Seyrelme: pay sayisinin son ~1 yildaki artisi ve hisse bazli odeme yuku
      * Yakin vadeli borc (SEC verisi varsa)
    """
    cq, bh = fund["cash_quality"], fund["balance_health"]
    fcf, ocf, cash = cq.get("fcf_ttm"), cq.get("ocf_ttm"), bh.get("cash")
    burn_monthly = (-fcf / 12.0) if (fcf is not None and fcf < 0) else None
    runway = (cash / burn_monthly) if (burn_monthly and cash is not None and cash > 0) else None

    shares = _share_series(bundle)
    share_growth = None
    if len(shares) >= 2:
        latest_date = shares.index[-1]
        older = shares[shares.index <= latest_date - pd.Timedelta(days=330)]
        base = older.iloc[-1] if len(older) else shares.iloc[0]
        if base:
            share_growth = (shares.iloc[-1] / base - 1.0) * 100.0

    sbc = None
    for key in ("quarterly_cashflow", "cashflow"):
        df = bundle.get(key)
        if isinstance(df, pd.DataFrame) and "Stock Based Compensation" in getattr(df, "index", []):
            vals = df.loc["Stock Based Compensation"].dropna()
            if key == "quarterly_cashflow" and len(vals) >= 4:
                sbc = float(vals.sort_index(ascending=False).iloc[:4].sum())
                break
            if key == "cashflow" and len(vals):
                sbc = float(vals.sort_index(ascending=False).iloc[0])
                break
    sec = fund.get("sec") or {}
    revenue = fund.get("revenue_ttm")
    sbc_pct_rev = (abs(sbc) / revenue * 100.0) if (sbc and revenue and revenue > 0) else None

    flags: list[str] = []
    level = "low"
    if runway is not None:
        if runway < RUNWAY_DANGER_MONTHS:
            level = "high"
            flags.append(f"Nakit ömrü yaklaşık {runway:.0f} ay: mevcut yakım hızında 1 yıl içinde yeni finansman "
                         "(hisse ihracı veya borç) gerekebilir.")
        elif runway < RUNWAY_WARN_MONTHS:
            level = "medium"
            flags.append(f"Nakit ömrü yaklaşık {runway:.0f} ay: 2 yıl içinde ek finansman ihtiyacı doğabilir.")
    elif fcf is not None and fcf < 0 and (cash is None or cash <= 0):
        level = "high"
        flags.append("Serbest nakit akışı negatif ve nakit verisi yok/sıfır: finansman riski yüksek.")
    if share_growth is not None and share_growth > 10:
        level = "high" if share_growth > 25 else ("medium" if level == "low" else level)
        flags.append(f"Pay sayısı son bir yılda %{share_growth:.1f} artmış (seyrelme).")
    near_debt = sec.get("debt_due_24m")
    if near_debt and cash is not None and near_debt > cash * 0.5:
        level = "high" if near_debt > cash else ("medium" if level == "low" else level)
        flags.append(f"Önümüzdeki 2 yılda vadesi gelen borç ({near_debt / 1e9:.2f} Mr) nakdin önemli kısmına eşit.")

    return {
        "level": level,
        "fcf_ttm": fcf,
        "ocf_ttm": ocf,
        "monthly_burn": round(burn_monthly, 0) if burn_monthly else None,
        "runway_months": round(runway, 1) if runway is not None else None,
        "share_growth_1y_pct": round(share_growth, 2) if share_growth is not None else None,
        "sbc_ttm": sbc,
        "sbc_pct_revenue": round(sbc_pct_rev, 1) if sbc_pct_rev is not None else None,
        "convertible_debt": sec.get("convertible_debt"),
        "debt_due_12m": sec.get("debt_due_12m"),
        "debt_due_24m": near_debt,
        "flags": flags,
    }
