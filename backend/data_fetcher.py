from __future__ import annotations

import time
from typing import Any

import pandas as pd
import yfinance as yf

from .cache import TTLCache
from .reference_data import bist_aliases, known_bist

# Eski -> Yeni BIST kod yonlendirmeleri ve bilinen BIST kodlari: backend/data/bist_symbols.json
BIST_ALIASES: dict[str, str] = bist_aliases()
KNOWN_BIST: frozenset[str] = known_bist()

# Kurus / pens gibi ALT BIRIMLE fiyatlanan para birimleri: (ana birim, carpan).
# Ornek: LSE hisseleri "GBp" (pens) ile fiyatlanir; .upper() ile "GBP" yapmak fiyati 100 kat
# yanlis gosterir. Yahoo'nun marketCap degeri ise ANA birimdedir (GBP).
MINOR_UNIT_CURRENCIES: dict[str, tuple[str, int]] = {
    "GBp": ("GBP", 100),
    "GBX": ("GBP", 100),
    "ZAc": ("ZAR", 100),
    "ZAC": ("ZAR", 100),
    "ILA": ("ILS", 100),
}

STOCK_TTL = 600      # 10 dakika
MACRO_TTL = 900      # 15 dakika

# Her hisse paketi 2 yillik fiyat + 6 finansal tablo icerir; sinirsiz buyumemesi icin LRU
_STOCK_CACHE = TTLCache(max_entries=40)
_MACRO_CACHE = TTLCache(max_entries=40)


def normalize_currency(raw: str | None, default: str) -> tuple[str, str, int]:
    """
    Donus: (gosterim_birimi, ana_birim, alt_birim_carpani)
    'GBp' -> ('GBp', 'GBP', 100);  'usd' -> ('USD', 'USD', 1)
    """
    if not raw:
        return default, default, 1
    if raw in MINOR_UNIT_CURRENCIES:
        major, factor = MINOR_UNIT_CURRENCIES[raw]
        return raw, major, factor
    up = raw.upper()
    return up, up, 1


def _clean_history(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [c[0] for c in df.columns]
    df = df.dropna(subset=["Close"]).copy()
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


def _fetch_history_direct(symbol: str, period: str = "2y") -> pd.DataFrame:
    t = yf.Ticker(symbol)
    df = t.history(period=period, interval="1d", auto_adjust=True)
    return _clean_history(df)


def resolve_symbol(raw_symbol: str, market: str = "auto") -> tuple[str, bool]:
    """
    Kullanicinin girdigi sembolu Yahoo Finance formatina cozer.
    Donus: (cozulmus_sembol, is_bist)
    """
    sym = raw_symbol.strip().upper().replace(" ", "")
    if not sym:
        raise ValueError("Hisse kodu boş olamaz.")

    base = sym[:-3] if sym.endswith(".IS") else sym
    if base in BIST_ALIASES:
        sym = f"{BIST_ALIASES[base]}.IS" if sym.endswith(".IS") else BIST_ALIASES[base]

    m = (market or "auto").lower()
    if m == "bist":
        if not sym.endswith(".IS"):
            sym = f"{sym}.IS"
        return sym, True

    if m == "us":
        if sym.endswith(".IS"):
            sym = sym[:-3]
        return sym, False

    # Auto mode
    if sym.endswith(".IS"):
        return sym, True
    if "." in sym or "-" in sym or sym.startswith("^"):
        return sym, sym.endswith(".IS")
    if sym in KNOWN_BIST:
        return f"{sym}.IS", True

    # Bilinmeyen sembol: once ABD/dogrudan dene, veri yoksa .IS dene
    df = _fetch_history_direct(sym, period="1mo")
    if not df.empty:
        return sym, False

    bist_sym = f"{sym}.IS"
    df_bist = _fetch_history_direct(bist_sym, period="1mo")
    if not df_bist.empty:
        return bist_sym, True

    return sym, False


def fetch_macro_series(symbol: str, period: str = "2y") -> pd.DataFrame:
    key = f"macro:{symbol}:{period}"
    cached = _MACRO_CACHE.get(key, MACRO_TTL)
    if cached is not None:
        return cached
    df = _fetch_history_direct(symbol, period=period)
    if not df.empty:
        _MACRO_CACHE.set(key, df)
    return df


def fetch_fx_rate(from_curr: str, to_curr: str) -> float | None:
    """
    1 birim from_curr kac to_curr eder? (Orn: USD -> TRY = ~35-45)
    """
    fc = (from_curr or "").upper()
    tc = (to_curr or "").upper()
    if not fc or not tc or fc == tc:
        return 1.0
    df = fetch_macro_series(f"{fc}{tc}=X", period="1mo")
    if not df.empty:
        val = float(df["Close"].iloc[-1])
        if val > 0:
            return val
    inv = fetch_macro_series(f"{tc}{fc}=X", period="1mo")
    if not inv.empty:
        val = float(inv["Close"].iloc[-1])
        if val > 0:
            return 1.0 / val
    return None


def fetch_stock_bundle(
    raw_symbol: str,
    market: str = "auto",
    force_refresh: bool = False,
) -> dict[str, Any]:
    """
    Bir hisse icin fiyat gecmisi, endeks, USDTRY (BIST ise), sirket bilgisi
    ve 3 finansal tabloyu (yillik + ceyreklik) getirir.
    """
    resolved, is_bist = resolve_symbol(raw_symbol, market)
    cache_key = f"stock:{resolved}"
    if not force_refresh:
        cached = _STOCK_CACHE.get(cache_key, STOCK_TTL)
        if cached is not None:
            return cached

    ticker = yf.Ticker(resolved)
    history = _clean_history(ticker.history(period="2y", interval="1d", auto_adjust=True))
    if history.empty:
        # Eger market='auto' ile yanlis cozulduyse diger tarafi son kez dene
        if market == "auto" and not is_bist and not resolved.endswith(".IS"):
            alt = f"{resolved}.IS"
            alt_hist = _clean_history(yf.Ticker(alt).history(period="2y", interval="1d", auto_adjust=True))
            if not alt_hist.empty:
                resolved, is_bist = alt, True
                ticker = yf.Ticker(resolved)
                history = alt_hist
        if history.empty:
            raise ValueError(f"'{raw_symbol}' için piyasa verisi bulunamadı. Kodu veya piyasa seçimini kontrol edin.")

    try:
        info = ticker.info or {}
    except Exception:
        info = {}

    def _safe_df(getter) -> pd.DataFrame:
        try:
            df = getter()
            return df if isinstance(df, pd.DataFrame) else pd.DataFrame()
        except Exception:
            return pd.DataFrame()

    income_stmt = _safe_df(lambda: ticker.income_stmt)
    quarterly_income = _safe_df(lambda: ticker.quarterly_income_stmt)
    balance_sheet = _safe_df(lambda: ticker.balance_sheet)
    quarterly_balance = _safe_df(lambda: ticker.quarterly_balance_sheet)
    cashflow = _safe_df(lambda: ticker.cashflow)
    quarterly_cashflow = _safe_df(lambda: ticker.quarterly_cashflow)

    benchmark_symbol = "XU100.IS" if is_bist else "^GSPC"
    benchmark_name = "BIST 100" if is_bist else "S&P 500"
    benchmark = fetch_macro_series(benchmark_symbol, period="2y")
    # 5 yillik kur: yillik buyumeyi donem ortalama kuruyla dolara cevirmek icin (TMS 29)
    usdtry = fetch_macro_series("USDTRY=X", period="5y") if is_bist else pd.DataFrame()

    default_curr = "TRY" if is_bist else "USD"
    trade_currency, trade_major, minor_factor = normalize_currency(info.get("currency"), default_curr)
    _, fin_currency, _ = normalize_currency(info.get("financialCurrency"), trade_major)
    # Kur hizalamasi ANA birimler uzerinden yapilir (marketCap ana birimdedir)
    fin_to_trade_fx = 1.0
    if fin_currency != trade_major:
        if fin_currency == "USD" and trade_major == "TRY" and not usdtry.empty:
            fin_to_trade_fx = float(usdtry["Close"].iloc[-1])
        else:
            fx = fetch_fx_rate(fin_currency, trade_major)
            if fx and fx > 0:
                fin_to_trade_fx = fx

    bundle = {
        "symbol": resolved,
        "display_symbol": resolved[:-3] if is_bist and resolved.endswith(".IS") else resolved,
        "is_bist": is_bist,
        "currency": trade_currency,            # fiyat gosterim birimi (orn. GBp)
        "currency_major": trade_major,         # ana birim (orn. GBP) — piyasa degeri bu birimde
        "minor_unit_factor": minor_factor,     # 100 ise fiyatlar alt birimde (pens/kurus)
        "financial_currency": fin_currency,
        "fin_to_trade_fx": fin_to_trade_fx,
        "info": info,
        "history": history,
        "benchmark_symbol": benchmark_symbol,
        "benchmark_name": benchmark_name,
        "benchmark": benchmark,
        "usdtry": usdtry,
        "income_stmt": income_stmt,
        "quarterly_income": quarterly_income,
        "balance_sheet": balance_sheet,
        "quarterly_balance": quarterly_balance,
        "cashflow": cashflow,
        "quarterly_cashflow": quarterly_cashflow,
        "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    _STOCK_CACHE.set(cache_key, bundle)
    return bundle
