"""
Pozisyon boyutu hesaplayicisi (sabit risk yontemi).

Adet = (Sermaye x Risk %) / (Giris - Stop), lot buyuklugune asagi yuvarlanir ve sermayenin
izin verilen payini asmayacak sekilde sinirlanir. 2R / 3R kar al seviyeleri ve likidite uyarisi uretir.
Yalnizca uzun (alis) pozisyonlar icindir; komisyon ve kayma dahil degildir.
"""
from __future__ import annotations

import math
from typing import Any

MAX_RISK_PCT = 10.0          # tek islemde izin verilen en yuksek risk yuzdesi
TIGHT_STOP_PCT = 1.0         # bundan yakin stop gun ici gurultuyle tetiklenebilir
WIDE_STOP_PCT = 15.0         # bundan genis stop cok buyuk zarar payi demektir
ADV_WARN_PCT = 1.0           # pozisyon, 20 gunluk ortalama islem hacminin bu yuzdesini asarsa kayma uyarisi
ADV_DANGER_PCT = 5.0


class PositionError(ValueError):
    pass


def plan_position(entry: float, stop: float, capital: float, risk_pct: float, lot_size: int = 1,
                  max_position_pct: float = 100.0, avg_turnover: float | None = None,
                  r_multiples: tuple[float, ...] = (2.0, 3.0)) -> dict[str, Any]:
    if not entry or entry <= 0:
        raise PositionError("Giriş fiyatı pozitif olmalı.")
    if stop is None or stop <= 0 or stop >= entry:
        raise PositionError("Stop, giriş fiyatının altında ve pozitif olmalı (yalnızca alış pozisyonu).")
    if not capital or capital <= 0:
        raise PositionError("Sermaye pozitif olmalı.")
    if not risk_pct or risk_pct <= 0 or risk_pct > MAX_RISK_PCT:
        raise PositionError(f"Risk yüzdesi 0 ile %{MAX_RISK_PCT:g} arasında olmalı.")
    lot = max(1, int(lot_size or 1))
    max_position_pct = min(max(max_position_pct or 100.0, 1.0), 100.0)

    risk_per_share = entry - stop
    risk_budget = capital * risk_pct / 100.0
    by_risk = math.floor(risk_budget / risk_per_share / lot) * lot
    by_capital = math.floor(capital * max_position_pct / 100.0 / entry / lot) * lot
    shares = max(0, min(by_risk, by_capital))
    limited_by = "risk" if by_risk <= by_capital else "capital"

    value = shares * entry
    max_loss = shares * risk_per_share
    stop_pct = risk_per_share / entry * 100.0
    warnings: list[str] = []
    if shares == 0:
        warnings.append("Risk bütçesi bu stop mesafesinde bir lot almaya yetmiyor; riski artırın veya stopu yaklaştırın.")
    if limited_by == "capital" and shares > 0:
        warnings.append(f"Pozisyon sermaye sınırına (%{max_position_pct:g}) takıldı; gerçek risk "
                        f"%{max_loss / capital * 100:.2f} (hedef %{risk_pct:g}).")
    if stop_pct < TIGHT_STOP_PCT:
        warnings.append(f"Stop çok yakın (%{stop_pct:.2f}); gün içi dalgalanmayla tetiklenebilir.")
    elif stop_pct > WIDE_STOP_PCT:
        warnings.append(f"Stop çok uzak (%{stop_pct:.1f}); fiyat stopa giderse kayıp büyük olur.")
    adv_pct = None
    if avg_turnover and avg_turnover > 0 and value > 0:
        adv_pct = value / avg_turnover * 100.0
        if adv_pct > ADV_DANGER_PCT:
            warnings.append(f"Pozisyon, günlük ortalama işlem hacminin %{adv_pct:.1f}'i: girip çıkarken ciddi kayma olur.")
        elif adv_pct > ADV_WARN_PCT:
            warnings.append(f"Pozisyon, günlük ortalama işlem hacminin %{adv_pct:.1f}'i: emirleri bölmek gerekebilir.")

    targets = [{"r": r, "price": round(entry + r * risk_per_share, 4),
                "gain": round(shares * r * risk_per_share, 2),
                "pct": round(r * stop_pct, 2)} for r in r_multiples]
    return {
        "entry": entry,
        "stop": stop,
        "shares": int(shares),
        "lot_size": lot,
        "position_value": round(value, 2),
        "position_pct_of_capital": round(value / capital * 100.0, 2),
        "risk_per_share": round(risk_per_share, 4),
        "stop_distance_pct": round(stop_pct, 2),
        "risk_budget": round(risk_budget, 2),
        "max_loss": round(max_loss, 2),
        "actual_risk_pct": round(max_loss / capital * 100.0, 3),
        "limited_by": limited_by,
        "targets": targets,
        "adv_pct": round(adv_pct, 2) if adv_pct is not None else None,
        "warnings": warnings,
        "note": "Komisyon, vergi ve kayma dahil değildir. Yalnızca alış (long) pozisyonu için.",
    }


def stop_options(price: float | None, tech: dict[str, Any]) -> list[dict[str, Any]]:
    """Analizdeki yapisal stop seviyelerinden fiyatin ALTINDA kalanlar."""
    if not price:
        return []
    vr, ma, av = tech.get("volatility_risk", {}), tech.get("moving_averages", {}), tech.get("avwap", {})
    cands = [
        ("adr1", "1 ADR (ortalama günlük aralık)", vr.get("stop_1adr")),
        ("atr15", "1.5 × ATR", vr.get("stop_15atr")),
        ("atr2", "2 × ATR", vr.get("stop_2atr")),
        ("sma50", "50 günlük ortalama", ma.get("sma50")),
        ("avwap_low", "52H dip AVWAP", av.get("low_52w")),
    ]
    out = []
    for key, label, val in cands:
        if val and 0 < val < price:
            out.append({"key": key, "label": label, "price": round(float(val), 4),
                        "distance_pct": round((price - val) / price * 100.0, 2)})
    return out
