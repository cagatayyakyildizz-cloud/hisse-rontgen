from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .analyzer import analyze_stock, build_summary_row
from .data_fetcher import resolve_symbol
from .money_flow import compute_money_flow

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
WATCHLIST_FILE = BASE_DIR / "watchlist.json"

DEFAULT_WATCHLIST = [
    {"symbol": "THYAO.IS", "market": "bist"},
    {"symbol": "ASELS.IS", "market": "bist"},
    {"symbol": "TUPRS.IS", "market": "bist"},
    {"symbol": "BIMAS.IS", "market": "bist"},
    {"symbol": "AAPL", "market": "us"},
    {"symbol": "NVDA", "market": "us"},
]


def _load_watchlist() -> list[dict[str, str]]:
    if not WATCHLIST_FILE.exists():
        _save_watchlist(DEFAULT_WATCHLIST)
        return list(DEFAULT_WATCHLIST)
    try:
        data = json.loads(WATCHLIST_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return list(DEFAULT_WATCHLIST)


def _save_watchlist(items: list[dict[str, str]]) -> None:
    WATCHLIST_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


app = FastAPI(title="HisseRöntgen — Tekno-Temel Hisse Analiz Platformu", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class WatchlistItemIn(BaseModel):
    symbol: str
    market: str = "auto"


class CompareRequest(BaseModel):
    items: list[WatchlistItemIn]


@app.get("/")
def serve_home() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/analyze/{symbol}")
def api_analyze(
    symbol: str,
    market: str = Query("auto", pattern="^(auto|bist|us)$"),
    refresh: bool = Query(False),
) -> dict[str, Any]:
    try:
        return analyze_stock(symbol, market=market, force_refresh=refresh, include_charts=True)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Analiz sırasında hata oluştu: {exc}")


@app.get("/api/money-flow")
def api_money_flow(
    market: str = Query("bist", pattern="^(bist|us)$"),
    refresh: bool = Query(False),
) -> dict[str, Any]:
    try:
        return compute_money_flow(market=market, force_refresh=refresh)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Para akışı verisi alınamadı: {exc}")


@app.get("/api/watchlist")
def api_get_watchlist() -> dict[str, Any]:
    return {"items": _load_watchlist()}


@app.post("/api/watchlist")
def api_add_watchlist(item: WatchlistItemIn) -> dict[str, Any]:
    try:
        resolved, is_bist = resolve_symbol(item.symbol, item.market)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    items = _load_watchlist()
    if not any(x["symbol"].upper() == resolved.upper() for x in items):
        items.append({"symbol": resolved, "market": "bist" if is_bist else "us"})
        _save_watchlist(items)
    return {"items": items, "added": resolved}


@app.delete("/api/watchlist/{symbol}")
def api_remove_watchlist(symbol: str) -> dict[str, Any]:
    target = symbol.strip().upper()
    items = _load_watchlist()
    filtered = [x for x in items if x["symbol"].upper() != target and x["symbol"].upper() != f"{target}.IS"]
    _save_watchlist(filtered)
    return {"items": filtered}


@app.post("/api/compare")
def api_compare(req: CompareRequest) -> dict[str, Any]:
    if not req.items:
        return {"rows": [], "errors": []}

    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    order_map = {idx: item for idx, item in enumerate(req.items[:20])}
    ordered_results: dict[int, dict[str, Any]] = {}

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {
            pool.submit(build_summary_row, item.symbol, item.market): idx
            for idx, item in order_map.items()
        }
        for fut in as_completed(futures):
            idx = futures[fut]
            item = order_map[idx]
            try:
                ordered_results[idx] = fut.result()
            except Exception as exc:
                errors.append({"symbol": item.symbol, "error": str(exc)})

    for idx in sorted(ordered_results):
        rows.append(ordered_results[idx])
    return {"rows": rows, "errors": errors}
