"""
Super Tarayici hazir filtrelerinin geriye donuk testi
====================================================

Her ay, O GUNE KADARKI veriyle her hisse icin teknik analiz ve para akisi skorlari hesaplanir;
filtrenin TEKNIK ve AKIS kosullarini saglayan hisselerin sonraki `--horizon` islem gunundeki
endekse gore fazla getirisi, tum gozlemlerle karsilastirilir.

* Bilanco kosullari test edilemez (Yahoo gecmise donuk bilanco vermez); bu kosullar raporda
  "test edilmedi" olarak listelenir. Yalnizca bilanco kosullarindan olusan filtreler atlanir.
* "Ayni ay farki": sinyal veren hissenin fazla getirisi eksi o ay tum hisselerin ortalama fazla
  getirisi. Piyasa zamanlamasini disarida birakip "secicilik" etkisini olcer.
* Sonuc `backend/data/screen_backtest.json` dosyasina yazilir ve arayuzde filtrenin yaninda gosterilir.

Sinirlamalar: hayatta kalma yanliligi, islem maliyeti yok, ortusen gozlemler.

Kullanim:
    python tools/backtest_tarayici.py --market bist
    python tools/backtest_tarayici.py --market us
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.money_flow import _compute_window_metrics, _period_return  # noqa: E402
from backend.reference_data import themes  # noqa: E402
from backend.screener import EVIDENCE_FILE, PRESETS, check  # noqa: E402
from backend.technical import analyze_technical  # noqa: E402
from tools.backtest_teknik import MIN_HISTORY, STEP, _download  # noqa: E402

TESTABLE = {"tech", "flow"}
MIN_SIGNALS = 20  # bundan az sinyal varsa sonuc "yetersiz orneklem" sayilir


def observations(symbols: list[str], market: str, horizon: int, period: str) -> list[dict]:
    bench_sym = "XU100.IS" if market == "bist" else "^GSPC"
    data = _download(symbols + [bench_sym], period)
    bench = data.pop(bench_sym, None)
    if bench is None:
        raise SystemExit(f"Endeks verisi ({bench_sym}) indirilemedi.")
    usdtry = _download(["USDTRY=X"], period).get("USDTRY=X", pd.DataFrame()) if market == "bist" else pd.DataFrame()

    rows: list[dict] = []
    for sym, df in data.items():
        for end in range(MIN_HISTORY, len(df) - horizon, STEP):
            hist = df.iloc[:end]
            as_of = hist.index[-1]
            b_hist = bench.loc[:as_of]
            bundle = {"history": hist, "benchmark": b_hist,
                      "usdtry": usdtry.loc[:as_of] if not usdtry.empty else usdtry,
                      "is_bist": market == "bist", "benchmark_name": "", "benchmark_symbol": bench_sym}
            try:
                t = analyze_technical(bundle, include_charts=False)
            except Exception:
                continue
            recent = hist.iloc[-130:]
            f1w = _compute_window_metrics(recent, _period_return(b_hist, 5), 5)["flow_score"]
            f1m = _compute_window_metrics(recent, _period_return(b_hist, 21), 21)["flow_score"]
            fwd_end = df.index[end - 1 + horizon]
            bw = bench["Close"].loc[as_of:fwd_end]
            if len(bw) < 2:
                continue
            stock_ret = (float(df["Close"].iloc[end - 1 + horizon]) / float(df["Close"].iloc[end - 1]) - 1) * 100
            bench_ret = (float(bw.iloc[-1]) / float(bw.iloc[0]) - 1) * 100
            rows.append({
                "symbol": sym, "date": as_of, "excess": stock_ret - bench_ret,
                "tech_score": t["score"], "flow_1w": f1w, "flow_1m": f1m,
                "minervini_passed": t["minervini"]["passed"], "vcp_ratio": t["volatility_risk"]["vcp_ratio"],
                "dist_high_pct": t["range_52w"]["dist_high_pct"], "rs": t["relative_strength"]["rs_score_est"],
                "rs_above_sma50": t["relative_strength"]["rs_above_sma50"], "above_avwap_low": t["avwap"]["above_low"],
            })
    return rows


def evaluate(rows: list[dict], horizon: int) -> dict:
    if not rows:
        return {}
    df = pd.DataFrame(rows)
    month = df["date"].dt.to_period("M")
    df["month_mean"] = df.groupby(month)["excess"].transform("mean")
    base = {"n": len(df), "mean": round(df["excess"].mean(), 2), "median": round(df["excess"].median(), 2),
            "hit_pct": round((df["excess"] > 0).mean() * 100, 1)}
    out = {}
    for p in PRESETS:
        tested = [c for c in p["conditions"] if c["kind"] in TESTABLE]
        untested = [c["label"] for c in p["conditions"] if c["kind"] not in TESTABLE]
        if not tested:
            out[p["key"]] = {"testable": False, "untested": untested,
                             "note": "Bu filtre yalnızca bilanço koşullarından oluşur; geriye dönük test edilemez."}
            continue
        mask = [all(check(r, c) is True for c in tested) for r in rows]
        sig = df[mask]
        res = {"testable": True, "tested": [c["label"] for c in tested], "untested": untested,
               "horizon_days": horizon, "baseline": base, "signals": int(len(sig))}
        if len(sig):
            res.update({
                "mean": round(sig["excess"].mean(), 2),
                "median": round(sig["excess"].median(), 2),
                "hit_pct": round((sig["excess"] > 0).mean() * 100, 1),
                "vs_month_mean": round((sig["excess"] - sig["month_mean"]).mean(), 2),
                "months_with_signal": int(sig["date"].dt.to_period("M").nunique()),
            })
        enough = len(sig) >= MIN_SIGNALS
        if not enough:
            verdict = "yetersiz örneklem"
        elif res["vs_month_mean"] > 2 and res["hit_pct"] > base["hit_pct"]:
            verdict = "endeksi ve evreni geçmiş"
        elif res["vs_month_mean"] < -2:
            verdict = "evrenin gerisinde kalmış"
        else:
            verdict = "belirgin fark yok"
        res["verdict"] = verdict
        out[p["key"]] = res
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Tarayici filtrelerinin geriye donuk testi")
    ap.add_argument("--market", choices=["us", "bist"], default="bist")
    ap.add_argument("--horizon", type=int, default=126)
    ap.add_argument("--period", default="5y")
    ap.add_argument("--no-save", action="store_true", help="Sonucu backend/data/screen_backtest.json'a yazma")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    symbols = sorted({s for syms in themes(args.market).values() for s in syms})
    print(f"{len(symbols)} hisse icin veri indiriliyor…")
    rows = observations(symbols, args.market, args.horizon, args.period)
    result = evaluate(rows, args.horizon)
    print(f"\nGozlem: {len(rows)} | Ufuk: {args.horizon} islem gunu | Piyasa: {args.market}")
    base = next((r["baseline"] for r in result.values() if r.get("baseline")), None)
    if base:
        print(f"Tum gozlemler: ort. fazla getiri {base['mean']}% | endeksi yenme %{base['hit_pct']}")
    for p in PRESETS:
        r = result.get(p["key"], {})
        if not r.get("testable"):
            print(f"- {p['name']}: test edilemez (yalnizca bilanco kosullari)")
            continue
        if not r.get("signals"):
            print(f"- {p['name']}: hic sinyal yok")
            continue
        print(f"- {p['name']}: {r['signals']} sinyal | ort. {r['mean']}% | medyan {r['median']}% | "
              f"yenme %{r['hit_pct']} | ayni ay farki {r['vs_month_mean']:+}% -> {r['verdict']}"
              + (f" | test edilmeyen: {', '.join(r['untested'])}" if r["untested"] else ""))

    if not args.no_save:
        try:
            current = json.loads(EVIDENCE_FILE.read_text(encoding="utf-8"))
        except Exception:
            current = {}
        for key, res in result.items():
            current.setdefault(key, {})[args.market] = res
        meta = current.setdefault("_meta", {})
        meta[args.market] = {"date": dt.date.today().isoformat(), "observations": len(rows),
                             "symbols": len(symbols), "period": args.period, "horizon_days": args.horizon}
        EVIDENCE_FILE.write_text(json.dumps(current, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nSonuc {EVIDENCE_FILE} dosyasina yazildi.")


if __name__ == "__main__":
    main()
