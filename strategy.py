import pandas as pd

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

def micro_score(klines: list) -> dict:
    df = pd.DataFrame(klines, columns=["t","o","h","l","c","v"]).astype(float)
    c  = df["c"]
    rsi_val = rsi(c, 14)
    atr_val = atr(df, 14)
    atr_pc  = atr_val / c.iloc[-1]
    ema9    = c.ewm(span=9).mean().iloc[-1]
    ema21   = c.ewm(span=21).mean().iloc[-1]
    vol_sma = df["v"].rolling(20).mean().iloc[-1]
    vol_ratio = df["v"].iloc[-1] / (vol_sma + 1e-8)

    long_score = 0.0
    if 45 < rsi_val < 65 and c.iloc[-1] > ema9 > ema21 and vol_ratio > 1.2 and atr_pc >= 0.0015:
        long_score = min(1.0, vol_ratio / 3)
    short_score = 0.0
    if 35 < rsi_val < 55 and c.iloc[-1] < ema9 < ema21 and vol_ratio > 1.2 and atr_pc >= 0.0015:
        short_score = min(1.0, vol_ratio / 3)
    return {"long": long_score, "short": short_score, "atr_pc": atr_pc}
