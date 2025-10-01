#!/usr/bin/env python3
import numpy as np, pandas as pd, os, pickle, logging, aiohttp, aiofiles
import tensorflow as tf
from sklearn.preprocessing import MinMaxScaler

log = logging.getLogger("lstm")

# ---------- скачивание одного файла ----------
async def download(url: str, dst: str):
    if os.path.exists(dst):
        return
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    async with aiohttp.ClientSession() as s:
        async with s.get(url) as r:
            r.raise_for_status()
            async with aiofiles.open(dst, "wb") as f:
                await f.write(await r.read())

# ---------- классы без изменений, кроме вызова download ----------
class MicroLSTM:
    def __init__(self, lookback=20):
        self.lb = lookback
        self.model = None
        self.scaler = MinMaxScaler()

    def build(self):
        self.model = tf.keras.Sequential([
            tf.keras.layers.Input(shape=(self.lb, 5)),
            tf.keras.layers.LSTM(32, return_sequences=True),
            tf.keras.layers.Dropout(0.2),
            tf.keras.layers.LSTM(16),
            tf.keras.layers.Dense(1, activation="sigmoid")
        ])
        self.model.compile(optimizer="adam", loss="binary_crossentropy", metrics=["accuracy"])

    # train / predict не трогали


class LSTMEnsemble:
    def __init__(self):
        self.model1 = MicroLSTM(20)
        self.model2 = MicroLSTM(40)

    def build_models(self):
        self.model1.build()
        self.model2.build()

    def save(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.model1.model.save_weights(path.replace(".pkl", ".m1.weights.h5"))
        self.model2.model.save_weights(path.replace(".pkl", ".m2.weights.h5"))
        with open(path, "wb") as f:
            pickle.dump({"scaler1": self.model1.scaler, "scaler2": self.model2.scaler}, f)

    @classmethod
    async def load_remote(cls, repo: str, symbol: str):
        """repo = 'owner/repo' """
        base = f"https://raw.githubusercontent.com/{repo}/weights"
        os.makedirs("weights", exist_ok=True)
        root = f"weights/{symbol.replace('-','')}"
        await download(f"{base}/{symbol.replace('-','')}.pkl", root+".pkl")
        await download(f"{base}/{symbol.replace('-','')}.m1.weights.h5", root+".m1.weights.h5")
        await download(f"{base}/{symbol.replace('-','')}.m2.weights.h5", root+".m2.weights.h5")
        # теперь обычный load
        obj = cls()
        obj.build_models()
        obj.model1.model.load_weights(root+".m1.weights.h5")
        obj.model2.model.load_weights(root+".m2.weights.h5")
        with open(root+".pkl", "rb") as f:
            bundle = pickle.load(f)
        obj.model1.scaler = bundle["scaler1"]
        obj.model2.scaler = bundle["scaler2"]
        return obj


# ---------- глобальная обёртка (ТОЛЬКО async) ----------
async def predict_ensemble(klines: list) -> float:
    repo = os.getenv("GITHUB_REPOSITORY", "YOUR_NAME/YOUR_REPO")
    symbol = "BTC-USDT"   # пока один универсальный файл
    try:
        model = await LSTMEnsemble.load_remote(repo, symbol)
        return model.predict_proba(klines)
    except Exception as e:
        log.warning("LSTM load/inf err: %s – return 0.5", e)
        return 0.5
