"""
Arka plan gorevleri (sunucu acikken calisir):

1. Izleme listesi uyarilari (her ALERT_INTERVAL_SEC saniyede):
   * Weinstein evresi degisti (orn. Evre 1 -> 2)
   * Bilesik puan onceki gune gore >= SCORE_CHANGE_ALERT degisti
   * Bilanco EARNINGS_WARN_DAYS gun icinde
2. Sektor ici kiyas verisi (gunde bir kez): tema listelerindeki tum hisseler analiz edilip
   metrik goruntuleri kaydedilir; boylece her analizde "sektor icinde nerede?" sorusu cevaplanir.

HISSE_SCHEDULER=0 ortam degiskeniyle kapatilabilir (testlerde kapali).
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from . import storage
from .market_info import EARNINGS_WARN_DAYS
from .reference_data import themes

log = logging.getLogger("hisse_rontgen.scheduler")

ALERT_INTERVAL_SEC = 30 * 60
SCORE_CHANGE_ALERT = 15
PEER_SNAPSHOT_WORKERS = 3
STARTUP_DELAY_SEC = 120

STAGE_NAMES = {1: "Evre 1 (Taban)", 2: "Evre 2 (Yükseliş)", 3: "Evre 3 (Tepe)", 4: "Evre 4 (Düşüş)"}

_state: dict[str, Any] = {"running": False, "last_alert_check": None, "last_peer_snapshot": None,
                          "peer_progress": None, "errors": []}
_thread: threading.Thread | None = None
_stop = threading.Event()


def status() -> dict[str, Any]:
    return dict(_state)


def evaluate_alerts(symbol: str, row: dict[str, Any], previous: dict[str, Any] | None) -> list[tuple[str, str, str]]:
    """Saf fonksiyon: (tur, mesaj, tekillestirme_anahtari) listesi dondurur. Test edilebilir."""
    out: list[tuple[str, str, str]] = []
    today = dt.date.today().isoformat()
    name = row.get("display_symbol") or symbol
    if previous:
        old_stage, new_stage = previous.get("stage"), row.get("stage")
        if old_stage and new_stage and old_stage != new_stage:
            out.append(("stage", f"{name}: Weinstein evresi değişti — {STAGE_NAMES.get(old_stage, old_stage)} → "
                                 f"{STAGE_NAMES.get(new_stage, new_stage)}.", f"{symbol}:stage:{new_stage}:{today}"))
        old_c, new_c = previous.get("composite"), row.get("composite_score")
        if old_c is not None and new_c is not None and abs(new_c - old_c) >= SCORE_CHANGE_ALERT:
            yon = "yükseldi" if new_c > old_c else "düştü"
            out.append(("score", f"{name}: Bileşik puan {old_c} → {new_c} ({yon}).", f"{symbol}:score:{new_c}:{today}"))
    days = row.get("earnings_days")
    if days is not None and 0 <= days <= EARNINGS_WARN_DAYS:
        out.append(("earnings", f"{name}: Bilanço {days} gün içinde ({row.get('next_earnings')}).",
                    f"{symbol}:earnings:{row.get('next_earnings')}"))
    return out


def check_watchlist(load_watchlist: Callable[[], list[dict[str, str]]],
                    summarize: Callable[[str, str], dict[str, Any]]) -> int:
    """Izleme listesindeki her hisseyi tarayip yeni uyarilari kaydeder. Eklenen uyari sayisini dondurur."""
    added = 0
    for item in load_watchlist():
        sym = item["symbol"]
        try:
            history = storage.score_history(sym, limit=10)
            today = dt.date.today().isoformat()
            previous = next((h for h in reversed(history) if h["date"] < today), None)
            row = summarize(sym, item.get("market", "auto"))
            for kind, msg, key in evaluate_alerts(row.get("symbol", sym), row, previous):
                if storage.add_alert(row.get("symbol", sym), kind, msg, key):
                    added += 1
        except Exception as exc:
            _note_error(f"{sym}: {exc}")
    _state["last_alert_check"] = dt.datetime.now().isoformat(timespec="seconds")
    return added


def refresh_peers(analyze: Callable[..., Any], market: str | None = None) -> dict[str, int]:
    """Tema listelerindeki hisseleri analiz edip kiyas goruntulerini kaydeder."""
    markets = [market] if market else ["bist", "us"]
    symbols = [(s, m) for m in markets for syms in themes(m).values() for s in syms]
    done = failed = 0
    _state["peer_progress"] = {"done": 0, "total": len(symbols)}

    def one(arg):
        sym, m = arg
        try:
            analyze(sym, market=m, include_charts=False)
            return True
        except Exception as exc:
            _note_error(f"{sym}: {exc}")
            return False

    with ThreadPoolExecutor(max_workers=PEER_SNAPSHOT_WORKERS) as ex:
        for ok in ex.map(one, symbols):
            done += ok
            failed += (not ok)
            _state["peer_progress"] = {"done": done + failed, "total": len(symbols)}
            if _stop.is_set():
                break
    _state["last_peer_snapshot"] = dt.date.today().isoformat()
    return {"ok": done, "failed": failed}


def _note_error(msg: str) -> None:
    log.warning(msg)
    _state["errors"] = (_state["errors"] + [msg])[-20:]


def start(load_watchlist, summarize, analyze) -> None:
    """Sunucu acilisinda cagrilir. HISSE_SCHEDULER=0 ise hicbir sey yapmaz."""
    global _thread
    if os.environ.get("HISSE_SCHEDULER", "1") == "0" or (_thread and _thread.is_alive()):
        return
    _stop.clear()

    def loop():
        _state["running"] = True
        last_alert = 0.0
        # Acilista kullanicinin kendi analizleriyle Yahoo istek limitine takilmamak icin bekle
        _stop.wait(STARTUP_DELAY_SEC)
        while not _stop.is_set():
            try:
                today = dt.date.today().isoformat()
                if _state["last_peer_snapshot"] != today:
                    total = sum(len(v) for m in ("bist", "us") for v in themes(m).values())
                    if storage.snapshot_count(today) >= total * 0.8:
                        _state["last_peer_snapshot"] = today  # bugun zaten toplanmis (yeniden baslatma)
                    else:
                        refresh_peers(analyze)
                if time.time() - last_alert >= ALERT_INTERVAL_SEC:
                    check_watchlist(load_watchlist, summarize)
                    last_alert = time.time()
            except Exception as exc:  # dongu asla olmesin
                _note_error(f"zamanlayici: {exc}")
            _stop.wait(60)
        _state["running"] = False

    _thread = threading.Thread(target=loop, name="hisse-rontgen-scheduler", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()
