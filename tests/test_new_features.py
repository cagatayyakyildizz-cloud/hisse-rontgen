"""Puan dokumu, analist/bilanco/finansman bilgisi, SEC cikarimi, kayit katmani ve uyarilar."""
import datetime as dt

import pandas as pd
import pytest

import backend.market_info as mi
from backend import scheduler, storage
from backend.fundamental import analyze_fundamental
from backend.scoring import ScoreCard
from backend.sec_data import extract
from tests.conftest import statement

YEARS = ["2025-12-31", "2024-12-31", "2023-12-31", "2022-12-31"]


# --------------------------------------------------------------- puan karti

def test_scorecard_excludes_missing_and_reports_breakdown():
    c = ScoreCard()
    c.add("A", 10, 10)
    c.add("B", None, 30)
    c.add_signal("C", 0.5, 10)
    assert c.score() == 75  # (10 + 5) / 20
    assert c.coverage == pytest.approx(20 / 50)
    assert c.missing == ["B"]
    bd = {i["label"]: i for i in c.breakdown()}
    assert bd["B"]["points"] is None and bd["A"]["contribution"] == 50.0


# --------------------------------------------------------------- analist / bilanco / finansman

def _bundle(**kw):
    base = {"is_bist": False, "currency": "USD", "currency_major": "USD", "info": {}, "calendar": {},
            "upgrades_downgrades": pd.DataFrame(), "quarterly_balance": pd.DataFrame(),
            "balance_sheet": pd.DataFrame(), "quarterly_cashflow": pd.DataFrame(), "cashflow": pd.DataFrame()}
    base.update(kw)
    return base


def test_analyst_view_us_and_bist(monkeypatch):
    monkeypatch.setattr(mi, "_today", lambda: dt.date(2026, 11, 23))
    ud = pd.DataFrame(
        {"Firm": ["UBS", "UBS", "Piper"], "ToGrade": ["Neutral", "Buy", "Neutral"], "FromGrade": ["Neutral", "", "Overweight"],
         "Action": ["main", "init", "down"], "currentPriceTarget": [43.0, 80.0, 54.0], "priorPriceTarget": [78.0, 0.0, 98.0]},
        index=pd.to_datetime(["2026-11-10", "2026-08-01", "2026-10-13"]))
    info = {"targetMeanPrice": 60.0, "targetMedianPrice": 50.0, "targetHighPrice": 100.0, "targetLowPrice": 40.0,
            "numberOfAnalystOpinions": 12, "recommendationKey": "buy"}
    a = mi.analyst_view(_bundle(info=info, upgrades_downgrades=ud), price=30.0)
    assert a["upside_mean_pct"] == 100.0 and a["recommendation"] == "Al"
    firms = [x["firm"] for x in a["recent_actions"]]
    assert firms == ["UBS", "Piper"], "her kurumun yalnizca en son islemi, yeniden eskiye"
    assert a["recent_actions"][0]["target"] == 43.0
    assert mi.analyst_view(_bundle(is_bist=True, info=info), price=30.0) is None


def test_earnings_warning_within_seven_days(monkeypatch):
    monkeypatch.setattr(mi, "_today", lambda: dt.date(2026, 11, 23))
    e = mi.earnings_info(_bundle(calendar={"Earnings Date": [dt.date(2026, 11, 27)]}))
    assert e["days_until"] == 4 and e["warning"]
    far = mi.earnings_info(_bundle(calendar={"Earnings Date": [dt.date(2027, 1, 27)]}))
    assert far["warning"] is None
    past = mi.earnings_info(_bundle(calendar={"Earnings Date": [dt.date(2026, 11, 10)]}))
    assert past["next_date"] is None and past["last_date"] == "2026-11-10"


def test_financing_risk_runway_and_dilution():
    q_bal = statement({"Ordinary Shares Number": [130.0, 120.0, 110.0, 105.0, 100.0]},
                      ["2026-09-30", "2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30"])
    fund = {"cash_quality": {"fcf_ttm": -1200.0, "ocf_ttm": -300.0}, "balance_health": {"cash": 1000.0},
            "revenue_ttm": 50.0, "sec": None}
    r = mi.financing_risk(_bundle(quarterly_balance=q_bal), fund)
    assert r["runway_months"] == pytest.approx(10.0)
    assert r["share_growth_1y_pct"] == pytest.approx(30.0)
    assert r["level"] == "high"
    healthy = mi.financing_risk(_bundle(), {"cash_quality": {"fcf_ttm": 500.0, "ocf_ttm": 600.0},
                                            "balance_health": {"cash": 100.0}, "sec": None})
    assert healthy["level"] == "low" and healthy["runway_months"] is None


# --------------------------------------------------------------- SEC XBRL cikarimi

def _fact(val, end, start=None, form="10-Q", filed="2026-11-01"):
    f = {"val": val, "end": end, "form": form, "filed": filed}
    if start:
        f["start"] = start
    return f


def test_sec_extract_ttm_from_ytd_and_debt_parts():
    usd = lambda *facts: {"units": {"USD": list(facts)}}  # noqa: E731
    facts = {"facts": {"us-gaap": {
        "Assets": usd(_fact(500, "2026-09-30")),
        # TTM = 2025 yillik 400 + 2026 9 ay 330 - 2025 9 ay 290 = 440
        "Revenues": usd(_fact(400, "2025-12-31", "2025-01-01", "10-K"), _fact(330, "2026-09-30", "2026-01-01"),
                        _fact(290, "2025-09-30", "2025-01-01")),
        "CashAndCashEquivalentsAtCarryingValue": usd(_fact(50, "2026-09-30")),
        "ShortTermInvestments": usd(_fact(25, "2026-09-30")),
        "LongTermDebtCurrent": usd(_fact(5, "2026-09-30")),
        "CommercialPaper": usd(_fact(3, "2026-09-30")),
        "LongTermDebtNoncurrent": usd(_fact(80, "2026-09-30")),
        "OperatingLeaseLiabilityCurrent": usd(_fact(2, "2026-09-30")),
        "OperatingLeaseLiabilityNoncurrent": usd(_fact(8, "2026-09-30")),
        # Eski etiket: son verisi cok eski -> kullanilmamali
        "SalesRevenueNet": usd(_fact(999, "2018-12-31", "2018-01-01", "10-K")),
    }}}
    s = extract(facts)
    assert s["revenue_ttm"] == 440
    assert s["cash_and_st"] == 75
    assert s["debt_ex_leases"] == 88
    assert s["lease_liabilities"] == 10


def test_sec_extract_returns_none_for_ifrs_filers():
    assert extract({"facts": {"ifrs-full": {}}}) is None


def test_sec_values_override_yahoo_and_report_differences(make_bundle):
    inc = statement({"Total Revenue": [100.0, 90.0], "Operating Income": [20.0, 18.0], "Net Income": [15.0, 12.0]},
                    ["2025-12-31", "2024-12-31"])
    bundle = make_bundle(inc=inc)
    bundle["sec"] = {"balance_date": "2026-09-30", "revenue_ttm": 130.0, "operating_income_ttm": 30.0,
                     "ocf_ttm": None, "fcf_ttm": None, "da_ttm": None, "cash_and_st": 40.0, "debt_ex_leases": 10.0,
                     "lease_liabilities": 2.0, "gross_profit_ttm": None, "net_income_ttm": 22.0,
                     "interest_expense_ttm": None}
    f = analyze_fundamental(bundle)
    assert f["data_source"].startswith("SEC")
    assert f["profitability"]["ebit_margin_pct"] == pytest.approx(30 / 130 * 100, abs=0.05)
    assert f["balance_health"]["net_debt"] == pytest.approx(12 - 40)
    rev = next(c for c in f["source_checks"] if c["item"] == "Gelir (TTM)")
    assert rev["diff_pct"] == pytest.approx((100 / 130 - 1) * 100, abs=0.1)
    assert any("%5'ten büyük fark" in n for n in f["notes"])


# --------------------------------------------------------------- donguusellik

def test_cyclical_peak_margin_is_flagged_and_penalized(make_bundle):
    rows = {"Total Revenue": [300.0, 100.0, 120.0, 110.0], "Operating Income": [210.0, 5.0, 12.0, 11.0],
            "Net Income": [180.0, 3.0, 9.0, 8.0]}
    inc = statement(rows, YEARS)
    peak = analyze_fundamental(make_bundle(inc=inc, info={"marketCap": 500.0, "sector": "Technology",
                                                          "industry": "Semiconductors"}))
    assert peak["cyclical"]["peak_margin"] is True
    assert peak["cyclical"]["normalized_pe"] > (500 / 180)
    assert any("Zirve kâr riski" in w for w in peak["flags_warn"])
    assert peak["score_penalty"] >= 10
    steady = analyze_fundamental(make_bundle(inc=inc, info={"marketCap": 500.0, "sector": "Technology",
                                                            "industry": "Software - Application"}))
    assert steady["cyclical"]["is_cyclical_industry"] is False
    assert steady["score_penalty"] < peak["score_penalty"]


# --------------------------------------------------------------- sektor ici kiyas

def test_percentile_rank_directions():
    assert storage.percentile_rank(5.0, [5, 10, 20, 30], "lower") == pytest.approx(0.875)
    assert storage.percentile_rank(0.30, [0.1, 0.2, 0.3], "higher") == pytest.approx(5 / 6)
    assert storage.percentile_rank(-3.0, [5, 10], "lower") is None  # negatif carpan siralanmaz


def test_peer_snapshot_roundtrip_and_blending(make_bundle):
    for i, ev in enumerate([6.0, 8.0, 10.0, 12.0, 30.0]):
        storage.save_snapshot(f"P{i}", "us", "us:Test", "Tech", "Soft", {"ev_ebitda": ev, "pe": ev * 1.5,
                                                                         "ebit_margin": 0.2})
    metrics, count = storage.peer_metrics("us:Test", exclude="P4")
    assert count == 4 and sorted(metrics["ev_ebitda"]) == [6.0, 8.0, 10.0, 12.0]
    metrics, count = storage.peer_metrics("us:Test")
    inc = statement({"Total Revenue": [100.0, 90.0], "Operating Income": [30.0, 25.0], "Net Income": [20.0, 18.0]},
                    ["2025-12-31", "2024-12-31"])
    f = analyze_fundamental(make_bundle(inc=inc), peers={"group": "us:Test", "count": count, "metrics": metrics})
    assert f["peers"]["used"] is True
    assert any("sektör içi" in b["label"] for b in f["score_breakdown"])


# --------------------------------------------------------------- puan gecmisi, onbellek, uyarilar

def test_score_history_and_cache():
    storage.record_scores("ABC", 60, 50, 70, 2, 10.0, 100, date="2026-11-20")
    storage.record_scores("ABC", 80, 70, 90, 2, 11.0, 100, date="2026-11-21")
    storage.record_scores("ABC", 81, 70, 91, 2, 11.0, 100, date="2026-11-21")  # ayni gun ustune yazar
    h = storage.score_history("abc")
    assert [x["date"] for x in h] == ["2026-11-20", "2026-11-21"] and h[-1]["composite"] == 81
    storage.cache_set("k", {"a": 1})
    assert storage.cache_get("k", ttl=60) == {"a": 1}
    assert storage.cache_get("k", ttl=-1) is None


def test_alerts_rules_and_dedupe():
    prev = {"stage": 1, "composite": 50}
    row = {"symbol": "X", "display_symbol": "X", "stage": 2, "composite_score": 70, "earnings_days": 3,
           "next_earnings": "2026-11-26"}
    kinds = [k for k, _, _ in scheduler.evaluate_alerts("X", row, prev)]
    assert kinds == ["stage", "score", "earnings"]
    assert scheduler.evaluate_alerts("X", {**row, "earnings_days": 30, "stage": 1, "composite_score": 55}, prev) == []
    k, msg, key = scheduler.evaluate_alerts("X", row, prev)[0]
    assert storage.add_alert("X", k, msg, key) is True
    assert storage.add_alert("X", k, msg, key) is False  # ayni uyari iki kez eklenmez
    assert storage.list_alerts(unseen_only=True)[0]["kind"] == "stage"
    assert storage.mark_alerts_seen() == 1


def test_check_watchlist_uses_previous_day(monkeypatch):
    storage.record_scores("AAA", 40, 40, 40, 1, 1.0, 100, date=(dt.date.today() - dt.timedelta(days=1)).isoformat())

    def summarize(sym, market):
        return {"symbol": sym, "display_symbol": sym, "stage": 2, "composite_score": 60, "earnings_days": None}

    added = scheduler.check_watchlist(lambda: [{"symbol": "AAA", "market": "us"}], summarize)
    assert added == 2  # evre 1->2 ve +20 puan
