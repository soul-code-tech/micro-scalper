import numpy as np, pandas as pd, pickle, os, tensorflow as tf
from sklearn.preprocessing import MinMaxScaler

class MicroLSTM:
    def __init__(self, lookback=60):
        self.lb = lookback
        self.model = None
        self.scaler = MinMaxScaler()

    def build(self):
        self.model = tf.keras.Sequential([
            tf.keras.layers.LSTM(32, return_sequences=True, input_shape=(self.lb, 5)),
            tf.keras.layers.Dropout(0.2),
            tf.keras.layers.LSTM(16),
            tf.keras.layers.Dense(1, activation="sigmoid")
        ])
        self.model.compile(optimizer="adam", loss="binary_crossentropy", metrics=["accuracy"])

    def train(self, klines: list, epochs=3):
        df = pd.DataFrame(klines, columns=["t","o","h","l","c","v"]).astype(float)
        feat = df[["o","h","l","c","v"]].values
        scaled = self.scaler.fit_transform(feat)
        X, y = [], []
        for i in range(self.lb, len(scaled)-1):
            X.append(scaled[i-self.lb:i])
            y.append(1.0 if scaled[i+1,3] > scaled[i,3] else 0.0)
        X, y = np.array(X), np.array(y)
        if len(np.unique(y)) < 2:
            raise ValueError("single class")
        self.model.fit(X, y, epochs=epochs, batch_size=32, verbose=0)

    def predict(self, klines: list) -> float:
        df = pd.DataFrame(klines, columns=["t","o","h","l","c","v"]).astype(float)
        feat = df[["o","h","l","c","v"]].values
        scaled = self.scaler.transform(feat)
        last = scaled[-self.lb:].reshape(1, self.lb, 5)
        return float(self.model.predict(last, verbose=0)[0,0])

def predict_ensemble(klines: list) -> float:
    m1, m2 = MicroLSTM(60), MicroLSTM(120)
    try:
        m1.build(); m2.build()
        m1.model.load_weights("weights/BTCUSDT.m1.weights.h5")
        m2.model.load_weights("weights/BTCUSDT.m2.weights.h5")
        p1 = m1.predict(klines)
        p2 = m2.predict(klines)
        return (p1 + p2) / 2
    except:
        return 0.5
