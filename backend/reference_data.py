"""Koda gomulu olmayan referans verileri (BIST kod listeleri ve tema haritalari).

Kod / unvan degisikliklerinde veya tema guncellemelerinde Python koduna dokunmadan
`backend/data/*.json` dosyalarini duzenlemek yeterlidir.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"


@lru_cache(maxsize=None)
def _load(name: str) -> dict:
    with (DATA_DIR / name).open(encoding="utf-8") as fh:
        return json.load(fh)


def bist_aliases() -> dict[str, str]:
    return {k.upper(): v.upper() for k, v in _load("bist_symbols.json")["aliases"].items()}


def known_bist() -> frozenset[str]:
    return frozenset(s.upper() for s in _load("bist_symbols.json")["known_bist"])


def themes(market: str) -> dict[str, list[str]]:
    key = "us" if market == "us" else "bist"
    return {name: list(syms) for name, syms in _load("themes.json")[key].items()}


def theme_of(symbol: str) -> tuple[str, str] | None:
    """Sembolun bulundugu tema: (piyasa, tema_adi). Temada yoksa None."""
    sym = symbol.upper()
    for market in ("bist", "us"):
        for name, syms in themes(market).items():
            if sym in (s.upper() for s in syms):
                return market, name
    return None
