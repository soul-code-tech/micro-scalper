#!/usr/bin/env python3
"""
Переобучение лог-рег на последних 3000 баров для всех тайм-фреймов
"""
import os, sys, asyncio, pickle, datetime as dt
from sklearn.linear_model import LogisticRegression
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from exchange import BingXAsync
from strategy import feat_vector

SYMBOLS = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "DOGE-USDT"]
BARS = 1440
TIME_FRAMES = ["1m", "3m", "5m", "15m"]   # обучаем на всех ТФ

async def train_one(sym: str, tf: str):
    async with BingXAsync(os.getenv("BINGX_API_KEY"), os.getenv("BINGX_SECRET_KEY")) as ex:
        klines = await ex.klines(sym, tf, BARS)
    X, y = [], []
    df = pd.DataFrame(klines, columns=["t", "o", "h", "l", "c", "v"]).astype(float)
    FEE = 0.0004  # 0.04 % одна сторона
    for i in range(50, len(df) - 1):
        fv = feat_vector(df.iloc[i - 50:i].values.tolist())
        price_now = df.iloc[i]["c"]
        price_next = df.iloc[i + 1]["c"]
        net_change = (price_next - price_now) / price_now
        target = 1 if net_change > 2 * FEE else 0
        X.append(fv.values)
        y.append(target)
    X, y = np.array(X), np.array(y)
    if len(np.unique(y)) < 2:
        print(f"⏭️  {sym} {tf} single class – skip")
        return
    clf = LogisticRegression(max_iter=1000)
    clf.fit(X, y)
    os.makedirs("weights", exist_ok=True)
    with open(f"weights/{sym.replace('-', '')}_{tf}.pkl", "wb") as f:
        pickle.dump({"clf": clf, "thr": 0.55}, f)
    print(f"✅ {sym} {tf} updated")

async def main():
    print("🚀 Walk-forward train (3000 bars, all TF)")
    for s in SYMBOLS:
        for tf in TIME_FRAMES:
            await train_one(s, tf)

if __name__ == "__main__":
    asyncio.run(main())
