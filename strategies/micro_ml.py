from jesse.strategies import Strategy
import joblib, os, numpy as np
from jesse import utils
import jesse.indicators as ta

SYMBOLS   = ('DOGE-USDT', 'LTC-USDT', 'SHIB-USDT', 'SUI-USDT')
TF        = '5m'
LEVERAGE  = 10
RISK_PC   = 0.01          # 1 %
MIN_USD   = 0.5           # мин номинал
TP_PC     = 0.02          # +2 %
SL_ATR_M  = 0.7
MAX_POS   = 6

MODEL_DIR = os.path.join(os.path.dirname(__file__), '..', 'weights')
_MODELS   = {}

def model_path(sym: str) -> str:
    return f"{MODEL_DIR}/{sym.replace('-','')}_{TF}.pkl"

def load_model(sym: str):
    if sym in _MODELS:
        return _MODELS[sym]
    p = model_path(sym)
    if not os.path.isfile(p):
        _MODELS[sym] = (None, None, 0.48)
        return None, None, 0.48
    obj = joblib.load(p)
    _MODELS[sym] = (obj['scaler'], obj['clf'], obj['thr'])
    return obj['scaler'], obj['clf'], obj['thr']

class MicroML(Strategy):
    def should_long(self) -> bool:
        return self._signal()['long'] > self._signal()['short']

    def should_short(self) -> bool:
        return self._signal()['short'] > self._signal()['long']

    def go_long(self):
        qty = self._qty()
        self.buy = qty, self.price
        self.stop_loss   = qty, self.price - SL_ATR_M * ta.atr(self.candles, 14)
        self.take_profit = qty, self.price * (1 + TP_PC)

    def go_short(self):
        qty = self._qty()
        self.sell = qty, self.price
        self.stop_loss   = qty, self.price + SL_ATR_M * ta.atr(self.candles, 14)
        self.take_profit = qty, self.price * (1 - TP_PC)

    def _signal(self):
        scaler, clf, thr = load_model(self.symbol)
        if scaler is None or clf is None:
            rsi_now = ta.rsi(self.candles, 14)
            return {'long': float(rsi_now < 45), 'short': float(rsi_now > 65)}
        feats = np.array([
            self.close[-1], self.close[-2], self.close[-3],
            ta.rsi(self.candles, 14), ta.atr(self.candles, 14)
        ]).reshape(1, -1)
        X   = scaler.transform(feats)
        prob = float(clf.predict_proba(X)[0, 1])
        return {'long': float(prob > thr), 'short': float(prob < 1 - thr)}

    def _qty(self):
        risk_usd = self.capital * RISK_PC
        atr = ta.atr(self.candles, 14)
        if atr == 0:
            return 0
        size = risk_usd / (SL_ATR_M * atr)
        qty = utils.size_to_qty(size, self.price, fee_rate=self.fee_rate)
        if qty * self.price < MIN_USD:
            qty = utils.size_to_qty(MIN_USD / self.price, self.price, fee_rate=self.fee_rate)
        return qty

    def should_cancel(self):
        return True
