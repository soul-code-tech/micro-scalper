import pandas as pd
import numpy as np

def rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / (loss + 1e-8)
    return 100 - (100 / (1 + rs))

def atr(df, period=14):
    hl = df["h"] - df["l"]
    hc = (df["h"] - df["c"].shift()).abs()
    lc = (df["l"] - df["c"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def micro_score(klines: list, sym: str, tf: str) -> dict:
    if len(klines) < 20:
        return {"long": 0.0, "short": 0.0, "atr_pc": 0.0}

    if isinstance(klines[0], dict):
        klines = [[d["time"], d["open"], d["high"], d["low"], d["close"], d["volume"]] for d in klines]

    df = pd.DataFrame(klines, columns=["t", "o", "h", "l", "c", "v"]).astype(float)
    df.columns = ["t", "o", "h", "l", "c", "v"]

    atr_val = atr(df, 14).iloc[-1]
    atr_pc = atr_val / (df["c"].iloc[-1] + 1e-8)

    rsi_val = rsi(df["c"], 14).iloc[-1]
    if rsi_val < 45:
        return {"long": 1.0, "short": 0.0, "atr_pc": atr_pc}
    elif rsi_val > 65:
        return {"long": 0.0, "short": 1.0, "atr_pc": atr_pc}
    else:
        return {"long": 0.0, "short": 0.0, "atr_pc": atr_pc}
