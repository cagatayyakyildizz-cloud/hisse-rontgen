"""
Teknik puan agirliklarinin kalibrasyon denemesi (orneklem disi dogrulamali).

Once geriye donuk test gozlemlerini CSV'ye yazin:
    python tools/backtest_teknik.py --market us --components --csv bt_us.csv
    python tools/backtest_teknik.py --market bist --components --csv bt_bist.csv
Sonra:
    python tools/kalibrasyon.py "bt_{m}.csv"

Yontem: Veri tarihe gore ikiye bolunur. Ilk yarida her kalemin aylik bilgi katsayisina (IC) gore
agirlik onerilir, ikinci yarida (orneklem disi) eski ve yeni agirliklar karsilastirilir. Yeni agirliklar
orneklem disinda belirgin sekilde daha iyi DEGILSE degistirilmemelidir (asiri uyum riski).
Sonuclar docs/BACKTEST.md dosyasinda.
"""
import sys
import pandas as pd
import numpy as np

ORIG = {"minervini": 30, "weinstein": 15, "rs_level": 12, "rs_trend": 3, "avwap_low": 5, "avwap_high_ytd": 4,
        "vcp": 3, "volume": 3, "regime": 5, "confirm": 5, "rsi": 5, "macd": 5, "extension": 5}
# Piyasa geneli (hisseye ozgu olmayan) kalemler hisseler arasi siralamaya katki yapmaz -> 0
MARKET_LEVEL = {"us": {"regime", "confirm"}, "bist": {"regime"}}
BLEND = 0.7  # IC tabanli agirlik payi; kalan pay orijinal (onsel) agirlik


def monthly_ic(df, col):
    vals = []
    for _, g in df.groupby(df["date"].dt.to_period("M")):
        g = g[[col, "excess"]].dropna()
        if len(g) >= 8 and g[col].nunique() > 1:
            vals.append(g[col].rank().corr(g["excess"].rank()))
    return float(np.mean(vals)) if vals else 0.0


def fit(df, market):
    comps = [c for c in ORIG if c in df.columns]
    usable = [c for c in comps if c not in MARKET_LEVEL[market]]
    ics = {c: monthly_ic(df, c) for c in usable}
    pos = {c: max(v, 0.0) for c, v in ics.items()}
    s_ic = sum(pos.values()) or 1.0
    s_or = sum(ORIG[c] for c in usable)
    w = {c: BLEND * pos[c] / s_ic + (1 - BLEND) * ORIG[c] / s_or for c in usable}
    # Tutarli olarak negatif IC'li kalemlerin onsel payini da sil
    for c, v in ics.items():
        if v < 0:
            w[c] = 0.0
    tot = sum(w.values())
    return {c: round(100 * w.get(c, 0.0) / tot, 1) for c in comps}, ics


def score(df, weights):
    num = sum(df[c].fillna(0) * weights[c] for c in weights)
    den = sum(df[c].notna() * weights[c] for c in weights)
    return 100 * num / den.replace(0, np.nan)


def evaluate(df, weights, label):
    d = df.copy()
    d["s"] = score(d, weights)
    ic = monthly_ic(d, "s")
    b = pd.cut(d["s"], [-1, 40, 65, 101], labels=["<40", "40-64", ">=65"])
    g = d.groupby(b, observed=True)["excess"].agg(["count", "mean", "median", lambda x: (x > 0).mean() * 100])
    g.columns = ["n", "mean", "median", "hit%"]
    print(f"  {label}: aylik IC {ic:.3f}")
    print(g.round(2).to_string().replace("\n", "\n    "))


for market in ("us", "bist"):
    df = pd.read_csv(sys.argv[1].format(m=market), parse_dates=["date"])
    dates = sorted(df["date"].unique())
    cut = dates[len(dates) // 2]
    train, test = df[df["date"] < cut], df[df["date"] >= cut]
    w_train, ic_train = fit(train, market)
    print(f"\n===== {market.upper()} | egitim < {pd.Timestamp(cut).date()} <= test")
    print("  egitim IC:", {k: round(v, 3) for k, v in ic_train.items()})
    print("  egitim agirliklari:", w_train)
    print(" TEST (orneklem disi):")
    evaluate(test, {k: float(v) for k, v in ORIG.items()}, "eski agirliklar")
    evaluate(test, w_train, "yeni agirliklar")
    w_full, ic_full = fit(df, market)
    print("  TAM VERI agirliklari:", w_full)
