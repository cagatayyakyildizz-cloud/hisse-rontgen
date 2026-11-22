"""
Yerel SQLite kaydi.

* score_history    : her hissenin gunluk puanlari (puan gecmisi grafigi, uyarilar, ileride bilanco backtest'i)
* metrics_snapshot : sektor/tema ici kiyaslama icin carpan ve karlilik anlik goruntuleri
* analysis_cache   : son analiz sonuclari (sunucu yeniden baslasa da kisa sure tekrar indirilmez)
* alerts           : izleme listesi uyarilari

Veritabani varsayilan olarak `.cache/hisse_rontgen.sqlite3` dosyasindadir (HISSE_DB ile degistirilebilir).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

DEFAULT_DB = Path(__file__).resolve().parent.parent / ".cache" / "hisse_rontgen.sqlite3"
_LOCK = threading.Lock()

# Kiyaslamada kullanilan metrikler ve hangi yonun "iyi" oldugu
PEER_METRICS: dict[str, str] = {
    "ev_ebitda": "lower",
    "pe": "lower",
    "fcf_yield": "higher",
    "roic": "higher",
    "ebit_margin": "higher",
    "rev_growth": "higher",
}
PEER_MAX_AGE_DAYS = 14

SCHEMA = """
CREATE TABLE IF NOT EXISTS score_history (
    symbol TEXT NOT NULL, date TEXT NOT NULL, composite INTEGER, tech INTEGER, fund INTEGER,
    stage INTEGER, price REAL, coverage INTEGER,
    PRIMARY KEY (symbol, date)
);
CREATE TABLE IF NOT EXISTS metrics_snapshot (
    symbol TEXT NOT NULL, date TEXT NOT NULL, market TEXT, peer_group TEXT, sector TEXT, industry TEXT,
    ev_ebitda REAL, pe REAL, fcf_yield REAL, roic REAL, ebit_margin REAL, rev_growth REAL,
    PRIMARY KEY (symbol, date)
);
CREATE INDEX IF NOT EXISTS idx_snapshot_group ON metrics_snapshot (peer_group, date);
CREATE TABLE IF NOT EXISTS analysis_cache (
    key TEXT PRIMARY KEY, saved_at REAL NOT NULL, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS screen_rows (
    symbol TEXT NOT NULL, date TEXT NOT NULL, market TEXT NOT NULL, payload TEXT NOT NULL,
    PRIMARY KEY (symbol, date)
);
CREATE INDEX IF NOT EXISTS idx_screen_market ON screen_rows (market, date);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, created_at TEXT NOT NULL,
    kind TEXT NOT NULL, message TEXT NOT NULL, seen INTEGER NOT NULL DEFAULT 0,
    dedupe_key TEXT UNIQUE
);
"""


def db_path() -> Path:
    return Path(os.environ.get("HISSE_DB") or DEFAULT_DB)


def _connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _run(fn):
    with _LOCK:
        conn = _connect()
        try:
            out = fn(conn)
            conn.commit()
            return out
        finally:
            conn.close()


def _today() -> str:
    return dt.date.today().isoformat()


# ---------------------------------------------------------------- puan gecmisi

def record_scores(symbol: str, composite: int, tech: int, fund: int, stage: int | None,
                  price: float | None, coverage: int | None, date: str | None = None) -> None:
    d = date or _today()
    _run(lambda c: c.execute(
        "INSERT OR REPLACE INTO score_history VALUES (?,?,?,?,?,?,?,?)",
        (symbol.upper(), d, composite, tech, fund, stage, price, coverage)))


def score_history(symbol: str, limit: int = 365) -> list[dict[str, Any]]:
    rows = _run(lambda c: c.execute(
        "SELECT * FROM score_history WHERE symbol=? ORDER BY date DESC LIMIT ?", (symbol.upper(), limit)).fetchall())
    return [dict(r) for r in reversed(rows)]


# ---------------------------------------------------------------- sektor ici kiyas

def save_snapshot(symbol: str, market: str, peer_group: str | None, sector: str | None, industry: str | None,
                  metrics: dict[str, float | None], date: str | None = None) -> None:
    d = date or _today()
    vals = [metrics.get(k) for k in PEER_METRICS]
    _run(lambda c: c.execute(
        "INSERT OR REPLACE INTO metrics_snapshot VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (symbol.upper(), d, market, peer_group, sector, industry, *vals)))


def snapshot_count(date: str | None = None) -> int:
    d = date or _today()
    # Tarama satiri her analizde kiyas goruntusuyle birlikte yazilir; ikisinin de bugun var olmasi gerekir
    return int(_run(lambda c: c.execute(
        """SELECT COUNT(*) FROM metrics_snapshot m JOIN screen_rows r ON r.symbol=m.symbol AND r.date=m.date
           WHERE m.date=?""", (d,)).fetchone()[0]))


def peer_metrics(peer_group: str, exclude: str | None = None) -> tuple[dict[str, list[float]], int]:
    """
    Gruptaki her hissenin SON (<= PEER_MAX_AGE_DAYS gunluk) goruntusunden metrik listeleri.
    Donus: ({metrik: [degerler]}, hisse_sayisi)
    """
    since = (dt.date.today() - dt.timedelta(days=PEER_MAX_AGE_DAYS)).isoformat()

    def q(c):
        return c.execute(
            """SELECT m.* FROM metrics_snapshot m
               JOIN (SELECT symbol, MAX(date) d FROM metrics_snapshot WHERE peer_group=? AND date>=? GROUP BY symbol) x
               ON m.symbol=x.symbol AND m.date=x.d""", (peer_group, since)).fetchall()

    rows = [r for r in _run(q) if not (exclude and r["symbol"] == exclude.upper())]
    out: dict[str, list[float]] = {k: [float(r[k]) for r in rows if r[k] is not None] for k in PEER_METRICS}
    return out, len(rows)


def percentile_rank(value: float, population: Iterable[float], better: str) -> float | None:
    """0..1: 1 = grubun en iyisi. 'lower' metriklerde dusuk deger iyidir (sadece pozitif carpanlar)."""
    pop = [p for p in population if p is not None]
    if better == "lower":
        pop = [p for p in pop if p > 0]
        if value is None or value <= 0:
            return None
    if not pop or value is None:
        return None
    if better == "higher":
        worse = sum(1 for p in pop if p < value)
    else:
        worse = sum(1 for p in pop if p > value)
    ties = sum(1 for p in pop if p == value)
    return (worse + 0.5 * ties) / len(pop)


# ---------------------------------------------------------------- tarayici satirlari

def save_screen_row(symbol: str, market: str, row: dict[str, Any], date: str | None = None) -> None:
    d = date or _today()
    data = json.dumps(row, ensure_ascii=False, default=str)
    _run(lambda c: c.execute("INSERT OR REPLACE INTO screen_rows VALUES (?,?,?,?)", (symbol.upper(), d, market, data)))


def latest_screen_rows(market: str, max_age_days: int = 3) -> list[dict[str, Any]]:
    """Her hissenin son (<= max_age_days gunluk) tarama satiri; '_date' alani eklenir."""
    since = (dt.date.today() - dt.timedelta(days=max_age_days)).isoformat()

    def q(c):
        return c.execute(
            """SELECT r.symbol, r.date, r.payload FROM screen_rows r
               JOIN (SELECT symbol, MAX(date) d FROM screen_rows WHERE market=? AND date>=? GROUP BY symbol) x
               ON r.symbol=x.symbol AND r.date=x.d WHERE r.market=?""", (market, since, market)).fetchall()

    out = []
    for r in _run(q):
        try:
            row = json.loads(r["payload"])
        except Exception:
            continue
        row["_date"] = r["date"]
        out.append(row)
    return out


# ---------------------------------------------------------------- analiz onbellegi

def cache_get(key: str, ttl: float) -> dict[str, Any] | None:
    row = _run(lambda c: c.execute("SELECT saved_at, payload FROM analysis_cache WHERE key=?", (key,)).fetchone())
    if not row or (time.time() - row["saved_at"]) > ttl:
        return None
    try:
        return json.loads(row["payload"])
    except Exception:
        return None


def cache_set(key: str, payload: dict[str, Any]) -> None:
    data = json.dumps(payload, ensure_ascii=False, default=str)
    _run(lambda c: c.execute("INSERT OR REPLACE INTO analysis_cache VALUES (?,?,?)", (key, time.time(), data)))


# ---------------------------------------------------------------- uyarilar

def add_alert(symbol: str, kind: str, message: str, dedupe_key: str) -> bool:
    """Ayni dedupe_key ile ikinci kez uyari eklenmez. Eklendiyse True."""
    def ins(c):
        cur = c.execute("INSERT OR IGNORE INTO alerts (symbol, created_at, kind, message, dedupe_key) VALUES (?,?,?,?,?)",
                        (symbol.upper(), dt.datetime.now().isoformat(timespec="seconds"), kind, message, dedupe_key))
        return cur.rowcount > 0
    return bool(_run(ins))


def list_alerts(limit: int = 50, unseen_only: bool = False) -> list[dict[str, Any]]:
    sql = "SELECT * FROM alerts " + ("WHERE seen=0 " if unseen_only else "") + "ORDER BY id DESC LIMIT ?"
    return [dict(r) for r in _run(lambda c: c.execute(sql, (limit,)).fetchall())]


def mark_alerts_seen() -> int:
    return _run(lambda c: c.execute("UPDATE alerts SET seen=1 WHERE seen=0").rowcount)
