"""
Teknik Puan Geriye Donuk Testi
==============================

Soru: Gecmiste Teknik Puani yuksek cikan hisseler, sonraki N islem gununde endeksi yendi mi?

Yontem
------
* Her hisse icin 5 yillik gunluk veri indirilir.
* Ayda bir (yaklasik 21 islem gunu arayla) O GUNE KADARKI veriyle `analyze_technical` calistirilir
  (ileriye bakma yok: sadece o tarihe kadar olan fiyatlar kullanilir).
* Her gozlem icin sonraki `--horizon` islem gunundeki getiri, ayni donemdeki endeks getirisiyle kiyaslanir.
* Gozlemler puan araligina gore gruplanir: ortalama / medyan fazla getiri ve endeksi yenme orani raporlanir.

Sinirlamalar (sonuclari yorumlarken MUTLAKA dikkate alin)
---------------------------------------------------------
* Sadece TEKNIK puan test edilir. Yahoo gecmise donuk ("point-in-time") bilanco vermedigi icin
  bilanco puani ve bilesik puan bu yontemle dogru test edilemez.
* Hayatta kalma yanliligi: Tema listeleri BUGUN islem goren hisselerden olusur; batmis veya
  kotasyondan cikmis hisseler testte yoktur. Sonuclar gercekte oldugundan iyi gorunebilir.
* Islem maliyeti, kayma ve vergi yoktur. Gozlemler birbirinden bagimsiz degildir (ust uste binen donemler).

Kullanim
--------
    python -m tools.backtest_teknik --market us
    python -m tools.backtest_teknik --market bist --horizon 63
    python -m tools.backtest_teknik --symbols AAPL,MSFT,NVDA --market us
"""
from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.reference_data import themes  # noqa: E402
from backend.technical import analyze_technical  # noqa: E402

MIN_HISTORY = 260      # 200 SMA + 52 hafta penceresi icin gereken en az bar
STEP = 21              # yaklasik aylik ornekleme
BUCKETS = [(0, 40, "Zayıf (<40)"), (40, 65, "Orta (40–64)"), (65, 101, "Güçlü (≥65)")]


def _download(symbols: list[str], period: str) -> dict[str, pd.DataFrame]:
    raw = yf.download(symbols, period=period, interval="1d", group_by="ticker",
                      auto_adjust=True, threads=True, progress=False)
    out: dict[str, pd.DataFrame] = {}
    for s in symbols:
        try:
            df = raw[s].copy() if isinstance(raw.columns, pd.MultiIndex) else raw.copy()
        except KeyError:
            continue
        df = df.dropna(subset=["Close"])
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        if len(df) > MIN_HISTORY:
            out[s] = df
    return out


def run(symbols: list[str], market: str, horizon: int, period: str) -> list[dict]:
    bench_sym = "XU100.IS" if market == "bist" else "^GSPC"
    data = _download(symbols + [bench_sym], period)
    bench = data.pop(bench_sym, None)
    if bench is None:
        raise SystemExit(f"Endeks verisi ({bench_sym}) indirilemedi.")

    usdtry = pd.DataFrame()
    if market == "bist":
        usdtry = _download(["USDTRY=X"], period).get("USDTRY=X", pd.DataFrame())

    rows: list[dict] = []
    for sym, df in data.items():
        for end in range(MIN_HISTORY, len(df) - horizon, STEP):
            hist = df.iloc[:end]
            as_of = hist.index[-1]
            bundle = {
                "history": hist,
                "benchmark": bench.loc[:as_of],
                "usdtry": usdtry.loc[:as_of] if not usdtry.empty else usdtry,
                "is_bist": market == "bist",
                "benchmark_name": "BIST 100" if market == "bist" else "S&P 500",
                "benchmark_symbol": bench_sym,
            }
            try:
                score = analyze_technical(bundle)["score"]
            except Exception as exc:  # tek bir tarihteki veri sorunu testi durdurmasin
                print(f"  ! {sym} {as_of.date()}: {exc}", file=sys.stderr)
                continue
            p0, p1 = float(df["Close"].iloc[end - 1]), float(df["Close"].iloc[end - 1 + horizon])
            fwd_end = df.index[end - 1 + horizon]
            b_window = bench["Close"].loc[as_of:fwd_end]
            if len(b_window) < 2:
                continue
            stock_ret = (p1 / p0 - 1) * 100
            bench_ret = (float(b_window.iloc[-1]) / float(b_window.iloc[0]) - 1) * 100
            rows.append({"symbol": sym, "date": as_of, "score": score,
                         "ret": stock_ret, "excess": stock_ret - bench_ret})
    return rows


def report(rows: list[dict], horizon: int) -> None:
    if not rows:
        print("Gozlem yok.")
        return
    print(f"\nToplam gozlem: {len(rows)} | Hisse: {len({r['symbol'] for r in rows})} | Ufuk: {horizon} islem gunu\n")
    print(f"{'Puan Aralığı':<16}{'Gözlem':>8}{'Ort. Fazla Getiri':>20}{'Medyan':>10}{'Endeksi Yenme':>16}")
    for lo, hi, name in BUCKETS:
        grp = [r for r in rows if lo <= r["score"] < hi]
        if not grp:
            print(f"{name:<16}{0:>8}")
            continue
        ex = [r["excess"] for r in grp]
        hit = sum(1 for x in ex if x > 0) / len(ex) * 100
        print(f"{name:<16}{len(grp):>8}{statistics.mean(ex):>19.2f}%{statistics.median(ex):>9.2f}%{hit:>15.1f}%")
    print("\nYorum: 'Güçlü' grubun ortalama fazla getirisi ve endeksi yenme orani 'Zayıf' gruptan belirgin "
          "yuksek degilse, puan esikleri ve agirliklari yeniden gozden gecirilmelidir. "
          "Sinirlamalar icin dosyanin basindaki aciklamaya bakin.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Teknik puanin geriye donuk testi")
    ap.add_argument("--market", choices=["us", "bist"], default="us")
    ap.add_argument("--symbols", help="Virgulle ayrilmis semboller (varsayilan: tema listesindeki tum hisseler)")
    ap.add_argument("--horizon", type=int, default=126, help="Ileri getiri ufku, islem gunu (varsayilan 126 ~ 6 ay)")
    ap.add_argument("--period", default="5y", help="Indirilecek veri suresi (varsayilan 5y)")
    args = ap.parse_args()
    # Windows konsolunda (cp1254) Turkce/ozel karakterler hata vermesin
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    else:
        symbols = sorted({s for syms in themes(args.market).values() for s in syms})
    print(f"{len(symbols)} hisse icin veri indiriliyor…")
    report(run(symbols, args.market, args.horizon, args.period), args.horizon)


if __name__ == "__main__":
    main()
