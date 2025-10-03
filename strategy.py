import pandas as pd
import pickle
import os

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

def feat_vector(klines: list) -> pd.Series:
    df = pd.DataFrame(klines, columns=["t", "o", "h", "l", "c", "v"]).astype(float)
    c, h, l, v = df["c"], df["h"], df["l"], df["v"]
    atr_pc = atr(df, 14) / c.iloc[-1]
    rsi_val = rsi(c, 14)
    ema9  = c.ewm(span=9).mean().iloc[-1]
    ema21 = c.ewm(span=21).mean().iloc[-1]
    vol_sma = v.rolling(20).mean().iloc[-1]
    vol_ratio = v.iloc[-1] / (vol_sma + 1e-8)
    return pd.Series([atr_pc, rsi_val, (c.iloc[-1] - ema9) / ema9, vol_ratio])

def load_model(sym_tf: str = "DOGEUSDT_5m"):
    """Загружает модель по имени символа и ТФ"""
    path = f"weights/{sym_tf}.pkl"
    if os.path.exists(path):
        with open(path, "rb") as f:
            return pickle.load(f)
    return None

def micro_score(klines: list, sym_tf: str = None) -> dict:
    model_data = load_model(sym_tf) if sym_tf else None
    fv = feat_vector(klines)
    atr_pc, rsi_val, ema_dev, vol_ratio = fv

    long_raw = short_raw = 0.0

    if model_data:
        # Используем ML-модель
        clf = model_data["clf"]
        thr = model_data.get("thr", 0.55)
        proba = clf.predict_proba([fv])[0][1]  # вероятность роста
        if proba > thr:
            long_raw = min(1.0, (proba - thr) * 3)
        elif proba < (1 - thr):
            short_raw = min(1.0, ((1 - proba) - thr) * 3)
    else:
        # Fallback на правила
        if 40 < rsi_val < 70 and ema_dev > 0 and vol_ratio > 0.6 and atr_pc >= 0.0001:
            long_raw = min(1.0, vol_ratio / 3)
        if 30 < rsi_val < 60 and ema_dev < 0 and vol_ratio > 0.6 and atr_pc >= 0.0001:
            short_raw = min(1.0, vol_ratio / 3)

    return {"long": long_raw, "short": short_raw, "atr_pc": atr_pc}
