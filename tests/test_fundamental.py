"""Temel analiz hesaplamalarinin ag erisimi olmadan dogrulanmasi."""
import pandas as pd
import pytest

from backend.fundamental import analyze_fundamental
from tests.conftest import statement

YEARS = ["2025-12-31", "2024-12-31"]


def _healthy_inc(op_income=(157.0, 120.0), ebit=(290.0, 150.0), revenue=(471.0, 400.0)):
    return statement(
        {
            "Total Revenue": list(revenue),
            "Gross Profit": [280.0, 230.0],
            "Operating Income": list(op_income),
            "EBIT": list(ebit),
            "EBITDA": [320.0, 180.0],
            "Net Income": [235.0, 130.0],
            "Interest Expense": [3.0, 3.0],
            "Selling General And Administration": [60.0, 55.0],
        },
        YEARS,
    )


def _healthy_cf():
    return statement(
        {
            "Operating Cash Flow": [180.0, 140.0],
            "Capital Expenditure": [-160.0, -50.0],
            "Depreciation And Amortization": [28.0, 20.0],
        },
        YEARS,
    )


def _bal(**overrides):
    rows = {
        "Total Assets": [700.0, 600.0],
        "Current Assets": [375.0, 330.0],
        "Current Liabilities": [134.0, 120.0],
        "Stockholders Equity": [677.0, 560.0],
        "Total Liabilities Net Minority Interest": [326.0, 300.0],
        "Total Debt": [141.9, 120.0],
        "Long Term Debt": [125.1, 110.0],
        "Capital Lease Obligations": [16.8, 10.0],
        "Cash And Cash Equivalents": [56.3, 50.0],
        "Cash Cash Equivalents And Short Term Investments": [265.1, 240.0],
        # Yahoo'nun yaniltici satiri: sadece nakdi dusuyor (141.9 - 56.3 = 85.6 ... pozitif net borc)
        "Net Debt": [68.8, 70.0],
        "Retained Earnings": [400.0, 350.0],
        "Accounts Receivable": [60.0, 55.0],
        "Net PPE": [300.0, 250.0],
        "Ordinary Shares Number": [12.0, 12.2],
    }
    rows.update(overrides)
    return statement(rows, YEARS)


# --- 1. Net borc: kisa vadeli yatirimlar dahil, Yahoo "Net Debt" satiri kullanilmaz ---------------

def test_net_debt_includes_short_term_investments(make_bundle):
    res = analyze_fundamental(make_bundle(inc=_healthy_inc(), bal=_bal(), cf=_healthy_cf()))
    bh = res["balance_health"]
    assert bh["net_debt"] == pytest.approx(141.9 - 265.1, abs=1)
    assert bh["net_debt"] < 0, "GOOGL benzeri sirket net nakit gorunmeli"
    assert any("Net Nakit" in f for f in res["flags_good"])
    assert bh["lease_liabilities"] == 17  # _safe(..., 0) yuvarlar


def test_ev_uses_corrected_net_debt(make_bundle):
    res = analyze_fundamental(make_bundle(inc=_healthy_inc(), bal=_bal(), cf=_healthy_cf(),
                                          info={"marketCap": 1000.0}))
    # EV = 1000 + (141.9 - 265.1)
    assert res["enterprise_value_fin"] == pytest.approx(1000 + 141.9 - 265.1, abs=1)


def test_debt_free_company_without_debt_rows(make_bundle):
    bal = _bal()
    bal = bal.drop(index=["Total Debt", "Long Term Debt", "Capital Lease Obligations", "Net Debt"])
    res = analyze_fundamental(make_bundle(inc=_healthy_inc(), bal=bal, cf=_healthy_cf()))
    assert res["balance_health"]["total_debt"] == 0
    assert res["balance_health"]["net_debt"] < 0
    assert any("borçsuz" in n for n in res["notes"])
    assert "Faiz karşılama" not in res["missing_inputs"]


# --- 2. Esas faaliyet kari "EBIT" satirina tercih edilir ------------------------------------------

def test_operating_income_preferred_over_ebit(make_bundle):
    res = analyze_fundamental(make_bundle(inc=_healthy_inc(), bal=_bal(), cf=_healthy_cf()))
    # EBIT marji 157/471, (290/471 DEGIL)
    assert res["profitability"]["ebit_margin_pct"] == pytest.approx(157 / 471 * 100, abs=0.05)


def test_ebitda_built_from_operating_income_plus_da(make_bundle):
    res = analyze_fundamental(make_bundle(inc=_healthy_inc(), bal=_bal(), cf=_healthy_cf()))
    # FAVOK = 157 + 28 = 185 (Yahoo'nun 320'lik EBITDA satiri degil)
    assert res["profitability"]["ebitda_margin_pct"] == pytest.approx(185 / 471 * 100, abs=0.05)
    assert res["history_table"][0]["ebitda"] == 185


# --- 3. Beneish: yetersiz veri ve yuksek buyume puandan dusulmez ----------------------------------

def test_beneish_not_computed_with_few_real_components(make_bundle):
    inc = statement({"Total Revenue": [200.0, 100.0], "Net Income": [10.0, 8.0]}, YEARS)
    bal = statement({"Total Assets": [500.0, 450.0]}, YEARS)
    res = analyze_fundamental(make_bundle(inc=inc, bal=bal))
    ben = res["scores"]["beneish"]
    assert ben["score"] is None
    assert "Yetersiz Veri" in ben["status"]


def test_beneish_high_growth_is_not_penalized(make_bundle):
    # Gelir 2 katina cikan, diger bilesenleri notr bir sirket
    fast = _healthy_inc(revenue=(800.0, 400.0))
    slow = _healthy_inc(revenue=(420.0, 400.0))
    res_fast = analyze_fundamental(make_bundle(inc=fast, bal=_bal(), cf=_healthy_cf()))
    ben = res_fast["scores"]["beneish"]
    assert ben["score"] is not None and ben["score"] > -1.78
    assert ben["high_growth"] is True
    assert any("puandan düşülmedi" in f for f in res_fast["flags_warn"])
    # Beneish tek basina puan kesintisine donusmez: hizli buyuyen sirketin puani yavas olandan dusuk olamaz
    res_slow = analyze_fundamental(make_bundle(inc=slow, bal=_bal(), cf=_healthy_cf()))
    assert res_fast["score"] >= res_slow["score"]


# --- 5. Eksik veri puan kazandirmaz -----------------------------------------------------------

def test_no_data_gives_no_free_points(make_bundle):
    res = analyze_fundamental(make_bundle())
    assert res["score"] == 0
    assert res["data_coverage_pct"] == 0
    assert len(res["missing_inputs"]) > 5


def test_partial_data_reports_coverage(make_bundle):
    inc = statement({"Total Revenue": [100.0, 90.0], "Operating Income": [20.0, 15.0], "Net Income": [15.0, 10.0]}, YEARS)
    res = analyze_fundamental(make_bundle(inc=inc))
    assert 0 < res["data_coverage_pct"] < 100
    assert res["missing_inputs"]
    assert any("veri" in n.lower() and "%" in n for n in res["notes"])


def test_loss_making_company_gets_zero_valuation_not_missing(make_bundle):
    inc = statement({"Total Revenue": [100.0, 90.0], "Operating Income": [-20.0, -15.0], "Net Income": [-25.0, -18.0]}, YEARS)
    res = analyze_fundamental(make_bundle(inc=inc))
    assert "Değerleme" not in res["missing_inputs"]


# --- 4. BIST: buyume dolar bazinda (enflasyon etkisi disarida) ---------------------------------

def _usdtry(start: str, end: str, start_rate: float, end_rate: float) -> pd.DataFrame:
    idx = pd.date_range(start, end, freq="B")
    rates = pd.Series(range(len(idx)), index=idx, dtype=float)
    rates = start_rate + (end_rate - start_rate) * rates / max(len(idx) - 1, 1)
    return pd.DataFrame({"Close": rates})


def test_bist_growth_is_measured_in_usd(make_bundle):
    # Nominal TL ciro %40 artmis ama kur da ~%40 artmis -> dolar bazinda buyume ~0
    inc = statement({"Total Revenue": [140.0, 100.0], "Operating Income": [14.0, 10.0], "Net Income": [10.0, 7.0]}, YEARS)
    fx = _usdtry("2023-12-01", "2025-12-31", 25.0, 49.0)
    res = analyze_fundamental(make_bundle(inc=inc, is_bist=True, currency="TRY", financial_currency="TRY", usdtry=fx))
    assert res["growth_basis"] == "USD"
    assert res["growth"]["rev_yoy_pct"] is not None
    assert abs(res["growth"]["rev_yoy_pct"]) < 10, "Enflasyon/kur kaynakli nominal buyume puanlanmamali"


def test_bist_growth_skipped_without_fx(make_bundle):
    inc = statement({"Total Revenue": [140.0, 100.0], "Operating Income": [14.0, 10.0], "Net Income": [10.0, 7.0]}, YEARS)
    res = analyze_fundamental(make_bundle(inc=inc, is_bist=True, currency="TRY", financial_currency="TRY"))
    assert res["growth"]["rev_yoy_pct"] is None
    assert "Ciro büyümesi" in res["missing_inputs"]


def test_us_growth_stays_nominal(make_bundle):
    inc = statement({"Total Revenue": [140.0, 100.0], "Operating Income": [14.0, 10.0], "Net Income": [10.0, 7.0]}, YEARS)
    res = analyze_fundamental(make_bundle(inc=inc))
    assert res["growth_basis"] == "nominal"
    assert res["growth"]["rev_yoy_pct"] == pytest.approx(40.0)
