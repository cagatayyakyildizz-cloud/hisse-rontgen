from __future__ import annotations

import logging
from typing import Any

from .data_fetcher import fetch_stock_bundle
from .fundamental import analyze_fundamental
from .market_info import analyst_view, earnings_info, financing_risk
from .reference_data import theme_of
from . import storage

log = logging.getLogger("hisse_rontgen")
from .technical import analyze_technical


def _build_verdict(tech_score: int, fund_score: int, tech: dict[str, Any], fund: dict[str, Any]) -> dict[str, Any]:
    """
    4-Kadran Tekno-Temel Karar Matrisi:
      - Guclu Tekno-Temel Aday: Bilanco >= 65 ve Teknik >= 65
      - Bilanco Saglam, Teknik Bekle: Bilanco >= 65 ve Teknik < 65
      - Spekulatif / Momentum: Teknik >= 65 ve Bilanco < 65
      - Zayif / Uzak Dur: Ikisi de < 65
    """
    composite = int(round(tech_score * 0.45 + fund_score * 0.55))

    if fund_score >= 65 and tech_score >= 65:
        quadrant = "strong_candidate"
        badge = "Güçlü Tekno-Temel Aday"
        tone = "positive"
        summary = (
            "Hem bilanço kalitesi hem de teknik trend yapısı güçlü bölgede örtüşüyor. "
            "Yüksek olasılıklı takip listesi adayı; giriş için 50 günlük ortalamadan aşırı uzama olup olmadığı "
            "ve ATR/ADR stop mesafesi kontrol edilmelidir."
        )
    elif fund_score >= 65 and tech_score < 65:
        quadrant = "watch_technical"
        badge = "Bilanço Sağlam — Teknik Olgunlaşma Bekle"
        tone = "info"
        summary = (
            "Şirketin finansal temelleri ve nakit/kârlılık profili güçlü görünüyor; ancak teknik yapı henüz "
            "net Evre 2 yükseliş teyidi vermiyor. Dip tahmin etmek yerine 30 haftalık / 50 günlük ortalama üzerine "
            "hacimli geçiş veya AVWAP toparlanması beklenebilir."
        )
    elif fund_score < 65 and tech_score >= 65:
        quadrant = "momentum_only"
        badge = "Teknik Güçlü — Bilanço Dikkat İstiyor"
        tone = "warning"
        summary = (
            "Fiyat momentumu ve trend yapısı güçlü; ancak bilanço rasyolarında değerleme, borçluluk veya nakit "
            "kalitesi açısından zayıf noktalar var. Uzun vadeli tutmaktan ziyade sıkı stop-loss (≤ 1 ADR / 10–20 MA) "
            "disipliniyle momentum odaklı izlenmelidir."
        )
    else:
        quadrant = "avoid"
        badge = "Zayıf Görünüm — Temkinli / Uzak Dur"
        tone = "negative"
        summary = (
            "Hem bilanço metrikleri hem de teknik trend yapısı zayıf puan alıyor. "
            "Yüksek riskli bölge; kurumsal birikim (Evre 1→2 geçişi) ve kârlılık/nakit akışı iyileşmesi görülmeden "
            "sermaye bağlamak risklidir."
        )

    # Kisa dinamik cumle ekleri
    stage = tech["weinstein"]["stage"]
    min_p = tech["minervini"]["passed"]
    pio = fund["scores"]["piotroski"]["score"]
    pio_av = fund["scores"]["piotroski"]["available"]
    highlights = []
    highlights.append(f"Weinstein Evresi: {tech['weinstein']['label']}")
    highlights.append(f"Minervini Şablonu: {min_p}/8")
    if tech["relative_strength"]["rs_score_est"] is not None:
        highlights.append(f"RS Tahmini (endekse göre): ~{tech['relative_strength']['rs_score_est']}")
    if fund.get("data_coverage_pct") is not None and fund["data_coverage_pct"] < 100:
        highlights.append(f"Bilanço veri kapsamı: %{fund['data_coverage_pct']}")
    if pio is not None:
        highlights.append(f"Piotroski F-Score: {pio}/{pio_av}")
    if fund["valuation"]["ev_ebitda"] is not None:
        highlights.append(f"FD/FAVÖK: {fund['valuation']['ev_ebitda']}x")
    elif fund["valuation"]["pe"] is not None:
        highlights.append(f"F/K: {fund['valuation']['pe']}x")

    return {
        "composite_score": composite,
        "quadrant": quadrant,
        "badge": badge,
        "tone": tone,
        "summary": summary,
        "highlights": highlights,
        "stage": stage,
    }


def analyze_stock(raw_symbol: str, market: str = "auto", force_refresh: bool = False, include_charts: bool = True) -> dict[str, Any]:
    bundle = fetch_stock_bundle(raw_symbol, market=market, force_refresh=force_refresh)
    tech = analyze_technical(bundle, include_charts=include_charts)
    peer_group = _peer_group(bundle)
    peers = None
    try:
        metrics, count = storage.peer_metrics(peer_group, exclude=bundle["symbol"])
        peers = {"group": peer_group, "count": count, "metrics": metrics}
    except Exception as exc:  # veritabani sorunu analizi durdurmasin
        log.warning("Sektor ici kiyas verisi okunamadi: %s", exc)
    fund = analyze_fundamental(bundle, peers=peers)
    verdict = _build_verdict(tech["score"], fund["score"], tech, fund)
    earnings = earnings_info(bundle)
    financing = financing_risk(bundle, fund)
    analysts = analyst_view(bundle, tech.get("price"))
    if earnings.get("warning"):
        verdict["highlights"].insert(0, f"⚠ Bilanço {earnings['days_until']} gün içinde")
        fund["flags_warn"].insert(0, earnings["warning"])
    for msg in financing["flags"]:
        fund["flags_warn"].append(msg)
    if financing["level"] == "high":
        verdict["highlights"].append("Finansman riski: Yüksek")

    info = bundle["info"]
    company_name = info.get("longName") or info.get("shortName") or bundle["display_symbol"]

    history: list[dict[str, Any]] = []
    try:
        storage.record_scores(bundle["symbol"], verdict["composite_score"], tech["score"], fund["score"],
                              tech["weinstein"]["stage"], tech.get("price"), fund.get("data_coverage_pct"))
        own = fund.get("peer_metrics_own") or {}
        storage.save_snapshot(bundle["symbol"], "bist" if bundle["is_bist"] else "us", peer_group,
                              fund["sector"], fund["industry"], own)
        history = storage.score_history(bundle["symbol"], limit=365)
    except Exception as exc:
        log.warning("Puan gecmisi kaydedilemedi: %s", exc)

    if not include_charts:
        tech_out = {k: v for k, v in tech.items() if k != "charts"}
    else:
        tech_out = tech

    return {
        "meta": {
            "symbol": bundle["symbol"],
            "display_symbol": bundle["display_symbol"],
            "name": company_name,
            "is_bist": bundle["is_bist"],
            "market_label": "BIST" if bundle["is_bist"] else (info.get("exchange") or "ABD / Global"),
            "currency": bundle["currency"],
            "currency_major": bundle.get("currency_major", bundle["currency"]),
            "financial_currency": bundle["financial_currency"],
            "sector": fund["sector"],
            "industry": fund["industry"],
            "fetched_at": bundle["fetched_at"],
        },
        "verdict": verdict,
        "technical": tech_out,
        "fundamental": fund,
        "earnings": earnings,
        "financing": financing,
        "analysts": analysts,
        "score_history": history,
    }


def _peer_group(bundle: dict[str, Any]) -> str:
    """Kiyas grubu: hisse bir temadaysa tema, degilse piyasa + Yahoo endustrisi."""
    found = theme_of(bundle["symbol"])
    if found:
        return f"{found[0]}:{found[1]}"
    market = "bist" if bundle["is_bist"] else "us"
    return f"{market}:{(bundle.get('info') or {}).get('industry') or 'Bilinmiyor'}"


def build_summary_row(raw_symbol: str, market: str = "auto") -> dict[str, Any]:
    """Izleme listesi ve coklu kiyaslama tablosu icin hafifletilmis ozet."""
    res = analyze_stock(raw_symbol, market=market, include_charts=False)
    m = res["meta"]
    v = res["verdict"]
    t = res["technical"]
    f = res["fundamental"]
    return {
        "symbol": m["symbol"],
        "display_symbol": m["display_symbol"],
        "name": m["name"],
        "is_bist": m["is_bist"],
        "market_label": m["market_label"],
        "currency": m["currency"],
        "price": t["price"],
        "daily_change_pct": t["daily_change_pct"],
        "ret_1y": t["returns"]["1y"],
        "composite_score": v["composite_score"],
        "tech_score": t["score"],
        "fund_score": f["score"],
        "fund_coverage_pct": f.get("data_coverage_pct"),
        "badge": v["badge"],
        "tone": v["tone"],
        "stage": t["weinstein"]["stage"],
        "minervini": f"{t['minervini']['passed']}/8",
        "rs": t["relative_strength"]["rs_score_est"],
        "piotroski": f"{f['scores']['piotroski']['score']}/{f['scores']['piotroski']['available']}" if f["scores"]["piotroski"]["score"] is not None else "—",
        "roic_pct": f["profitability"]["roic_pct"],
        "roe_pct": f["profitability"]["roe_pct"],
        "pe": f["valuation"]["pe"],
        "ev_ebitda": f["valuation"]["ev_ebitda"],
        "net_debt_ebitda": f["balance_health"]["net_debt_to_ebitda"],
        "adr20_pct": t["volatility_risk"]["adr20_pct"],
        "next_earnings": res["earnings"]["next_date"],
        "earnings_days": res["earnings"]["days_until"],
        "financing_risk": res["financing"]["level"],
        "analyst_target_mean": (res["analysts"] or {}).get("target_mean"),
        "analyst_upside_pct": (res["analysts"] or {}).get("upside_mean_pct"),
    }
