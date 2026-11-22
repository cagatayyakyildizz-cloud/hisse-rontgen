from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from .scoring import ScoreCard

# Teknik puan agirliklari (toplam 100). tools/backtest_teknik.py --components ciktisina gore
# ayarlanir; degistirirseniz testi tekrar calistirip sonucu README'ye not edin.
TECH_WEIGHTS: dict[str, float] = {
    "minervini": 30.0,
    "weinstein": 15.0,
    "rs_level": 12.0,
    "rs_trend": 3.0,
    "avwap_low": 5.0,
    "avwap_high_ytd": 4.0,
    "vcp": 3.0,
    "volume": 3.0,
    "regime": 5.0,
    "confirm": 5.0,
    "rsi": 5.0,
    "macd": 5.0,
    "extension": 5.0,
}

# Geriye donuk test kaniti (docs/BACKTEST.md). Arayuzde puanin ne kadar guvenilir oldugunu gosterir.
BACKTEST_EVIDENCE: dict[str, dict[str, Any]] = {
    "bist": {"monthly_ic": 0.147, "observations": 3423, "strength": "güçlü",
             "note": "Geriye dönük testte (5 yıl, 87 hisse) teknik puan BIST'te sonraki 6 aylık göreli getiriyi "
                     "anlamlı biçimde sıraladı (aylık IC 0.15)."},
    "us": {"monthly_ic": 0.031, "observations": 2784, "strength": "zayıf",
           "note": "Geriye dönük testte (5 yıl, 67 hisse) teknik puanın ABD'de sonraki 6 aylık göreli getiriyle "
                   "ilişkisi zayıf ve kararsız bulundu (aylık IC 0.03). Tek başına karar ölçütü olarak kullanmayın."},
}


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


def _compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _compute_macd(close: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    return macd, signal, hist


def _compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["High"]
    low = df["Low"]
    prev_close = df["Close"].shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def _compute_avwap(df: pd.DataFrame, start_idx: int) -> pd.Series:
    """Belirli bir bar indeksinden baslayan Anchored VWAP serisi."""
    result = pd.Series(np.nan, index=df.index, dtype=float)
    if start_idx < 0 or start_idx >= len(df):
        return result
    sub = df.iloc[start_idx:]
    typical = (sub["High"] + sub["Low"] + sub["Close"]) / 3.0
    vol = sub["Volume"].fillna(0).astype(float)
    cum_vol = vol.cumsum()
    cum_pv = (typical * vol).cumsum()
    avwap = cum_pv / cum_vol.replace(0, np.nan)
    # Hacim 0 ise tipik fiyata geri dus
    avwap = avwap.fillna(typical)
    result.iloc[start_idx:] = avwap
    return result


def _series_to_chart_points(series: pd.Series) -> list[dict[str, Any]]:
    pts = []
    for dt, v in series.items():
        sv = _safe(v, 4)
        if sv is not None:
            pts.append({"time": dt.strftime("%Y-%m-%d"), "value": sv})
    return pts


def _build_ohlcv_chart(df: pd.DataFrame, avwap_low_idx: int, avwap_high_idx: int) -> dict[str, Any]:
    sma50 = df["Close"].rolling(50).mean()
    sma150 = df["Close"].rolling(150).mean()
    sma200 = df["Close"].rolling(200).mean()
    avwap_low = _compute_avwap(df, avwap_low_idx)
    avwap_high = _compute_avwap(df, avwap_high_idx)

    candles = []
    volumes = []
    for dt, row in df.iterrows():
        o, h, l, c = _safe(row["Open"], 4), _safe(row["High"], 4), _safe(row["Low"], 4), _safe(row["Close"], 4)
        if None in (o, h, l, c):
            continue
        t_str = dt.strftime("%Y-%m-%d")
        candles.append({"time": t_str, "open": o, "high": h, "low": l, "close": c})
        v = _safe(row.get("Volume", 0), 0) or 0
        volumes.append(
            {
                "time": t_str,
                "value": v,
                "color": "rgba(34, 197, 94, 0.42)" if c >= o else "rgba(239, 68, 68, 0.42)",
            }
        )

    return {
        "candles": candles,
        "volumes": volumes,
        "sma50": _series_to_chart_points(sma50),
        "sma150": _series_to_chart_points(sma150),
        "sma200": _series_to_chart_points(sma200),
        "avwap_low": _series_to_chart_points(avwap_low),
        "avwap_high": _series_to_chart_points(avwap_high),
    }


def analyze_technical(bundle: dict[str, Any], include_charts: bool = True) -> dict[str, Any]:
    """include_charts=False: grafik serileri uretilmez (geriye donuk test icin hizli)."""
    df: pd.DataFrame = bundle["history"]
    bench: pd.DataFrame = bundle["benchmark"]
    usdtry: pd.DataFrame = bundle["usdtry"]
    is_bist: bool = bundle["is_bist"]

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"].fillna(0)

    n = len(df)
    last_close = float(close.iloc[-1])
    prev_close = float(close.iloc[-2]) if n >= 2 else last_close
    daily_change_pct = ((last_close / prev_close) - 1.0) * 100.0 if prev_close else 0.0

    # Hareketli ortalamalar
    sma10 = close.rolling(10).mean()
    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    sma150 = close.rolling(150).mean()
    sma200 = close.rolling(200).mean()

    v_sma10 = _safe(sma10.iloc[-1], 4)
    v_sma20 = _safe(sma20.iloc[-1], 4)
    v_sma50 = _safe(sma50.iloc[-1], 4)
    v_sma150 = _safe(sma150.iloc[-1], 4)
    v_sma200 = _safe(sma200.iloc[-1], 4)

    # 200 SMA son 20 islem gunu egimi
    sma200_1m_ago = _safe(sma200.iloc[-21], 4) if n >= 221 else None
    sma200_rising = bool(v_sma200 is not None and sma200_1m_ago is not None and v_sma200 > sma200_1m_ago)

    # 52 haftalik (son ~252 islem gunu) zirve ve dip
    win52 = df.iloc[-min(252, n):]
    high_52w = float(win52["High"].max())
    low_52w = float(win52["Low"].min())
    high_52w_date = win52["High"].idxmax()
    low_52w_date = win52["Low"].idxmin()

    dist_from_high_pct = ((last_close / high_52w) - 1.0) * 100.0 if high_52w else 0.0
    dist_from_low_pct = ((last_close / low_52w) - 1.0) * 100.0 if low_52w else 0.0
    ext_from_sma50_pct = ((last_close / v_sma50) - 1.0) * 100.0 if v_sma50 else None
    ext_from_sma20_pct = ((last_close / v_sma20) - 1.0) * 100.0 if v_sma20 else None

    # --- 1. Mark Minervini 8'li Trend Sablonu ---
    minervini_checks = [
        {"name": "Fiyat > 50 Günlük SMA", "passed": bool(v_sma50 and last_close > v_sma50), "detail": f"{_safe(last_close)} vs {v_sma50}"},
        {"name": "Fiyat > 150 Günlük SMA", "passed": bool(v_sma150 and last_close > v_sma150), "detail": f"{_safe(last_close)} vs {v_sma150}"},
        {"name": "Fiyat > 200 Günlük SMA", "passed": bool(v_sma200 and last_close > v_sma200), "detail": f"{_safe(last_close)} vs {v_sma200}"},
        {"name": "50 SMA > 150 SMA", "passed": bool(v_sma50 and v_sma150 and v_sma50 > v_sma150), "detail": f"{v_sma50} vs {v_sma150}"},
        {"name": "150 SMA > 200 SMA", "passed": bool(v_sma150 and v_sma200 and v_sma150 > v_sma200), "detail": f"{v_sma150} vs {v_sma200}"},
        {"name": "200 SMA Yükseliyor (≥ 1 Ay)", "passed": sma200_rising, "detail": f"{sma200_1m_ago} → {v_sma200}" if sma200_1m_ago else "Yetersiz veri"},
        {"name": "52H Zirveye En Fazla %25 Uzak", "passed": dist_from_high_pct >= -25.0, "detail": f"Zirveye {_safe(dist_from_high_pct)}%"},
        {"name": "52H Dipten En Az %30 Yukarıda", "passed": dist_from_low_pct >= 30.0, "detail": f"Dipten +{_safe(dist_from_low_pct)}%"},
    ]
    minervini_passed = sum(1 for c in minervini_checks if c["passed"])

    # --- 2. Stan Weinstein Haftalik Evre (30 Haftalik SMA) ---
    weekly = df["Close"].resample("W-FRI").last().dropna()
    w_sma30 = weekly.rolling(30).mean()
    stage = 0
    stage_label = "Yetersiz Haftalık Veri"
    stage_desc = "30 haftalık ortalama için en az 30 haftalık veri gerekir."
    w_sma30_val = None
    if len(w_sma30.dropna()) >= 5:
        w_last = float(weekly.iloc[-1])
        w_cur = float(w_sma30.iloc[-1])
        w_prev = float(w_sma30.iloc[-5])
        w_sma30_val = _safe(w_cur, 4)
        slope_pct = ((w_cur / w_prev) - 1.0) * 100.0 if w_prev else 0.0
        above_30w = w_last > w_cur
        if above_30w and slope_pct > 0.4:
            stage = 2
            stage_label = "Evre 2 — Yükseliş Trendi"
            stage_desc = "Fiyat yükselen 30 haftalık ortalamanın üzerinde; ana alım ve trend taşıma bölgesi."
        elif not above_30w and slope_pct < -0.4:
            stage = 4
            stage_label = "Evre 4 — Düşüş Trendi"
            stage_desc = "Fiyat düşen 30 haftalık ortalamanın altında; kurumsal dağıtım / düşüş bölgesi."
        elif above_30w:
            stage = 1 if dist_from_low_pct < 35 else 3
            if stage == 1:
                stage_label = "Evre 1 — Taban / Birikim (Erken)"
                stage_desc = "30 haftalık ortalama yataylaşıyor, fiyat üzerine çıkmaya çalışıyor."
            else:
                stage_label = "Evre 3 — Tepe / Dağıtım Riski"
                stage_desc = "Yükseliş sonrası 30 haftalık ortalama ivme kaybediyor; volatilite ve kâr satışı izlenmeli."
        else:
            stage = 1 if slope_pct >= -0.4 and dist_from_low_pct < 35 else 3
            stage_label = "Evre 1 — Taban / Yatay" if stage == 1 else "Evre 3 — Zayıflama / Tepe"
            stage_desc = "30 haftalık ortalama yatay, fiyat hemen altında; hacimli kırılım beklenmeli."

    # --- 3. Volatilite & Risk: ATR(14), ADR%(20), VCP daralma ---
    atr14 = _compute_atr(df, 14)
    v_atr14 = _safe(atr14.iloc[-1], 4)
    atr_pct = _safe((v_atr14 / last_close) * 100.0, 2) if (v_atr14 and last_close) else None

    daily_range_pct = ((high - low) / low.replace(0, np.nan)) * 100.0
    adr20 = _safe(daily_range_pct.rolling(20).mean().iloc[-1], 2)
    adr10 = _safe(daily_range_pct.rolling(10).mean().iloc[-1], 2)
    adr50 = _safe(daily_range_pct.rolling(50).mean().iloc[-1], 2)

    # VCP daralma orani: son 10 gun volatilitesi / 50 gun volatilitesi (< 0.80 = daralma!)
    vcp_ratio = _safe(adr10 / adr50, 2) if (adr10 and adr50 and adr50 > 0) else None
    vcp_tight = bool(vcp_ratio is not None and vcp_ratio <= 0.82 and dist_from_high_pct >= -18.0)

    # Hacim & RVOL
    vol_avg20 = float(volume.rolling(20).mean().iloc[-1]) if n >= 20 else float(volume.mean())
    vol_avg5 = float(volume.rolling(5).mean().iloc[-1]) if n >= 5 else vol_avg20
    last_vol = float(volume.iloc[-1])
    rvol = _safe(last_vol / vol_avg20, 2) if vol_avg20 > 0 else None
    vol_dryup_ratio = _safe(vol_avg5 / vol_avg20, 2) if vol_avg20 > 0 else None
    avg_turnover_20d = _safe(float((close * volume).rolling(20).mean().iloc[-1]), 0) if n >= 20 else None

    # Yapisal stop referanslari
    stop_1adr = _safe(last_close * (1.0 - (adr20 / 100.0)), 2) if adr20 else None
    stop_15atr = _safe(last_close - 1.5 * v_atr14, 2) if v_atr14 else None
    stop_2atr = _safe(last_close - 2.0 * v_atr14, 2) if v_atr14 else None

    # --- 4. Anchored VWAP (52H Dip, 52H Zirve, Yilbasi) ---
    low_pos = int(df.index.get_loc(low_52w_date))
    high_pos = int(df.index.get_loc(high_52w_date))
    avwap_low_s = _compute_avwap(df, low_pos)
    avwap_high_s = _compute_avwap(df, high_pos)
    v_avwap_low = _safe(avwap_low_s.iloc[-1], 4)
    v_avwap_high = _safe(avwap_high_s.iloc[-1], 4)

    ytd_mask = df.index.year == df.index[-1].year
    ytd_pos = int(np.argmax(ytd_mask)) if ytd_mask.any() else 0
    v_avwap_ytd = _safe(_compute_avwap(df, ytd_pos).iloc[-1], 4)

    above_avwap_low = bool(v_avwap_low and last_close >= v_avwap_low)
    above_avwap_high = bool(v_avwap_high and last_close >= v_avwap_high)
    above_avwap_ytd = bool(v_avwap_ytd and last_close >= v_avwap_ytd)

    # --- 5. Goreceli Guc (RS) & Piyasa Rejimi ---
    def _ret(s: pd.Series, days: int) -> float | None:
        if len(s) <= days:
            return None
        p0 = float(s.iloc[-days - 1])
        p1 = float(s.iloc[-1])
        return ((p1 / p0) - 1.0) * 100.0 if p0 > 0 else None

    ret_1m = _safe(_ret(close, 21), 2)
    ret_3m = _safe(_ret(close, 63), 2)
    ret_6m = _safe(_ret(close, 126), 2)
    ret_1y = _safe(_ret(close, min(252, n - 1)), 2) if n > 20 else None

    bench_regime = {
        "name": bundle["benchmark_name"],
        "symbol": bundle["benchmark_symbol"],
        "above_sma50": None,
        "above_sma200": None,
        "status": "Bilinmiyor",
        "ret_3m": None,
        "ret_1y": None,
    }
    rs_info = {
        "excess_3m": None,
        "excess_6m": None,
        "excess_1y": None,
        "rs_above_sma50": None,
        "rs_score_est": None,
        "label": "Veri Yok",
    }

    if bench is not None and not bench.empty and len(bench) >= 50:
        b_close = bench["Close"]
        b_last = float(b_close.iloc[-1])
        b_sma50 = float(b_close.rolling(50).mean().iloc[-1])
        b_sma200 = float(b_close.rolling(200).mean().iloc[-1]) if len(b_close) >= 200 else None
        b_ab50 = b_last > b_sma50
        b_ab200 = (b_last > b_sma200) if b_sma200 else None
        if b_ab50 and (b_ab200 is True or b_ab200 is None):
            b_status = "Güçlü Boğa (50 & 200 SMA Üstü)"
        elif b_ab200 is True:
            b_status = "Düzeltme (200 SMA Üstü, 50 Altı)"
        elif b_ab50:
            b_status = "Toparlanma (50 SMA Üstü, 200 Altı)"
        else:
            b_status = "Zayıf / Ayı (50 & 200 SMA Altı)"
        bench_regime.update(
            {
                "above_sma50": b_ab50,
                "above_sma200": b_ab200,
                "status": b_status,
                "ret_3m": _safe(_ret(b_close, 63), 2),
                "ret_1y": _safe(_ret(b_close, min(252, len(b_close) - 1)), 2),
            }
        )

        # RS Orani (Hisse / Endeks)
        joined = pd.concat([close.rename("s"), b_close.rename("b")], axis=1).dropna()
        if len(joined) >= 65:
            ratio = joined["s"] / joined["b"]
            ratio_sma50 = ratio.rolling(50).mean()
            rs_ab50 = bool(ratio.iloc[-1] > ratio_sma50.iloc[-1])
            ex3 = _safe((_ret(joined["s"], 63) or 0) - (_ret(joined["b"], 63) or 0), 2)
            ex6 = _safe((_ret(joined["s"], 126) or 0) - (_ret(joined["b"], 126) or 0), 2) if len(joined) > 126 else None
            ex1y = _safe((_ret(joined["s"], min(252, len(joined) - 1)) or 0) - (_ret(joined["b"], min(252, len(joined) - 1)) or 0), 2)

            # IBD agirlikli goreceli performans yaklasimi (%40 3A + %20 6A + %40 1Y)
            weighted_ex = (ex3 or 0) * 0.4 + (ex6 if ex6 is not None else (ex3 or 0)) * 0.2 + (ex1y or 0) * 0.4
            rs_est = int(max(1, min(99, round(50 + weighted_ex * 0.85))))
            rs_label = (
                "Lider (Endeksten Güçlü)" if rs_est >= 75 else
                "Endekse Paralel / Pozitif" if rs_est >= 55 else
                "Nötr / Hafif Zayıf" if rs_est >= 40 else
                "Geride Kalan (Laggard)"
            )
            rs_info.update(
                {
                    "excess_3m": ex3,
                    "excess_6m": ex6,
                    "excess_1y": ex1y,
                    "rs_above_sma50": rs_ab50,
                    "rs_score_est": rs_est,
                    "label": rs_label,
                }
            )

    # --- 6. RSI(14) & MACD(12,26,9) (Trend Baglaminda) ---
    rsi_s = _compute_rsi(close, 14)
    v_rsi = _safe(rsi_s.iloc[-1], 2)
    macd_s, sig_s, hist_s = _compute_macd(close)
    v_macd = _safe(macd_s.iloc[-1], 4)
    v_sig = _safe(sig_s.iloc[-1], 4)
    v_hist = _safe(hist_s.iloc[-1], 4)
    macd_bullish = bool(v_macd is not None and v_sig is not None and v_macd > v_sig)

    # --- 7. BIST USD Bazli Analiz ve Grafik ---
    usd_analysis = None
    chart_usd = None
    if is_bist and usdtry is not None and not usdtry.empty:
        fx_aligned = usdtry["Close"].reindex(df.index).ffill().bfill()
        if not fx_aligned.isna().all() and (fx_aligned > 0).all():
            df_usd = df.copy()
            for col in ("Open", "High", "Low", "Close"):
                df_usd[col] = df[col] / fx_aligned
            u_close = df_usd["Close"]
            u_last = float(u_close.iloc[-1])
            u_sma50 = _safe(u_close.rolling(50).mean().iloc[-1], 4)
            u_sma200 = _safe(u_close.rolling(200).mean().iloc[-1], 4) if len(u_close) >= 200 else None
            u_ret1y = _safe(_ret(u_close, min(252, len(u_close) - 1)), 2) if len(u_close) > 20 else None
            u_win52 = df_usd.iloc[-min(252, len(df_usd)):]
            u_low_pos = int(df_usd.index.get_loc(u_win52["Low"].idxmin()))
            u_high_pos = int(df_usd.index.get_loc(u_win52["High"].idxmax()))
            chart_usd = _build_ohlcv_chart(df_usd, u_low_pos, u_high_pos) if include_charts else None
            usd_analysis = {
                "price_usd": _safe(u_last, 4),
                "usdtry_last": _safe(fx_aligned.iloc[-1], 4),
                "sma50_usd": u_sma50,
                "sma200_usd": u_sma200,
                "above_sma50_usd": bool(u_sma50 and u_last > u_sma50),
                "above_sma200_usd": bool(u_sma200 and u_last > u_sma200),
                "ret_1y_usd": u_ret1y,
            }

    # --- 8. Ana Grafik Serisi ---
    chart_primary = _build_ohlcv_chart(df, low_pos, high_pos) if include_charts else None

    # --- 9. Seffaf Teknik Puanlama (0 - 100) ---
    # Her kalem 0..1 arasi bir sinyal uretir; puan = agirlikli ortalama * 100.
    # Agirliklar TECH_WEIGHTS'te tutulur ve tools/backtest_teknik.py sonuclarina gore ayarlanir.
    card = ScoreCard()
    w = TECH_WEIGHTS
    card.add_signal("Minervini trend şablonu", minervini_passed / 8.0, w["minervini"], "minervini",
                    f"{minervini_passed}/8")
    card.add_signal("Weinstein evresi", {2: 1.0, 1: 8 / 15, 3: 5 / 15, 4: 0.0}.get(stage), w["weinstein"], "weinstein",
                    stage_label)

    rs_est = rs_info["rs_score_est"]
    rs_level = None
    if rs_est is not None:
        rs_level = 1.0 if rs_est >= 80 else 0.75 if rs_est >= 65 else 0.5 if rs_est >= 50 else 0.25 if rs_est >= 35 else 0.0
    card.add_signal("RS seviyesi (endekse göre)", rs_level, w["rs_level"], "rs_level",
                    f"~{rs_est}" if rs_est is not None else None)
    rs_trend = None if rs_info["rs_above_sma50"] is None else (1.0 if rs_info["rs_above_sma50"] else 0.0)
    card.add_signal("RS çizgisi 50 günlük ortalamanın üstünde", rs_trend, w["rs_trend"], "rs_trend")

    card.add_signal("52H dip AVWAP üstünde", None if v_avwap_low is None else float(above_avwap_low),
                    w["avwap_low"], "avwap_low")
    card.add_signal("52H zirve veya yılbaşı AVWAP üstünde",
                    None if (v_avwap_high is None and v_avwap_ytd is None) else float(above_avwap_high or above_avwap_ytd),
                    w["avwap_high_ytd"], "avwap_high_ytd")
    vcp_sig = None if vcp_ratio is None else (1.0 if vcp_tight else 0.5 if vcp_ratio <= 1.0 else 0.0)
    card.add_signal("Volatilite daralması (VCP)", vcp_sig, w["vcp"], "vcp", f"{vcp_ratio}x" if vcp_ratio else None)
    vol_ok = (rvol is not None and rvol >= 1.3 and daily_change_pct > 0) or (
        vol_dryup_ratio is not None and vol_dryup_ratio <= 0.85 and abs(daily_change_pct) < 2.0)
    card.add_signal("Hacim teyidi", None if rvol is None else (1.0 if vol_ok else 0.5), w["volume"], "volume")

    regime = None
    if bench_regime["above_sma50"] is not None:
        both = bench_regime["above_sma50"] and bench_regime["above_sma200"]
        one = bench_regime["above_sma50"] or bench_regime["above_sma200"]
        regime = 1.0 if both else 0.5 if one else 0.0
    card.add_signal(f"Piyasa rejimi ({bundle['benchmark_name']})", regime, w["regime"], "regime",
                    bench_regime["status"])
    if is_bist and usd_analysis:
        u50, u200 = usd_analysis["above_sma50_usd"], usd_analysis["above_sma200_usd"]
        card.add_signal("USD bazlı trend teyidi", 1.0 if (u50 and u200) else 0.5 if (u50 or u200) else 0.0,
                        w["confirm"], "confirm")
    else:
        conf = None if bench_regime["above_sma200"] is None else (1.0 if bench_regime["above_sma200"] else 0.4)
        card.add_signal("Endeks 200 günlük ortalama üstünde", conf, w["confirm"], "confirm")

    rsi_sig = None
    if v_rsi is not None:
        rsi_sig = 1.0 if 48 <= v_rsi <= 72 else 0.6 if (40 <= v_rsi < 48 or 72 < v_rsi <= 78) else 0.3 if v_rsi > 78 else 0.0
    card.add_signal("RSI(14) sağlıklı bölgede", rsi_sig, w["rsi"], "rsi", f"{v_rsi}" if v_rsi is not None else None)
    macd_sig = None if v_macd is None else (1.0 if (macd_bullish and (v_sma200 is None or last_close > v_sma200))
                                            else 0.5 if macd_bullish else 0.0)
    card.add_signal("MACD pozitif (trend filtreli)", macd_sig, w["macd"], "macd")
    ext_sig = None
    if ext_from_sma50_pct is not None:
        e = ext_from_sma50_pct
        ext_sig = 1.0 if -3.0 <= e <= 18.0 else 0.5 if 18.0 < e <= 30.0 else 0.4 if -10.0 <= e < -3.0 else 0.0
    card.add_signal("50 SMA'ya göre makul uzaklık", ext_sig, w["extension"], "extension",
                    f"{ext_from_sma50_pct:+.1f}%" if ext_from_sma50_pct is not None else None)

    tech_score = card.score() or 0
    tech_breakdown = card.breakdown()

    # Kontrol listesi (Raporumuzdaki 9 maddelik ozet kart)
    checklist = [
        {
            "label": f"Piyasa Rejimi ({bundle['benchmark_name']})",
            "status": "pass" if (bench_regime["above_sma50"] and bench_regime["above_sma200"]) else ("warn" if (bench_regime["above_sma50"] or bench_regime["above_sma200"]) else "fail"),
            "value": bench_regime["status"],
        },
        {
            "label": "Weinstein Haftalık Evre (30W SMA)",
            "status": "pass" if stage == 2 else ("warn" if stage in (1, 3) else "fail"),
            "value": stage_label,
        },
        {
            "label": "Minervini 8'li Trend Şablonu",
            "status": "pass" if minervini_passed >= 7 else ("warn" if minervini_passed >= 5 else "fail"),
            "value": f"{minervini_passed}/8 kriter sağlandı",
        },
        {
            "label": "Göreceli Güç (RS vs Endeks)",
            "status": "pass" if (rs_est is not None and rs_est >= 70) else ("warn" if (rs_est is not None and rs_est >= 45) else "fail"),
            "value": f"RS ~{rs_est} ({rs_info['label']})" if rs_est is not None else "Veri yok",
        },
        {
            "label": "Kurumsal Maliyet (Anchored VWAP)",
            "status": "pass" if (above_avwap_low and above_avwap_ytd) else ("warn" if above_avwap_low else "fail"),
            "value": f"Dip AVWAP: {v_avwap_low} | Yılbaşı: {v_avwap_ytd}",
        },
        {
            "label": "Volatilite Daralması (VCP) & Hacim",
            "status": "pass" if vcp_tight else ("warn" if (vcp_ratio is not None and vcp_ratio <= 1.05) else "fail"),
            "value": f"Daralma: {vcp_ratio}x | RVOL: {rvol}x" if vcp_ratio else f"RVOL: {rvol}x",
        },
        {
            "label": "50 SMA'dan Uzama (Kovalama Riski)",
            "status": "pass" if (ext_from_sma50_pct is not None and -2 <= ext_from_sma50_pct <= 18) else ("warn" if (ext_from_sma50_pct is not None and ext_from_sma50_pct <= 28) else "fail"),
            "value": f"{ext_from_sma50_pct:+.1f}%" if ext_from_sma50_pct is not None else "Veri yok",
        },
        {
            "label": "Momentum (RSI & MACD — Trend Filtreli)",
            "status": "pass" if (v_rsi is not None and 48 <= v_rsi <= 72 and macd_bullish) else ("warn" if (v_rsi is not None and v_rsi >= 40) else "fail"),
            "value": f"RSI: {v_rsi} | MACD: {'Pozitif' if macd_bullish else 'Negatif'}",
        },
    ]
    if is_bist and usd_analysis:
        checklist.insert(
            3,
            {
                "label": "BIST USD Bazlı Trend Doğrulaması",
                "status": "pass" if (usd_analysis["above_sma50_usd"] and usd_analysis["above_sma200_usd"]) else ("warn" if (usd_analysis["above_sma50_usd"] or usd_analysis["above_sma200_usd"]) else "fail"),
                "value": f"${usd_analysis['price_usd']} (50G: {'Üstü' if usd_analysis['above_sma50_usd'] else 'Altı'}, 200G: {'Üstü' if usd_analysis['above_sma200_usd'] else 'Altı'})",
            },
        )

    # Teknik bayraklar
    flags_good = []
    flags_warn = []
    if minervini_passed == 8:
        flags_good.append("Minervini 8/8 Trend Şablonu tam sağlanıyor (güçlü yükseliş yapısı).")
    elif minervini_passed <= 3:
        flags_warn.append(f"Minervini Trend Şablonu zayıf ({minervini_passed}/8) — ana trend düşüş veya dağınık.")
    if stage == 2:
        flags_good.append("Haftalık 30W SMA üzerinde Evre 2 yükseliş trendinde.")
    elif stage == 4:
        flags_warn.append("Weinstein Evre 4 (düşüş trendi) — dip avcılığı riskli.")
    if rs_est is not None and rs_est >= 80:
        flags_good.append(f"Endeksten belirgin pozitif ayrışan lider hisse (RS ~{rs_est}).")
    elif rs_est is not None and rs_est < 35:
        flags_warn.append(f"Endeksin gerisinde kalan zayıf göreceli güç (RS ~{rs_est}).")
    if vcp_tight:
        flags_good.append(f"Zirveye yakın volatilite daralması (VCP oranı: {vcp_ratio}x) — kırılım izlenebilir.")
    if ext_from_sma50_pct is not None and ext_from_sma50_pct > 25:
        flags_warn.append(f"50 günlük ortalamadan +{ext_from_sma50_pct:.1f}% uzamış — kovalama/düzeltme riski yüksek.")
    if v_rsi is not None and v_rsi > 78:
        flags_warn.append(f"RSI ({v_rsi}) aşırı ısınmış bölgede; kısa vadeli geri çekilme ihtimali artıyor.")
    if is_bist and usd_analysis and not usd_analysis["above_sma200_usd"] and (v_sma200 and last_close > v_sma200):
        flags_warn.append("TL grafikte 200 SMA üstünde olsa da USD bazlı grafikte 200 SMA altında (enflasyon yanılsaması riski).")

    return {
        "score": tech_score,
        "score_breakdown": tech_breakdown,
        "backtest_evidence": BACKTEST_EVIDENCE["bist" if is_bist else "us"],
        "price": _safe(last_close, 4),
        "prev_close": _safe(prev_close, 4),
        "daily_change_pct": _safe(daily_change_pct, 2),
        "last_date": df.index[-1].strftime("%Y-%m-%d"),
        "returns": {"1m": ret_1m, "3m": ret_3m, "6m": ret_6m, "1y": ret_1y},
        "moving_averages": {
            "sma10": v_sma10,
            "sma20": v_sma20,
            "sma50": v_sma50,
            "sma150": v_sma150,
            "sma200": v_sma200,
            "w_sma30": w_sma30_val,
            "ext_sma20_pct": _safe(ext_from_sma20_pct, 2),
            "ext_sma50_pct": _safe(ext_from_sma50_pct, 2),
        },
        "range_52w": {
            "high": _safe(high_52w, 4),
            "low": _safe(low_52w, 4),
            "dist_high_pct": _safe(dist_from_high_pct, 2),
            "dist_low_pct": _safe(dist_from_low_pct, 2),
        },
        "minervini": {
            "passed": minervini_passed,
            "total": 8,
            "checks": minervini_checks,
        },
        "weinstein": {
            "stage": stage,
            "label": stage_label,
            "description": stage_desc,
            "w_sma30": w_sma30_val,
        },
        "relative_strength": rs_info,
        "benchmark_regime": bench_regime,
        "volatility_risk": {
            "atr14": v_atr14,
            "atr_pct": atr_pct,
            "adr20_pct": adr20,
            "adr10_pct": adr10,
            "vcp_ratio": vcp_ratio,
            "vcp_tight": vcp_tight,
            "rvol": rvol,
            "vol_dryup_ratio": vol_dryup_ratio,
            "avg_volume_20d": _safe(vol_avg20, 0),
            "avg_turnover_20d": avg_turnover_20d,
            "stop_1adr": stop_1adr,
            "stop_15atr": stop_15atr,
            "stop_2atr": stop_2atr,
        },
        "avwap": {
            "low_52w": v_avwap_low,
            "low_52w_date": low_52w_date.strftime("%Y-%m-%d"),
            "high_52w": v_avwap_high,
            "high_52w_date": high_52w_date.strftime("%Y-%m-%d"),
            "ytd": v_avwap_ytd,
            "above_low": above_avwap_low,
            "above_high": above_avwap_high,
            "above_ytd": above_avwap_ytd,
        },
        "oscillators": {
            "rsi14": v_rsi,
            "macd": v_macd,
            "macd_signal": v_sig,
            "macd_hist": v_hist,
            "macd_bullish": macd_bullish,
        },
        "usd_analysis": usd_analysis,
        "checklist": checklist,
        "flags_good": flags_good,
        "flags_warn": flags_warn,
        "charts": {
            "primary": chart_primary,
            "usd": chart_usd,
        },
    }
