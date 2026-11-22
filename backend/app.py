from __future__ import annotations

import json
import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi import Path as FastAPIPath
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import scheduler, storage
from .analyzer import analyze_stock, build_summary_row
from .data_fetcher import resolve_symbol
from .money_flow import compute_money_flow

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
WATCHLIST_FILE = BASE_DIR / "watchlist.json"

# Karsilastirma istegi basina en fazla hisse (Yahoo istek limiti ve yanit suresi icin)
MAX_COMPARE = 20
# Yahoo sembolleri: harf, rakam, nokta, tire, sapka, esittir (orn. THYAO.IS, BRK-B, ^GSPC, USDTRY=X)
SYMBOL_PATTERN = r"^[A-Za-z0-9.\-^=]{1,20}$"

# Izleme listesi dosyasina ayni anda yazan istekler birbirini ezmesin
_WATCHLIST_LOCK = threading.Lock()

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
    """Atomik yazma: once gecici dosyaya yaz, sonra yerine koy (yarim kalan dosya olusmaz)."""
    payload = json.dumps(items, ensure_ascii=False, indent=2)
    fd, tmp_path = tempfile.mkstemp(dir=str(WATCHLIST_FILE.parent), prefix=".watchlist-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp_path, WATCHLIST_FILE)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# Son analiz sonucunun diskten sunulma suresi (sunucu yeniden baslasa da tekrar indirilmez)
ANALYSIS_CACHE_TTL = 600


@asynccontextmanager
async def lifespan(_app: FastAPI):
    scheduler.start(_load_watchlist, lambda s, m: build_summary_row(s, m), analyze_stock)
    yield
    scheduler.stop()


app = FastAPI(title="HisseRöntgen — Tekno-Temel Hisse Analiz Platformu", version="1.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class WatchlistItemIn(BaseModel):
    symbol: str = Field(..., pattern=SYMBOL_PATTERN)
    market: str = Field("auto", pattern="^(auto|bist|us)$")


class CompareRequest(BaseModel):
    items: list[WatchlistItemIn]


@app.get("/")
def serve_home() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/analyze/{symbol}")
def api_analyze(
    symbol: str = FastAPIPath(..., pattern=SYMBOL_PATTERN),
    market: str = Query("auto", pattern="^(auto|bist|us)$"),
    refresh: bool = Query(False),
) -> dict[str, Any]:
    cache_key = f"analyze:{symbol.upper()}:{market}"
    if not refresh:
        try:
            cached = storage.cache_get(cache_key, ANALYSIS_CACHE_TTL)
        except Exception:
            cached = None
        if cached:
            return cached
    try:
        result = analyze_stock(symbol, market=market, force_refresh=refresh, include_charts=True)
        try:
            storage.cache_set(cache_key, result)
        except Exception:
            pass
        return result
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

    with _WATCHLIST_LOCK:
        items = _load_watchlist()
        if not any(x["symbol"].upper() == resolved.upper() for x in items):
            items.append({"symbol": resolved, "market": "bist" if is_bist else "us"})
            _save_watchlist(items)
    return {"items": items, "added": resolved}


@app.delete("/api/watchlist/{symbol}")
def api_remove_watchlist(symbol: str) -> dict[str, Any]:
    target = symbol.strip().upper()
    with _WATCHLIST_LOCK:
        items = _load_watchlist()
        filtered = [x for x in items if x["symbol"].upper() != target and x["symbol"].upper() != f"{target}.IS"]
        _save_watchlist(filtered)
    return {"items": filtered}


@app.post("/api/compare")
def api_compare(req: CompareRequest) -> dict[str, Any]:
    if not req.items:
        return {"rows": [], "errors": [], "skipped": []}

    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    # Sinir asilirsa fazlasi sessizce atilmaz; yanitta "skipped" olarak bildirilir
    skipped = [item.symbol for item in req.items[MAX_COMPARE:]]
    order_map = {idx: item for idx, item in enumerate(req.items[:MAX_COMPARE])}
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
    return {"rows": rows, "errors": errors, "skipped": skipped, "limit": MAX_COMPARE}


@app.get("/api/history/{symbol}")
def api_history(symbol: str = FastAPIPath(..., pattern=SYMBOL_PATTERN), limit: int = Query(365, ge=1, le=2000)) -> dict[str, Any]:
    return {"symbol": symbol.upper(), "history": storage.score_history(symbol, limit=limit)}


@app.get("/api/alerts")
def api_alerts(unseen: bool = Query(False), limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    items = storage.list_alerts(limit=limit, unseen_only=unseen)
    return {"items": items, "unseen": sum(1 for a in items if not a["seen"])}


@app.post("/api/alerts/seen")
def api_alerts_seen() -> dict[str, Any]:
    return {"updated": storage.mark_alerts_seen()}


@app.post("/api/alerts/check")
def api_alerts_check() -> dict[str, Any]:
    """Uyari kontrolunu hemen calistirir (normalde arka planda 30 dakikada bir)."""
    added = scheduler.check_watchlist(_load_watchlist, lambda s, m: build_summary_row(s, m))
    return {"added": added, "items": storage.list_alerts(limit=50)}


@app.post("/api/peers/refresh")
def api_peers_refresh(market: str = Query("us", pattern="^(bist|us)$")) -> dict[str, Any]:
    """Sektor ici kiyas verisini arka planda yeniler (uzun surer; durum /api/scheduler'da)."""
    threading.Thread(target=scheduler.refresh_peers, args=(analyze_stock, market), daemon=True).start()
    return {"started": True, "market": market}


@app.get("/api/scheduler")
def api_scheduler() -> dict[str, Any]:
    return scheduler.status()
