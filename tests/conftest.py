import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def statement(rows: dict[str, list[float | None]], dates: list[str]) -> pd.DataFrame:
    """yfinance bicimli finansal tablo: satirlar kalem, sutunlar donem (yeniden eskiye)."""
    cols = [pd.Timestamp(d) for d in dates]
    return pd.DataFrame({c: [rows[k][i] for k in rows] for i, c in enumerate(cols)}, index=list(rows))


@pytest.fixture
def make_bundle():
    """Testler icin ag erisimi olmayan sahte bir hisse paketi uretir."""

    def _make(
        *,
        inc: pd.DataFrame | None = None,
        bal: pd.DataFrame | None = None,
        cf: pd.DataFrame | None = None,
        q_inc: pd.DataFrame | None = None,
        q_bal: pd.DataFrame | None = None,
        q_cf: pd.DataFrame | None = None,
        info: dict | None = None,
        is_bist: bool = False,
        currency: str = "USD",
        financial_currency: str = "USD",
        usdtry: pd.DataFrame | None = None,
    ) -> dict:
        empty = pd.DataFrame()
        return {
            "symbol": "TEST",
            "display_symbol": "TEST",
            "is_bist": is_bist,
            "currency": currency,
            "currency_major": currency,
            "minor_unit_factor": 1,
            "financial_currency": financial_currency,
            "fin_to_trade_fx": 1.0,
            "info": {"marketCap": 1_000.0, "sector": "Technology", "industry": "Software", **(info or {})},
            "income_stmt": inc if inc is not None else empty,
            "quarterly_income": q_inc if q_inc is not None else empty,
            "balance_sheet": bal if bal is not None else empty,
            "quarterly_balance": q_bal if q_bal is not None else empty,
            "cashflow": cf if cf is not None else empty,
            "quarterly_cashflow": q_cf if q_cf is not None else empty,
            "usdtry": usdtry if usdtry is not None else empty,
        }

    return _make
