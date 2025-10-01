# strategy.py  (корень, pure-pandas)
import pandas as pd
import numpy as np

# ----------- вспомогательные функции -----------
def rsi(series: pd.Series, period: int = 14) -> float:
    delta = series.diff()
    gain  = delta.where(delta > 0, 0).rolling(period).mean()
    loss  = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs    = gain / (loss + 1e-8)
    return float((100 - (100 / (1 + rs))).iloc[-1])

def atr(df: pd.DataFrame, period: int = 14) -> float:
    hl = df["h"] - df["l"]
    hc = (df["h"] - df["c"].shift()).abs()
    lc = (df["l"] - df["c"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])

# ----------- основной скоринг -----------
def micro_score(klines: list) -> dict:
    """
    klines: [[t,o,h,l,c,v], ...]  – newest last
    returns {"long": 0-1, "short": 0-1, "atr_pc": float}
    """
    df = pd.DataFrame(klines, columns=["t", "o", "h", "l", "c", "v"]).astype(float)
    c  = df["c"]

    # индикаторы
    rsi_val = rsi(c, 14)
    atr_val = atr(df, 14)
    atr_pc  = atr_val / c.iloc[-1]
    ema9    = c.ewm(span=9).mean().iloc[-1]
    ema21   = c.ewm(span=21).mean().iloc[-1]
    vol_sma = df["v"].rolling(20).mean().iloc[-1]
    vol_ratio = df["v"].iloc[-1] / (vol_sma + 1e-8)

    # оценка направления
    long_score = 0.0
    if 45 < rsi_val < 65 and c.iloc[-1] > ema9 > ema21 and vol_ratio > 1.2:
        long_score = min(1.0, vol_ratio / 3)

    short_score = 0.0
    if 35 < rsi_val < 55 and c.iloc[-1] < ema9 < ema21 and vol_ratio > 1.2:
        short_score = min(1.0, vol_ratio / 3)

    return {"long": long_score, "short": short_score, "atr_pc": atr_pc}
