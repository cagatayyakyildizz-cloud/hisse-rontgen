from __future__ import annotations

import threading
import time
from typing import Any

import pandas as pd
import yfinance as yf

# Eski -> Yeni BIST hisse kod yonlendirmeleri (Kasim 2025 unvan degisiklikleri)
BIST_ALIASES: dict[str, str] = {
    "KOZAL": "TRALT",
    "KOZAA": "TRMET",
    "IPEKE": "TRENJ",
}

# Yaygin BIST sembolleri: Otomatik modda dogrudan .IS eklenir
KNOWN_BIST = {
    "AEFES", "AGHOL", "AHGAZ", "AKBNK", "AKCNS", "AKFGY", "AKFYE", "AKGRT", "AKSA", "AKSEN",
    "ALARK", "ALBRK", "ALFAS", "ALKIM", "ALTNY", "ANSGR", "ARCLK", "ARDYZ", "ASELS", "ASTOR", "ASUZU",
    "AVPGY", "BERA", "BFREN", "BIENY", "BIMAS", "BJKAS", "BOSSA", "BRISA", "BRSAN",
    "BRYAT", "BTCIM", "BUCIM", "CANTE", "CCOLA", "CIMSA", "CLEBI", "CVKMD", "CWENE", "DEVA",
    "DOAS", "DOHOL", "ECILC", "ECZYT", "EGEEN", "EKGYO", "ENERY", "ENJSA", "ENKAI",
    "EREGL", "ESEN", "EUPWR", "FENER", "FROTO", "GARAN", "GESAN", "GLYHO", "GOLTS",
    "GOODY", "GSDHO", "GSRAY", "GUBRF", "GWIND", "HALKB", "HEDEF", "HEKTS", "HLGYO",
    "INVEO", "ISCTR", "ISGYO", "ISMEN", "IZENR", "JANTS", "KARSN", "KCAER",
    "KCHOL", "KLKIM", "KLRHO", "KLSER", "KMPUR", "KONTR", "KONYA", "KORDS",
    "KRDMD", "KUTPO", "LOGO", "MAGEN", "MAVI", "MGROS", "MIATK", "MPARK",
    "NATEN", "NTGAZ", "NTHOL", "NUHCM", "ODAS", "ONRYT", "OTKAR", "OYAKC", "PAPIL", "PARSN", "PASEU",
    "PEKGY", "PENTA", "PETKM", "PGSUS", "PRKME", "QUAGR", "REEDR", "RYGYO", "RYSAS",
    "SAHOL", "SARKY", "SASA", "SDTTR", "SELEC", "SISE", "SKBNK", "SMRTG", "SNGYO",
    "SOKM", "TABGD", "TATGD", "TAVHL", "TCELL", "THYAO", "TKFEN", "TMSN", "TOASO",
    "TRALT", "TRENJ", "TRGYO", "TRMET", "TSKB", "TSPOR", "TTKOM", "TTRAK", "TUKAS", "TUPRS", "TURSG", "ULKER",
    "VAKBN", "VESBE", "VESTL", "VKGYO", "YEOTK", "YKBNK", "ZOREN", "ZRGYO",
}

_CACHE: dict[str, tuple[float, Any]] = {}
_LOCK = threading.Lock()
STOCK_TTL = 600      # 10 dakika
MACRO_TTL = 900      # 15 dakika


def _cache_get(key: str, ttl: int) -> Any | None:
    with _LOCK:
        entry = _CACHE.get(key)
        if entry and (time.time() - entry[0]) < ttl:
            return entry[1]
    return None


def _cache_set(key: str, value: Any) -> None:
    with _LOCK:
        _CACHE[key] = (time.time(), value)


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
    cached = _cache_get(key, MACRO_TTL)
    if cached is not None:
        return cached
    df = _fetch_history_direct(symbol, period=period)
    if not df.empty:
        _cache_set(key, df)
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
        cached = _cache_get(cache_key, STOCK_TTL)
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
    usdtry = fetch_macro_series("USDTRY=X", period="2y") if is_bist else pd.DataFrame()

    trade_currency = (info.get("currency") or ("TRY" if is_bist else "USD")).upper()
    fin_currency = (info.get("financialCurrency") or trade_currency).upper()
    fin_to_trade_fx = 1.0
    if fin_currency != trade_currency:
        if fin_currency == "USD" and trade_currency == "TRY" and not usdtry.empty:
            fin_to_trade_fx = float(usdtry["Close"].iloc[-1])
        else:
            fx = fetch_fx_rate(fin_currency, trade_currency)
            if fx and fx > 0:
                fin_to_trade_fx = fx

    bundle = {
        "symbol": resolved,
        "display_symbol": resolved[:-3] if is_bist and resolved.endswith(".IS") else resolved,
        "is_bist": is_bist,
        "currency": trade_currency,
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
    _cache_set(cache_key, bundle)
    return bundle
