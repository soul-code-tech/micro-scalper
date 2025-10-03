import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression

N_LAG = 5          # сколько лагов каждой фичи
MODEL = {}         # символ -> (scaler, clf, thr)

def rsi(series: pd.Series, period: int = 14) -> float:
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / (loss + 1e-8)
    return float((100 - (100 / (1 + rs))).iloc[-1])

def atr(df: pd.DataFrame, period: int = 14) -> float:
    hl = df["h"] - df["l"]
    hc = (df["h"] - df["c"].shift()).abs()
    lc = (df["l"] - df["c"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])

def micro_structure(df: pd.DataFrame) -> pd.Series:
    """
    30 фичей: лаги + дельты для RSI, ATR, EMA-dev, vol-ratio
    """
    c, h, l, v = df["c"], df["h"], df["l"], df["v"]

    # базовые индикаторы
    rsi_val = rsi(c, 14)
    atr_val = atr(df, 14)
    ema9  = c.ewm(span=9).mean()
    ema21 = c.ewm(span=21).mean()
    ema_dev = (c - ema9) / ema9
    vol_sma = v.rolling(20).mean()
    vol_ratio = v / (vol_sma + 1e-8)

    # DataFrame для удобства лагов
    ind = pd.DataFrame({
        "rsi": rsi_val,
        "atr": atr_val,
        "ema_dev": ema_dev,
        "vol_r": vol_ratio,
    }).iloc[-N_LAG-1:]          # берём N_LAG+1 бар

    # строим лаги и дельты
    feats = []
    for col in ind.columns:
        for lag in range(1, N_LAG+1):
            feats.append(ind[col].shift(lag).iloc[-1])
        # дельта последнего шага
        feats.append(ind[col].diff().iloc[-1])

    return pd.Series(feats)     # 4*(N_LAG+1) = 30 чисел
