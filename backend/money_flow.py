from __future__ import annotations

import math
import time
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

from .cache import TTLCache
from .reference_data import themes as load_themes

# Tema haritalari: backend/data/themes.json (sadece hisse senedi, ETF yok)
BIST_THEMES: dict[str, list[str]] = load_themes("bist")
US_THEMES: dict[str, list[str]] = load_themes("us")

# Son islem tarihi endeksten bu kadar takvim gunu gerideyse (islem durdurma, kotasyondan
# cikma vb.) hisse bayat veri sayilir ve akis hesabina katilmaz
MAX_STALE_DAYS = 4

# Likidite filtresi: 20 gunluk ortalama islem hacmi bu esigin altindaki hisseler akis hesabina
# katilmaz (cok sig hisselerde birkac emir skoru bozar). Para birimi piyasanin kendi birimidir.
MIN_AVG_TURNOVER = {"bist": 25_000_000.0, "us": 20_000_000.0}

WINDOWS = {
    "1d": 1,
    "1w": 5,
    "1m": 21,
    "3m": 63,
}

_FLOW_CACHE = TTLCache(max_entries=4)
FLOW_TTL = 600  # 10 dakika


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


def _extract_ticker_df(raw: pd.DataFrame, sym: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()
    try:
        if isinstance(raw.columns, pd.MultiIndex):
            if sym in raw.columns.get_level_values(0):
                df = raw[sym].copy()
            elif sym in raw.columns.get_level_values(1):
                df = raw.xs(sym, axis=1, level=1).copy()
            else:
                return pd.DataFrame()
        else:
            df = raw.copy()
        df = df.dropna(subset=["Close"])
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        return df
    except Exception:
        return pd.DataFrame()


def _compute_window_metrics(
    df: pd.DataFrame,
    bench_ret: float | None,
    days: int,
) -> dict[str, Any]:
    """
    Belirli bir donem (1g / 5g / 21g / 63g) icin:
      - Donem getirisi (%)
      - Endekse gore fark (RS %)
      - RVOL (donem ortalama hacmi / 20 gunluk baz hacim)
      - CMF (Chaikin Money Flow / alim-satim baskisi, -1..+1)
      - Yaklasik Net Para Akisi (MFM * Hacim * Kapanis toplami)
      - Toplam Islem Hacmi (Turnover)
      - Para Akisi Skoru (-100 .. +100)
    """
    n = len(df)
    if n < max(days + 1, 5):
        return {
            "ret_pct": None,
            "rs_pct": None,
            "rvol": None,
            "cmf": None,
            "net_flow": None,
            "turnover": None,
            "flow_score": 0,
            "label": "Veri Yok",
        }

    close = df["Close"].astype(float)
    vol = df["Volume"].fillna(0).astype(float)

    p_end = float(close.iloc[-1])
    p_start = float(close.iloc[-days - 1])
    ret_pct = ((p_end / p_start) - 1.0) * 100.0 if p_start > 0 else 0.0
    rs_pct = (ret_pct - bench_ret) if bench_ret is not None else ret_pct

    # Baz hacim (son 20 gun ortalama hacim)
    base_vol = float(vol.iloc[-min(20, n):].mean())
    win_slice = df.iloc[-days:]
    w_close = win_slice["Close"].astype(float)
    w_high = win_slice["High"].astype(float)
    w_low = win_slice["Low"].astype(float)
    w_vol = win_slice["Volume"].fillna(0).astype(float)

    win_avg_vol = float(w_vol.mean())
    rvol = (win_avg_vol / base_vol) if base_vol > 0 else 1.0

    # Money Flow Multiplier: ((C - L) - (H - C)) / (H - L) -> [-1, +1]
    hl = (w_high - w_low).replace(0, np.nan)
    mfm = (((w_close - w_low) - (w_high - w_close)) / hl).fillna(0.0).clip(-1.0, 1.0)
    # 1 gunluk gap hareketlerinde MFM tek basina eksik kalabilecegi icin gunluk yonle hafif harmanla
    if days == 1 and n >= 2:
        prev_c = float(close.iloc[-2])
        day_dir = np.clip(((p_end / prev_c) - 1.0) / 0.03, -1.0, 1.0) if prev_c > 0 else 0.0
        mfm_val = float(mfm.iloc[-1]) * 0.6 + float(day_dir) * 0.4
        turnover = float(w_close.iloc[-1] * w_vol.iloc[-1])
        net_flow = mfm_val * turnover
        cmf = mfm_val
    else:
        turnovers = w_close * w_vol
        turnover = float(turnovers.sum())
        mfv = mfm * turnovers
        net_flow = float(mfv.sum())
        cmf = (net_flow / turnover) if turnover > 0 else 0.0

    # Doneme gore normalize getiri katsayisi (1g icin %3, 1h icin %6, 1a icin %12, 3a icin %22 = guclu hareket)
    scale = {1: 3.2, 5: 6.5, 21: 13.0, 63: 24.0}.get(days, 10.0)
    ret_comp = max(-1.0, min(1.0, ret_pct / scale))
    rs_comp = max(-1.0, min(1.0, rs_pct / scale))
    cmf_comp = max(-1.0, min(1.0, cmf * 1.45))

    # RVOL carpan etkisi: yuksek hacim sinyali guclendirir, cok dusuk hacim sinyali zayiflatir
    vol_mult = min(1.35, max(0.65, 0.75 + 0.30 * min(rvol, 2.5)))
    raw_score = (ret_comp * 42.0 + rs_comp * 26.0 + cmf_comp * 32.0) * vol_mult
    flow_score = int(max(-100, min(100, round(raw_score))))

    if flow_score >= 30:
        label = "Güçlü Giriş"
    elif flow_score >= 10:
        label = "Ilımlı Giriş"
    elif flow_score <= -30:
        label = "Güçlü Çıkış"
    elif flow_score <= -10:
        label = "Ilımlı Çıkış"
    else:
        label = "Nötr / Yatay"

    return {
        "ret_pct": _safe(ret_pct, 2),
        "rs_pct": _safe(rs_pct, 2),
        "rvol": _safe(rvol, 2),
        "cmf": _safe(cmf, 2),
        "net_flow": _safe(net_flow, 0),
        "turnover": _safe(turnover, 0),
        "flow_score": flow_score,
        "label": label,
    }


def _period_return(df: pd.DataFrame, days: int) -> float | None:
    if df is None or df.empty or len(df) < days + 1:
        return None
    p0 = float(df["Close"].iloc[-days - 1])
    p1 = float(df["Close"].iloc[-1])
    return _safe(((p1 / p0) - 1.0) * 100.0, 2) if p0 > 0 else None


def compute_money_flow(market: str = "bist", force_refresh: bool = False) -> dict[str, Any]:
    mkt = "us" if (market or "bist").lower() == "us" else "bist"
    cache_key = f"flow:{mkt}"
    if not force_refresh:
        cached = _FLOW_CACHE.get(cache_key, FLOW_TTL)
        if cached is not None:
            return cached

    themes_map = BIST_THEMES if mkt == "bist" else US_THEMES
    bench_symbol = "XU100.IS" if mkt == "bist" else "^GSPC"
    bench_name = "BIST 100" if mkt == "bist" else "S&P 500"
    currency = "TRY" if mkt == "bist" else "USD"

    all_symbols = sorted({sym for syms in themes_map.values() for sym in syms} | {bench_symbol})

    raw = yf.download(
        tickers=all_symbols,
        period="6mo",
        interval="1d",
        group_by="ticker",
        auto_adjust=True,
        threads=True,
        progress=False,
    )

    bench_df = _extract_ticker_df(raw, bench_symbol)
    bench_returns = {k: _period_return(bench_df, d) for k, d in WINDOWS.items()}
    last_date = bench_df.index[-1].strftime("%Y-%m-%d") if not bench_df.empty else time.strftime("%Y-%m-%d")

    # Hisse bazli metrikler
    sym_to_theme: dict[str, str] = {}
    for t_name, syms in themes_map.items():
        for s in syms:
            sym_to_theme[s] = t_name

    stocks_list: list[dict[str, Any]] = []
    stock_by_sym: dict[str, dict[str, Any]] = {}

    bench_last = bench_df.index[-1] if not bench_df.empty else None
    stale_symbols: list[str] = []
    missing_symbols: list[str] = []
    illiquid_symbols: list[str] = []

    for sym, theme_name in sym_to_theme.items():
        df = _extract_ticker_df(raw, sym)
        if df.empty or len(df) < 10:
            missing_symbols.append(sym)
            continue
        if bench_last is not None and (bench_last - df.index[-1]).days > MAX_STALE_DAYS:
            # Endeksle ayni gunun verisi yoksa getiriler endeksle kiyaslanamaz
            stale_symbols.append(sym)
            continue
        turnover20 = float((df["Close"] * df["Volume"].fillna(0)).iloc[-min(20, len(df)):].mean())
        if turnover20 < MIN_AVG_TURNOVER[mkt]:
            illiquid_symbols.append(sym)
            continue
        last_close = _safe(df["Close"].iloc[-1], 2)
        avg_turnover_20d = _safe(float((df["Close"] * df["Volume"].fillna(0)).iloc[-min(20, len(df)):].mean()), 0)

        periods: dict[str, Any] = {}
        for wk, days in WINDOWS.items():
            periods[wk] = _compute_window_metrics(df, bench_returns.get(wk), days)

        # Rotasyon sinyali: 1A zayif ama 1H guclu giris -> "Erken Donus / Rotasyon"
        m_1w = periods["1w"]["flow_score"]
        m_1m = periods["1m"]["flow_score"]
        rotation_tag = ""
        if m_1w >= 25 and m_1m <= -5:
            rotation_tag = "Erken Para Girişi"
        elif m_1w <= -25 and m_1m >= 15:
            rotation_tag = "Kâr Satışı / Çıkış"
        elif m_1w >= 25 and m_1m >= 25:
            rotation_tag = "Sürekli Liderlik"
        elif m_1w <= -25 and m_1m <= -25:
            rotation_tag = "Sürekli Zayıflık"

        entry_obj = {
            "symbol": sym,
            "display_symbol": sym[:-3] if sym.endswith(".IS") else sym,
            "theme": theme_name,
            "is_bist": mkt == "bist",
            "currency": currency,
            "price": last_close,
            "avg_turnover_20d": avg_turnover_20d,
            "rotation_tag": rotation_tag,
            "periods": periods,
        }
        stocks_list.append(entry_obj)
        stock_by_sym[sym] = entry_obj

    # Tema bazli toplulastirma (her zaman dilimi icin!)
    themes_list: list[dict[str, Any]] = []
    for theme_name, syms in themes_map.items():
        members = [stock_by_sym[s] for s in syms if s in stock_by_sym]
        if not members:
            continue

        theme_periods: dict[str, Any] = {}
        for wk in WINDOWS:
            valid = [m for m in members if m["periods"][wk]["ret_pct"] is not None]
            if not valid:
                theme_periods[wk] = {
                    "flow_score": 0, "ret_pct": None, "rs_pct": None, "rvol": None,
                    "cmf": None, "net_flow": 0, "turnover": 0, "pos_count": 0,
                    "inflow_count": 0, "total": len(members), "label": "Veri Yok",
                }
                continue

            # Tema skoru islem hacmiyle agirliklandirilir: buyuk ve likit hisselerin akisi daha cok sayar.
            # Tek bir dev hissenin temayi tamamen domine etmemesi icin agirliklar karekokle yumusatilir.
            weights = [math.sqrt(max(m["avg_turnover_20d"] or 0.0, 0.0)) or 1.0 for m in valid]
            avg_score = int(round(sum(w * m["periods"][wk]["flow_score"] for w, m in zip(weights, valid)) / sum(weights)))
            avg_ret = _safe(sum(m["periods"][wk]["ret_pct"] for m in valid) / len(valid), 2)
            avg_rs = _safe(sum((m["periods"][wk]["rs_pct"] or 0) for m in valid) / len(valid), 2)
            avg_rvol = _safe(sum((m["periods"][wk]["rvol"] or 1) for m in valid) / len(valid), 2)
            total_turnover = sum((m["periods"][wk]["turnover"] or 0) for m in valid)
            total_net_flow = sum((m["periods"][wk]["net_flow"] or 0) for m in valid)
            agg_cmf = _safe((total_net_flow / total_turnover) if total_turnover > 0 else 0.0, 2)
            pos_count = sum(1 for m in valid if (m["periods"][wk]["ret_pct"] or 0) > 0)
            inflow_count = sum(1 for m in valid if m["periods"][wk]["flow_score"] >= 10)

            lbl = (
                "Güçlü Giriş" if avg_score >= 25 else
                "Ilımlı Giriş" if avg_score >= 8 else
                "Güçlü Çıkış" if avg_score <= -25 else
                "Ilımlı Çıkış" if avg_score <= -8 else
                "Nötr / Yatay"
            )
            theme_periods[wk] = {
                "flow_score": avg_score,
                "ret_pct": avg_ret,
                "rs_pct": avg_rs,
                "rvol": avg_rvol,
                "cmf": agg_cmf,
                "net_flow": _safe(total_net_flow, 0),
                "turnover": _safe(total_turnover, 0),
                "pos_count": pos_count,
                "inflow_count": inflow_count,
                "total": len(valid),
                "label": lbl,
            }

        # Tema lideri (haftalik akis skoruna gore)
        top_member = max(members, key=lambda m: m["periods"]["1w"]["flow_score"])
        # Tema rotasyon etiketi
        ts_1w = theme_periods["1w"]["flow_score"]
        ts_1m = theme_periods["1m"]["flow_score"]
        t_rot = ""
        if ts_1w >= 18 and ts_1m <= -5:
            t_rot = "Rotasyon Başlangıcı"
        elif ts_1w <= -18 and ts_1m >= 12:
            t_rot = "Zayıflama / Çıkış"
        elif ts_1w >= 20 and ts_1m >= 20:
            t_rot = "Ana Lider Tema"
        elif ts_1w <= -20 and ts_1m <= -20:
            t_rot = "Baskı Altında"

        themes_list.append(
            {
                "name": theme_name,
                "stock_count": len(members),
                "top_stock": top_member["display_symbol"],
                "rotation_tag": t_rot,
                "periods": theme_periods,
            }
        )

    # Piyasa genisligi ozeti (her donem icin)
    breadth: dict[str, Any] = {}
    for wk in WINDOWS:
        valid = [s for s in stocks_list if s["periods"][wk]["ret_pct"] is not None]
        tot = len(valid)
        pos = sum(1 for s in valid if (s["periods"][wk]["ret_pct"] or 0) > 0)
        inf = sum(1 for s in valid if s["periods"][wk]["flow_score"] >= 10)
        outf = sum(1 for s in valid if s["periods"][wk]["flow_score"] <= -10)
        breadth[wk] = {
            "total": tot,
            "positive": pos,
            "positive_pct": int(round((pos / tot) * 100)) if tot else 0,
            "inflow": inf,
            "outflow": outf,
        }

    result = {
        "market": mkt,
        "market_label": "BIST (Borsa İstanbul)" if mkt == "bist" else "ABD / Global",
        "currency": currency,
        "benchmark_name": bench_name,
        "benchmark_returns": bench_returns,
        "last_date": last_date,
        "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "breadth": breadth,
        "excluded": {"stale": stale_symbols, "missing": missing_symbols, "illiquid": illiquid_symbols},
        "min_avg_turnover": MIN_AVG_TURNOVER[mkt],
        "note": "Para akışı; fiyat, hacim ve gün içi kapanış konumundan (Chaikin) TAHMİN edilir. Gerçek takas / aracı kurum (AKD) verisi değildir.",
        "themes": themes_list,
        "stocks": stocks_list,
    }
    _FLOW_CACHE.set(cache_key, result)
    return result
