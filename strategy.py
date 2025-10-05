import pandas as pd
import pickle
import os
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.dummy import DummyClassifier
from sklearn.metrics import accuracy_score
import joblib

N_LAG = 5
MODEL_DIR = "weights"

# 🚀 КЭШ МОДЕЛЕЙ — ДОБАВЛЯЕМ!
_MODEL_CACHE = {}

def model_path(sym: str, tf: str) -> str:
    return f"{MODEL_DIR}/{sym.replace('-','')}_{tf}.pkl"

def load_model(sym: str, tf: str):
    key = (sym, tf)
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]

    p = model_path(sym, tf)
    if not os.path.exists(p):
        _MODEL_CACHE[key] = (None, None, 0.55)
        return None, None, 0.55

    try:
        with open(p, "rb") as f:
            obj = pickle.load(f)
        _MODEL_CACHE[key] = (obj["scaler"], obj["clf"], obj["thr"])
        return obj["scaler"], obj["clf"], obj["thr"]
    except Exception as e:
        print(f"[ERR] Failed to load model {p}: {e}")
        _MODEL_CACHE[key] = (None, None, 0.55)
        return None, None, 0.55

def save_model(sym, tf, scaler, clf, thr):
    os.makedirs(MODEL_DIR, exist_ok=True)
    with open(model_path(sym, tf), "wb") as f:
        pickle.dump({"scaler": scaler, "clf": clf, "thr": thr}, f)

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
    c, h, l, v = df["c"], df["h"], df["l"], df["v"]

    rsi_val = rsi(c, 14)
    atr_val = atr(df, 14)
    ema9 = c.ewm(span=9).mean()
    ema_dev = (c - ema9) / ema9
    vol_sma = v.rolling(20).mean()
    vol_ratio = v / (vol_sma + 1e-8)

    ind = pd.DataFrame({
        "rsi": rsi_val,
        "atr": atr_val,
        "ema_dev": ema_dev,
        "vol_r": vol_ratio,
    }).iloc[-N_LAG - 1:]

    feats = []
    for col in ind.columns:
        for lag in range(1, N_LAG + 1):
            feats.append(ind[col].shift(lag).iloc[-1])
        feats.append(ind[col].diff().iloc[-1])
    return pd.Series(feats, dtype=np.float32)

def micro_score(klines: list, sym: str, tf: str) -> dict:
    if len(klines) < N_LAG + 2:
        return {"long": 0.0, "short": 0.0, "atr_pc": 0.0}

    # если пришли словари – превращаем в список списков
    if klines and isinstance(klines[0], dict):
        klines = [[d["time"], d["open"], d["high"], d["low"], d["close"], d["volume"]] for d in klines]

    df = pd.DataFrame(klines, columns=["t", "o", "h", "l", "c", "v"]).astype(float)

    # 3. ATR(14) в процентах от цены закрытия
    atr14 = atr(df, 14)
    atr_pc = float(atr14 / (df["c"].iloc[-1] + 1e-8))
    print(f"[DBG] {sym} {tf}  atr14={atr14:.8f}  close={df['c'].iloc[-1]:.5f}  atr_pc={atr_pc:.5f}")
    if not np.isfinite(atr_pc):
        atr_pc = 0.0

    scaler, clf, thr = load_model(sym, tf)
    feat = micro_structure(df)

    # ---------------- DEBUG -----------------
    print(f"[DBG] {sym} {tf}  atr_pc={atr_pc:.5f}  thr={thr:.3f}  model={clf is not None}")
    # --------------------------------------

    if scaler is None or clf is None:
    rsi_now = rsi(df["c"], 14)
    if rsi_now < 30:
        long_raw, short_raw = 1.0, 0.0
        print(f"[DBG] {sym}  fallback RSI rule → OVERSOLD → LONG")
    elif rsi_now > 70:
        long_raw, short_raw = 0.0, 1.0
        print(f"[DBG] {sym}  fallback RSI rule → OVERBOUGHT → SHORT")
    else:
        long_raw, short_raw = 0.0, 0.0
        print(f"[DBG] {sym}  fallback RSI rule → NEUTRAL (30–70) → NO SIDE")
    return {"long": long_raw, "short": short_raw, "atr_pc": atr_pc}
    X = scaler.transform(feat.values.reshape(1, -1))
    prob = float(clf.predict_proba(X)[0, 1])

    long_raw  = float(prob > thr)
    short_raw = float(prob < 1 - thr)

    print(f"[DBG] {sym}  prob={prob:.3f}  long={long_raw}  short={short_raw}")
    return {"long": long_raw, "short": short_raw, "atr_pc": atr_pc}

async def train_one(sym: str, tf: str, bars: int = 1440):
    from exchange import BingXAsync
    async with BingXAsync(os.getenv("BINGX_API_KEY"), os.getenv("BINGX_SECRET_KEY")) as ex:
        klines = await ex.klines(sym, tf, bars)
    df = pd.DataFrame(klines, columns=["t","o","h","l","c","v"]).astype(float)

    X, y = [], []
    for i in range(N_LAG+1, len(df)-1):
        feat = micro_structure(df.iloc[i-N_LAG-1:i])
        target = 1 if df.iloc[i+1]["c"] > df.iloc[i]["c"] else 0
        X.append(feat.values)
        y.append(target)
    X, y = np.array(X), np.array(y)

    if len(np.unique(y)) < 2:
        clf = DummyClassifier(strategy="stratified")
    else:
        clf = LogisticRegression(max_iter=1000, class_weight="balanced")
    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)
    clf.fit(Xs, y)
    thr = max(0.52, clf.predict_proba(Xs)[:, 1].mean())
    save_model(sym, tf, scaler, clf, thr)
    print(f"✅ {sym} {tf}  acc={accuracy_score(y, clf.predict(Xs)):.2f}  thr={thr:.3f}")
