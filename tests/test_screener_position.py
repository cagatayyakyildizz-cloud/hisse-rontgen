"""Super Tarayici ve pozisyon boyutu."""
import pytest

from backend import screener, storage
from backend.position import PositionError, plan_position, stop_options


# --------------------------------------------------------------- pozisyon boyutu

def test_position_size_by_risk():
    p = plan_position(entry=100.0, stop=95.0, capital=200_000, risk_pct=1.0)
    # risk butcesi 2000, hisse basi risk 5 -> 400 adet
    assert p["shares"] == 400 and p["limited_by"] == "risk"
    assert p["max_loss"] == 2000 and p["position_value"] == 40_000
    assert [t["price"] for t in p["targets"]] == [110.0, 115.0]


def test_position_limited_by_capital_and_lot_rounding():
    p = plan_position(entry=100.0, stop=99.5, capital=10_000, risk_pct=1.0, max_position_pct=25, lot_size=10)
    # riskle 200 adet olurdu; sermayenin %25'i 2500 -> 25 adet -> 10'luk lota yuvarla -> 20
    assert p["shares"] == 20 and p["limited_by"] == "capital"
    assert any("sermaye sınırına" in w for w in p["warnings"])
    assert any("Stop çok yakın" in w for w in p["warnings"])


def test_position_liquidity_warning_and_zero_shares():
    p = plan_position(entry=10.0, stop=9.0, capital=1_000_000, risk_pct=2.0, avg_turnover=1_000_000)
    assert any("işlem hacminin" in w for w in p["warnings"])
    tiny = plan_position(entry=1000.0, stop=500.0, capital=1000, risk_pct=0.5)
    assert tiny["shares"] == 0 and tiny["warnings"]


@pytest.mark.parametrize("kw", [dict(stop=105.0), dict(stop=0.0), dict(capital=0), dict(risk_pct=15)])
def test_position_rejects_bad_input(kw):
    args = dict(entry=100.0, stop=95.0, capital=1000.0, risk_pct=1.0)
    args.update(kw)
    with pytest.raises(PositionError):
        plan_position(**args)


def test_stop_options_only_below_price():
    tech = {"volatility_risk": {"stop_1adr": 96.0, "stop_15atr": 94.0, "stop_2atr": 92.0},
            "moving_averages": {"sma50": 105.0}, "avwap": {"low_52w": 80.0}}
    keys = [o["key"] for o in stop_options(100.0, tech)]
    assert keys == ["adr1", "atr15", "atr2", "avwap_low"]  # 50 SMA fiyatin ustunde -> stop olamaz


# --------------------------------------------------------------- tarayici

def _row(sym, **kw):
    base = {"symbol": sym, "display_symbol": sym, "composite_score": 70, "tech_score": 70, "fund_score": 70,
            "rs": 85, "rs_above_sma50": True, "above_avwap_low": True, "roic_pct": 20, "piotroski_score": 8,
            "ocf_to_ni": 1.1, "net_debt": -5, "net_debt_ebitda": -0.5, "peer_value_pct": 60, "peak_margin": False,
            "minervini_passed": 8, "vcp_ratio": 0.7, "dist_high_pct": -5}
    base.update(kw)
    return base


def _flow(**scores):
    return {"stocks": [{"symbol": s, "periods": {"1w": {"flow_score": w}, "1m": {"flow_score": m}}}
                       for s, (w, m) in scores.items()]}


def test_scan_presets_and_flow_join():
    storage.save_screen_row("AAA", "us", _row("AAA"))
    storage.save_screen_row("BBB", "us", _row("BBB", fund_score=40, rs=50))
    storage.save_screen_row("CCC", "us", _row("CCC", tech_score=80))
    flow = _flow(AAA=(20, 5), BBB=(30, -10), CCC=(5, 5))

    gold = screener.run_scan("us", screener.PRESET_BY_KEY["altin_kesisim"], flow)
    assert [m["symbol"] for m in gold["matches"]] == ["AAA"]  # CCC haftalik akis 5 < 15
    rs = screener.run_scan("us", screener.PRESET_BY_KEY["rs_liderleri"], flow)
    assert {m["symbol"] for m in rs["matches"]} == {"AAA", "CCC"}
    early = screener.run_scan("us", screener.PRESET_BY_KEY["erken_rotasyon"], flow)
    assert early["matches"] == []  # BBB akis uygun ama bilanco 40
    quality = screener.run_scan("us", screener.PRESET_BY_KEY["kaliteli_ucuz"], flow)
    assert {m["symbol"] for m in quality["matches"]} == {"AAA", "BBB", "CCC"}
    assert gold["scanned"] == 3 and gold["flow_available"]


def test_scan_without_flow_marks_undecided():
    storage.save_screen_row("AAA", "bist", _row("AAA"))
    res = screener.run_scan("bist", screener.PRESET_BY_KEY["altin_kesisim"], None)
    assert res["matches"] == [] and res["undecided"] == 1 and not res["flow_available"]


def test_custom_preset():
    storage.save_screen_row("AAA", "us", _row("AAA", composite_score=55))
    storage.save_screen_row("BBB", "us", _row("BBB", composite_score=75))
    p = screener.custom_preset(min_composite=60, min_tech=None, min_fund=None, min_flow_1w=None)
    assert [m["symbol"] for m in screener.run_scan("us", p, None)["matches"]] == ["BBB"]


def test_every_preset_has_evidence_entry_or_is_untestable():
    ev = screener.load_evidence()
    for p in screener.PRESETS:
        testable = any(c["kind"] in ("tech", "flow") for c in p["conditions"])
        if ev:
            assert p["key"] in ev, p["key"]
            for market in ("us", "bist"):
                assert ev[p["key"]][market]["testable"] == testable
