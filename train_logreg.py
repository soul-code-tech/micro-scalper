#!/usr/bin/env python3
import os, pickle, pandas as pd, numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score

MODEL_FILE = "weights/BTCUSDT.pkl"
N_FEAT     = 4
LOOKBACK   = 20

# ---------- тех.индикаторы ----------
def rsi(series: pd.Series, period: int = 14) -> float:
    delta = series.diff()
    gain  = delta.where(delta > 0, 0).rolling(period).mean()
    loss  = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs    = gain / (loss + 1e-8)
    return float((100 - (100 / (1 + rs))).iloc[-1])

def feat_vector(klines: list) -> pd.Series:
    df = pd.DataFrame(klines, columns=["t", "o", "h", "l", "c", "v"]).astype(float)
    c, h, l, v = df["c"], df["h"], df["l"], df["v"]
    atr_pc = (h - l).mean() / c.iloc[-1]
    rsi_val = rsi(c, 14)
    ema9  = c.ewm(span=9).mean().iloc[-1]
    vol_sma = v.rolling(20).mean().iloc[-1]
    vol_ratio = v.iloc[-1] / (vol_sma + 1e-8)
    return pd.Series([atr_pc, rsi_val, (c.iloc[-1] - ema9) / ema9, vol_ratio])

# ---------- датасет ----------
def make_dataset(klines: list, lookback=20):
    df = pd.DataFrame(klines, columns=["t", "o", "h", "l", "c", "v"]).astype(float)
    feats, labels = [], []
    for i in range(lookback, len(df) - 1):
        fv = feat_vector(df.iloc[i - lookback:i].values.tolist())
        target = 1 if df.iloc[i + 1]["c"] > df.iloc[i]["c"] else 0
        feats.append(fv.values)
        labels.append(target)
    return np.array(feats), np.array(labels)

# ---------- обучение ----------
async def train(klines: list):
    X, y = make_dataset(klines, LOOKBACK)
    if len(np.unique(y)) < 2:
        print("⏭️  только один класс – пропуск")
        return

    clf = LogisticRegression(max_iter=1000, class_weight="balanced")
    clf.fit(X, y)
    acc = accuracy_score(y, clf.predict(X))
    print(f"✅ обучено {len(y)} примеров, accuracy = {acc:.3f}")

    os.makedirs("weights", exist_ok=True)
    with open(MODEL_FILE, "wb") as f:
        pickle.dump(clf, f)

# ---------- быстрый тест ----------
if __name__ == "__main__":
    import asyncio, exchange, os
    async def main():
        async with exchange.BingXAsync(
            os.getenv("BINGX_API_KEY"),
            os.getenv("BINGX_SECRET_KEY")
        ) as ex:
            klines = await ex.klines("BTC-USDT", "15m", 1500)
        await train(klines)
    asyncio.run(main())
