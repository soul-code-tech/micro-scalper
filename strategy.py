import pandas as pd
import pickle
import os

MODEL_PATH = "weights/BTCUSDT.pkl"

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
    # 4 фичи
    return pd.Series([atr_pc, rsi_val, (c.iloc[-1] - ema9) / ema9, vol_ratio])

def load_model():
    if not os.path.exists(MODEL_PATH):
        return None
    with open(MODEL_PATH, "rb") as f:
        return pickle.load(f)   # dict{clf, thr}

def micro_score(klines: list) -> dict:
    model = load_model()
    fv = feat_vector(klines)
    atr_pc, rsi_val, ema_dev, vol_ratio = fv
    long_raw = 0.0
    if 45 < rsi_val < 65 and ema_dev > 0 and vol_ratio > 1.0 and atr_pc >= 0.0004:
        long_raw = min(1.0, vol_ratio / 3)
    short_raw = 0.0
    if 35 < rsi_val < 55 and ema_dev < 0 and vol_ratio > 1.0 and atr_pc >= 0.0004:
        short_raw = min(1.0, vol_ratio / 3)

    # если есть модель – улучшаем
    if model:
        X = fv.values.reshape(1, -1)
        prob = model["clf"].predict_proba(X)[0, 1]
        if prob > model["thr"]:
            long_raw = max(long_raw, prob * 0.8)
        elif prob < 1 - model["thr"]:
            short_raw = max(short_raw, (1 - prob) * 0.8)

    return {"long": long_raw, "short": short_raw, "atr_pc": atr_pc}
