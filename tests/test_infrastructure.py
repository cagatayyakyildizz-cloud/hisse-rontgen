"""Onbellek, kur birimi, referans verileri ve para akisi yardimcilari."""
import time

import numpy as np
import pandas as pd

from backend.cache import TTLCache
from backend.data_fetcher import KNOWN_BIST, normalize_currency, resolve_symbol
from backend.money_flow import _compute_window_metrics
from backend.reference_data import themes

KNOWN_ETFS = {"IBIT", "GLD", "SLV", "SPY", "QQQ", "IAU", "FBTC", "XLK", "SMH", "SOXX", "ARKK"}


def test_cache_evicts_least_recently_used():
    c = TTLCache(max_entries=2)
    c.set("a", 1)
    c.set("b", 2)
    assert c.get("a", ttl=60) == 1  # "a" yeni kullanildi
    c.set("c", 3)                    # "b" atilmali
    assert c.get("b", ttl=60) is None
    assert c.get("a", ttl=60) == 1 and c.get("c", ttl=60) == 3
    assert len(c) == 2


def test_cache_expires_entries():
    c = TTLCache(max_entries=5)
    c.set("a", 1)
    assert c.get("a", ttl=0) is None
    c.set("b", 2)
    time.sleep(0.01)
    assert c.get("b", ttl=60) == 2


def test_minor_unit_currencies_are_not_uppercased():
    assert normalize_currency("GBp", "USD") == ("GBp", "GBP", 100)
    assert normalize_currency("ZAc", "USD") == ("ZAc", "ZAR", 100)
    assert normalize_currency("usd", "USD") == ("USD", "USD", 1)
    assert normalize_currency(None, "TRY") == ("TRY", "TRY", 1)


def test_bist_aliases_resolve_without_network():
    assert resolve_symbol("KOZAL", "bist") == ("TRALT.IS", True)
    assert resolve_symbol("thyao", "auto") == ("THYAO.IS", True)
    assert resolve_symbol("THYAO.IS", "us") == ("THYAO", False)
    assert "THYAO" in KNOWN_BIST


def test_themes_contain_no_etfs():
    for market in ("bist", "us"):
        for name, syms in themes(market).items():
            assert syms, name
            assert not (set(syms) & KNOWN_ETFS), f"{name} ETF iceriyor"
            assert len(syms) == len(set(syms)), f"{name} tekrar eden sembol iceriyor"


def _ohlcv(closes: list[float], close_at_high: bool) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=len(closes), freq="B")
    c = np.array(closes, dtype=float)
    high = c * 1.01 if not close_at_high else c
    low = c * 0.97
    return pd.DataFrame({"Open": c, "High": high, "Low": low, "Close": c, "Volume": 1_000_000.0}, index=idx)


def test_flow_score_positive_for_rising_stock_closing_at_highs():
    df = _ohlcv(list(np.linspace(100, 130, 70)), close_at_high=True)
    m = _compute_window_metrics(df, bench_ret=2.0, days=21)
    assert m["flow_score"] > 30
    assert m["cmf"] > 0.5


def test_flow_score_negative_for_falling_stock():
    df = _ohlcv(list(np.linspace(130, 100, 70)), close_at_high=False)
    m = _compute_window_metrics(df, bench_ret=0.0, days=21)
    assert m["flow_score"] < 0
