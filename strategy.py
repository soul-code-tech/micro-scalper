import pandas as pd
import numpy as np
from talib import RSI, ATR

def micro_score(klines: list) -> dict:
    df = pd.DataFrame(klines, columns=["t","o","h","l","c","v"]).astype(float)
    c = df["c"]
    rsi = RSI(c, timeperiod=14).iloc[-1]
    atr = ATR(df["h"], df["l"], df["c"], timeperiod=14).iloc[-1]
    atr_pc = atr / c.iloc[-1]
    ema9 = c.ewm(span=9).mean().iloc[-1]
    ema21 = c.ewm(span=21).mean().iloc[-1]
    vol_sma = df["v"].rolling(20).mean().iloc[-1]
    vol_ratio = df["v"].iloc[-1] / (vol_sma + 1e-8)

    long_score = 0.0
    if 45 < rsi < 65 and c.iloc[-1] > ema9 > ema21 and vol_ratio > 1.2:
        long_score = min(1.0, vol_ratio/3)
    short_score = 0.0
    if 35 < rsi < 55 and c.iloc[-1] < ema9 < ema21 and vol_ratio > 1.2:
        short_score = min(1.0, vol_ratio/3)
    return dict(long=long_score, short=short_score, atr_pc=atr_pc)
