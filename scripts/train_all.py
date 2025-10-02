#!/usr/bin/env python3
"""
Переобучение лог-рег каждые 2 мес на последних 3000 баров
"""
import os, sys, asyncio, pickle, datetime as dt
from sklearn.linear_model import LogisticRegression
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from exchange import BingXAsync
from strategy import feat_vector

SYMBOLS = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "DOGE-USDT"]
BARS = 3000          # последние 3 000 бар
MONTHS = 2           # переобучаем каждые 2 мес

async def train_one(sym: str, tf: str = "15m"):
    async with BingXAsync(os.getenv("BINGX_API_KEY"), os.getenv("BINGX_SECRET_KEY")) as ex:
        klines = await ex.klines(sym, tf, BARS)
    # строим X, y
    X, y = [], []
    df = pd.DataFrame(klines, columns=["t", "o", "h", "l", "c", "v"]).astype(float)
    for i in range(50, len(df) - 1):
        fv = feat_vector(df.iloc[i - 50:i].values.tolist())
        target = 1 if df.iloc[i + 1]["c"] > df.iloc[i]["c"] else 0
        X.append(fv.values)
        y.append(target)
    X, y = np.array(X), np.array(y)
    if len(np.unique(y)) < 2:
        print(f"⏭️  {sym} single class – skip")
        return

    clf = LogisticRegression(max_iter=1000)
    clf.fit(X, y)
    os.makedirs("weights", exist_ok=True)
    with open(f"weights/{sym.replace('-', '')}.pkl", "wb") as f:
        pickle.dump({"clf": clf, "thr": 0.55}, f)
    print(f"✅ {sym} updated")

async def main():
    print("🚀 Walk-forward train (3000 bars)")
    for s in SYMBOLS:
        await train_one(s)

if __name__ == "__main__":
    asyncio.run(main())
