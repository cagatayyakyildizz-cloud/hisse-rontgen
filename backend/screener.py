"""
Super Tarayici: tekno-temel puanlar + para akisi kesisimi.

Veri kaynagi: her analizde (ve arka plan gorevinin gunluk taramasinda) kaydedilen ozet satirlar
(storage.screen_rows) + para akisi motorunun haftalik/aylik akis skorlari. Tarama Yahoo'ya yeni
analiz istegi atmaz; bu yuzden hizlidir. Satirlar en fazla SCREEN_MAX_AGE_DAYS gun eski olabilir.

Her hazir filtrenin gecmis performansi `tools/backtest_tarayici.py` ile olculur ve
`backend/data/screen_backtest.json` dosyasindan arayuze tasinir. Bilanco kosullari gecmise donuk
test edilemez (Yahoo point-in-time bilanco vermez); bu durumda yalnizca teknik/akis kosullari test edilir.
"""
from __future__ import annotations

import json
import operator
from pathlib import Path
from typing import Any, Callable

from . import storage
from .reference_data import themes

SCREEN_MAX_AGE_DAYS = 3
EVIDENCE_FILE = Path(__file__).resolve().parent / "data" / "screen_backtest.json"

OPS: dict[str, Callable[[Any, Any], bool]] = {
    ">=": operator.ge, "<=": operator.le, ">": operator.gt, "<": operator.lt, "==": operator.eq,
}

# kind: "tech" / "flow" -> gecmise donuk test edilebilir; "fund" -> edilemez
PRESETS: list[dict[str, Any]] = [
    {
        "key": "altin_kesisim",
        "name": "Altın Kesişim",
        "description": "Bilanço ve teknik güçlü, haftalık para girişi var.",
        "conditions": [
            {"field": "fund_score", "op": ">=", "value": 65, "label": "Bilanço ≥ 65", "kind": "fund"},
            {"field": "tech_score", "op": ">=", "value": 65, "label": "Teknik ≥ 65", "kind": "tech"},
            {"field": "flow_1w", "op": ">=", "value": 15, "label": "Haftalık akış ≥ +15", "kind": "flow"},
        ],
    },
    {
        "key": "rs_liderleri",
        "name": "Göreli Güç Liderleri",
        "description": "Geriye dönük testte en tutarlı çalışan kalemler: yüksek RS, yükselen RS çizgisi, dip AVWAP üstü.",
        "conditions": [
            {"field": "rs", "op": ">=", "value": 80, "label": "RS tahmini ≥ 80", "kind": "tech"},
            {"field": "rs_above_sma50", "op": "==", "value": True, "label": "RS çizgisi 50G ort. üstünde", "kind": "tech"},
            {"field": "above_avwap_low", "op": "==", "value": True, "label": "52H dip AVWAP üstünde", "kind": "tech"},
        ],
    },
    {
        "key": "erken_rotasyon",
        "name": "Erken Rotasyon",
        "description": "Aylık akış negatifken haftalık güçlü para girişi başlamış, bilançosu sağlam şirketler.",
        "conditions": [
            {"field": "flow_1m", "op": "<", "value": 0, "label": "Aylık akış < 0", "kind": "flow"},
            {"field": "flow_1w", "op": ">=", "value": 25, "label": "Haftalık akış ≥ +25", "kind": "flow"},
            {"field": "fund_score", "op": ">=", "value": 65, "label": "Bilanço ≥ 65", "kind": "fund"},
        ],
    },
    {
        "key": "kaliteli_ucuz",
        "name": "Kaliteli ve Görece Ucuz",
        "description": "Yüksek sermaye getirisi, güçlü nakit dönüşümü, düşük borç; sektör içinde ucuz yarıda. Döngüsel zirvedekiler hariç.",
        "conditions": [
            {"field": "roic_pct", "op": ">=", "value": 15, "label": "ROIC ≥ %15", "kind": "fund"},
            {"field": "piotroski_score", "op": ">=", "value": 7, "label": "Piotroski ≥ 7", "kind": "fund"},
            {"field": "ocf_to_ni", "op": ">=", "value": 0.9, "label": "OCF / Net kâr ≥ 0.9", "kind": "fund"},
            {"field": "leverage_ok", "op": "==", "value": True, "label": "Net nakit veya Net borç/FAVÖK < 2", "kind": "fund"},
            {"field": "peer_value_pct", "op": ">=", "value": 50, "label": "Sektör içi değerleme sırası ≥ %50", "kind": "fund"},
            {"field": "peak_margin", "op": "==", "value": False, "label": "Döngüsel zirve kâr değil", "kind": "fund"},
        ],
    },
    {
        "key": "vcp_kirilim",
        "name": "VCP Kırılım Adayları",
        "description": "Trend şablonu güçlü, volatilite daralıyor, zirveye yakın. Dikkat: VCP kalemi geriye dönük testte zayıf çıktı.",
        "conditions": [
            {"field": "minervini_passed", "op": ">=", "value": 7, "label": "Minervini ≥ 7/8", "kind": "tech"},
            {"field": "vcp_ratio", "op": "<=", "value": 0.82, "label": "VCP daralma ≤ 0.82", "kind": "tech"},
            {"field": "dist_high_pct", "op": ">=", "value": -15, "label": "Zirveye en fazla %15 uzak", "kind": "tech"},
        ],
    },
]
PRESET_BY_KEY = {p["key"]: p for p in PRESETS}


def load_evidence() -> dict[str, Any]:
    try:
        return json.loads(EVIDENCE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _derive(row: dict[str, Any]) -> dict[str, Any]:
    r = dict(row)
    nd, nde = r.get("net_debt"), r.get("net_debt_ebitda")
    r["leverage_ok"] = (nd is not None and nd < 0) or (nde is not None and nde < 2)
    return r


def check(row: dict[str, Any], cond: dict[str, Any]) -> bool | None:
    """True/False; alan verisi yoksa None (kosul degerlendirilemedi)."""
    val = row.get(cond["field"])
    if val is None:
        return None
    try:
        return bool(OPS[cond["op"]](val, cond["value"]))
    except TypeError:
        return None


def custom_preset(min_composite: float | None, min_tech: float | None, min_fund: float | None,
                  min_flow_1w: float | None) -> dict[str, Any]:
    conds = []
    for field, val, label, kind in (("composite_score", min_composite, "Bileşik", "fund"),
                                    ("tech_score", min_tech, "Teknik", "tech"),
                                    ("fund_score", min_fund, "Bilanço", "fund"),
                                    ("flow_1w", min_flow_1w, "Haftalık akış", "flow")):
        if val is not None:
            conds.append({"field": field, "op": ">=", "value": val, "label": f"{label} ≥ {val:g}", "kind": kind})
    return {"key": "ozel", "name": "Özel Filtre", "description": "Kendi eşiklerin.", "conditions": conds}


def run_scan(market: str, preset: dict[str, Any], flow: dict[str, Any] | None) -> dict[str, Any]:
    rows = [_derive(r) for r in storage.latest_screen_rows(market, SCREEN_MAX_AGE_DAYS)]
    flow_by_sym: dict[str, dict[str, Any]] = {}
    if flow:
        for s in flow.get("stocks", []):
            flow_by_sym[s["symbol"].upper()] = s
    for r in rows:
        fs = flow_by_sym.get(r["symbol"].upper())
        r["flow_1w"] = fs["periods"]["1w"]["flow_score"] if fs else None
        r["flow_1m"] = fs["periods"]["1m"]["flow_score"] if fs else None

    matches, undecided = [], 0
    for r in rows:
        results = [check(r, c) for c in preset["conditions"]]
        if all(x is True for x in results) and results:
            r["matched"] = [c["label"] for c in preset["conditions"]]
            matches.append(r)
        elif any(x is None for x in results) and not any(x is False for x in results):
            undecided += 1
    matches.sort(key=lambda r: (r.get("composite_score") or 0), reverse=True)

    universe = sum(len(v) for v in themes(market).values())
    evidence = load_evidence().get(preset["key"], {}).get(market)
    dates = sorted({r["_date"] for r in rows})
    return {
        "market": market,
        "preset": {k: v for k, v in preset.items()},
        "matches": matches,
        "scanned": len(rows),
        "universe": universe,
        "undecided": undecided,
        "data_dates": [dates[0], dates[-1]] if dates else None,
        "flow_available": bool(flow_by_sym),
        "evidence": evidence,
        "note": ("Tarama, kaydedilmiş günlük analiz özetlerinden yapılır. Eksik hisseler için kıyas verisini "
                 "yenileyin (arka plan görevi günde bir kez tüm tema hisselerini analiz eder)."),
    }
