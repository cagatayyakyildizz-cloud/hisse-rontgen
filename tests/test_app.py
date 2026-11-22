"""API uc noktalari: izleme listesi kilidi/atomik yazma, dogrulama ve karsilastirma siniri."""
import json
import threading

import pytest
from fastapi.testclient import TestClient

import backend.app as app_module


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "WATCHLIST_FILE", tmp_path / "watchlist.json")
    monkeypatch.setattr(app_module, "resolve_symbol", lambda s, m="auto": (s.upper(), False))

    def fake_row(symbol, market="auto"):
        if symbol.upper() == "BOZUK":
            raise ValueError("veri yok")
        return {"symbol": symbol.upper(), "display_symbol": symbol.upper()}

    monkeypatch.setattr(app_module, "build_summary_row", fake_row)
    return TestClient(app_module.app)


def test_invalid_symbol_is_rejected(client):
    assert client.post("/api/watchlist", json={"symbol": "<script>", "market": "us"}).status_code == 422
    assert client.post("/api/watchlist", json={"symbol": "AAPL", "market": "mars"}).status_code == 422
    assert client.get("/api/analyze/" + "A" * 30).status_code == 422


def test_watchlist_add_remove_roundtrip(client):
    client.get("/api/watchlist")  # varsayilan liste olusur
    r = client.post("/api/watchlist", json={"symbol": "msft", "market": "us"})
    assert r.status_code == 200 and r.json()["added"] == "MSFT"
    r = client.delete("/api/watchlist/MSFT")
    assert all(x["symbol"] != "MSFT" for x in r.json()["items"])
    # Dosya gecerli JSON olarak kalmali (atomik yazma)
    data = json.loads(app_module.WATCHLIST_FILE.read_text(encoding="utf-8"))
    assert isinstance(data, list)


def test_concurrent_adds_are_not_lost(client):
    client.get("/api/watchlist")
    symbols = [f"T{i}" for i in range(15)]

    def add(sym):
        client.post("/api/watchlist", json={"symbol": sym, "market": "us"})

    threads = [threading.Thread(target=add, args=(s,)) for s in symbols]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    saved = {x["symbol"] for x in client.get("/api/watchlist").json()["items"]}
    assert set(symbols) <= saved


def test_compare_reports_skipped_and_errors(client):
    items = [{"symbol": f"S{i}", "market": "us"} for i in range(app_module.MAX_COMPARE + 3)]
    items[0]["symbol"] = "BOZUK"
    body = client.post("/api/compare", json={"items": items}).json()
    assert body["limit"] == app_module.MAX_COMPARE
    assert len(body["skipped"]) == 3
    assert [e["symbol"] for e in body["errors"]] == ["BOZUK"]
    assert len(body["rows"]) == app_module.MAX_COMPARE - 1


def test_history_and_alert_endpoints(client):
    from backend import storage

    storage.record_scores("MSFT", 70, 60, 80, 2, 400.0, 100, date="2026-11-20")
    body = client.get("/api/history/MSFT").json()
    assert body["history"][0]["composite"] == 70
    storage.add_alert("MSFT", "stage", "MSFT: evre degisti", "k1")
    alerts = client.get("/api/alerts").json()
    assert alerts["unseen"] == 1 and alerts["items"][0]["symbol"] == "MSFT"
    assert client.post("/api/alerts/seen").json()["updated"] == 1
    assert client.get("/api/alerts?unseen=true").json()["items"] == []
    assert client.get("/api/history/%3Cx%3E").status_code == 422
