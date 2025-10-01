import numpy as np, pandas as pd, os, tensorflow as tf, logging
from sklearn.preprocessing import MinMaxScaler

log = logging.getLogger("lstm")

class MicroLSTM:
    def __init__(self, lookback=60):
        self.lb   = lookback
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

    def train(self, klines: list, epochs=3, symbol="SYM"):
        df = pd.DataFrame(klines, columns=["t","o","h","l","c","v"]).astype(float)
        # фильтр волатильности
        atr_pc = (df["h"] - df["l"]).div(df["c"]).mean()
        if atr_pc < 0.0015:
            raise ValueError(f"low volatility {symbol}")

        feat = df[["o","h","l","c","v"]].values
        scaled = self.scaler.fit_transform(feat)

        X, y = [], []
        for i in range(self.lb, len(scaled)-1):
            X.append(scaled[i-self.lb:i])
            y.append(1.0 if scaled[i+1,3] > scaled[i,3] else 0.0)

        y = np.array(y)
        if len(np.unique(y)) < 2:
            raise ValueError(f"single class {symbol}")

        X = np.array(X).reshape((len(X), self.lb, 5))
        self.model.fit(X, y, epochs=epochs, batch_size=32, verbose=0)

    def predict(self, klines: list) -> float:
        df = pd.DataFrame(klines, columns=["t","o","h","l","c","v"]).astype(float)
        feat = df[["o","h","l","c","v"]].values
        scaled = self.scaler.transform(feat)
        last = scaled[-self.lb:].reshape(1, self.lb, 5)
        return float(self.model.predict(last, verbose=0)[0,0])


class LSTMEnsemble:
    def __init__(self):
        self.model1 = MicroLSTM(60)
        self.model2 = MicroLSTM(120)

    def build_models(self):
        self.model1.build()
        self.model2.build()

    def train(self, klines: list, epochs=3, symbol="SYM"):
        try:
            self.model1.train(klines, epochs, symbol)
            self.model2.train(klines, epochs, symbol)
        except ValueError as e:
            # пропускаем пару
            log.warning(e)
            return
        self.is_trained = True

    def predict_proba(self, klines: list) -> float:
        p1 = self.model1.predict(klines)
        p2 = self.model2.predict(klines)
        return (p1 + p2) / 2.0

    def save(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.model1.model.save_weights(path.replace(".pkl", ".m1.weights.h5"))
        self.model2.model.save_weights(path.replace(".pkl", ".m2.weights.h5"))
        import pickle
        with open(path, "wb") as f:
            pickle.dump({"scaler1": self.model1.scaler, "scaler2": self.model2.scaler}, f)

    @classmethod
    def load(cls, path: str):
        if not (os.path.exists(path) and
                os.path.exists(path.replace(".pkl", ".m1.weights.h5")) and
                os.path.exists(path.replace(".pkl", ".m2.weights.h5"))):
            return None
        obj = cls()
        obj.build_models()
        obj.model1.model.load_weights(path.replace(".pkl", ".m1.weights.h5"))
        obj.model2.model.load_weights(path.replace(".pkl", ".m2.weights.h5"))
        with open(path, "rb") as f:
            bundle = pickle.load(f)
        obj.model1.scaler = bundle["scaler1"]
        obj.model2.scaler = bundle["scaler2"]
        obj.is_trained = True
        return obj
