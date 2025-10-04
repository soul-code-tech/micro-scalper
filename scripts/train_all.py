#!/usr/bin/env python3
"""
Переобучение лог-рег на последних 3000 баров для всех тайм-фреймов
"""
import asyncio
import pickle
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sklearn.linear_model import LogisticRegression
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from exchange import BingXAsync
def feat_vector(klines: list) -> pd.Series:
    import pandas as pd
    import numpy as np
    
    df = pd.DataFrame(klines, columns=["t", "o", "h", "l", "c", "v"]).astype(float)
    c, h, l, v = df["c"], df["h"], df["l"], df["v"]
    atr_pc = (h - l).mean() / c.iloc[-1]
    rsi_val = rsi(c, 14)
    ema9 = c.ewm(span=9).mean().iloc[-1]
    vol_sma = v.rolling(20).mean().iloc[-1]
    vol_ratio = v.iloc[-1] / (vol_sma + 1e-8)
    out = pd.Series([atr_pc, rsi_val, (c.iloc[-1] - ema9) / ema9, vol_ratio])
    return out.replace([np.inf, -np.inf], np.nan).fillna(0.0)

SYMBOLS = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "DOGE-USDT"]
BARS = 1440
TIME_FRAMES = ["1m", "3m", "5m", "15m"]   # обучаем на всех ТФ

def rsi(series: pd.Series, period: int = 14) -> float:
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / (loss + 1e-8)
    return float((100 - (100 / (1 + rs))).iloc[-1])

async def train_one(sym: str, tf: str):
    async with BingXAsync(os.getenv("BINGX_API_KEY"), os.getenv("BINGX_SECRET_KEY")) as ex:
        klines = await ex.klines(sym, tf, BARS)
    X, y = [], []
    df = pd.DataFrame(klines, columns=["t", "o", "h", "l", "c", "v"]).astype(float)
    for i in range(50, len(df) - 1):
        fv = feat_vector(df.iloc[i - 50:i].values.tolist())
        target = 1 if df.iloc[i + 1]["c"] > df.iloc[i]["c"] else 0
        X.append(fv.values)
        y.append(target)
    X, y = np.array(X), np.array(y)
    if len(np.unique(y)) < 2:
        from sklearn.dummy import DummyClassifier
        clf = DummyClassifier(strategy="most_frequent")
        thr = 0.55
    else:
        clf = LogisticRegression(max_iter=1000)
        clf.fit(X, y)
        prob = clf.predict_proba(X)[:, 1]
        thr = max(0.52, prob.mean())   # реальный порог

    # после thr = max(0.52, prob.mean())
    os.makedirs("weights", exist_ok=True)
    with open(f"weights/{sym.replace('-', '')}_{tf}.pkl", "wb") as f:
        pickle.dump({"clf": clf, "thr": thr}, f)

async def main():
    print("🚀 Walk-forward train (3000 bars, all TF)")
    for s in SYMBOLS:
        for tf in TIME_FRAMES:
            await train_one(s, tf)

if __name__ == "__main__":
    asyncio.run(main())
