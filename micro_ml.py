from jesse.strategies import Strategy
import joblib
import os
import numpy as np
from jesse import utils
from jesse.services import logger

# ---------- наши константы из CONFIG ----------
SYMBOLS = ('DOGE-USDT', 'LTC-USDT', 'SHIB-USDT', 'SUI-USDT')
TF = '5m'
LEVERAGE = 10
RISK_PC = 0.01          # 1 % от баланса
MIN_NOTIONAL = 0.5      # USDT
TP_PCT = 0.02           # +2 %
SL_ATR_MUL = 0.7
MAX_POS = 6

# ---------- загрузка модели ----------
MODEL_DIR = os.path.join(os.path.dirname(__file__), '..', 'weights')
_MODELS = {}

def model_path(sym: str) -> str:
    return f"{MODEL_DIR}/{sym.replace('-','')}_{TF}.pkl"

def load_model(sym: str):
    if sym in _MODELS:
        return _MODELS[sym]
    p = model_path(sym)
    if not os.path.isfile(p):
        _MODELS[sym] = (None, None, 0.55)
        return None, None, 0.55
    obj = joblib.load(p)
    _MODELS[sym] = (obj['scaler'], obj['clf'], obj['thr'])
    return obj['scaler'], obj['clf'], obj['thr']

# ---------- стратегия ----------
class MicroML(Strategy):
    def before(self):
        # торгуем только разрешённые пары
        if self.symbol not in SYMBOLS:
            return

    def should_long(self) -> bool:
        score = self._micro_score()
        return score['long'] > score['short']

    def should_short(self) -> bool:
        score = self._micro_score()
        return score['short'] > score['long']

    def go_long(self):
        qty = self._qty()
        if qty == 0:
            return
        self.buy = qty, self.price
        self.stop_loss = qty, self.price - SL_ATR_MUL * self._atr()
        self.take_profit = qty, self.price * (1 + TP_PCT)

    def go_short(self):
        qty = self._qty()
        if qty == 0:
            return
        self.sell = qty, self.price
        self.stop_loss = qty, self.price + SL_ATR_MUL * self._atr()
        self.take_profit = qty, self.price * (1 - TP_PCT)

    def _atr(self) -> float:
        return ta.atr(self.candles, 14)

    def _micro_score(self) -> dict:
        scaler, clf, thr = load_model(self.symbol)
        # --- простейший fallback, если модель не грузится ---
        if scaler is None or clf is None:
            rsi_now = ta.rsi(self.candles, 14)
            long = float(rsi_now < 45)
            short = float(rsi_now > 65)
            return {'long': long, 'short': short}
        # --- извлекаем фичи (пример: 5 лагов RSI/ATR) ---
        closes = self.candles[:, 2]
        feats = []
        for lag in range(1, 6):
            feats.append(closes[-lag])
        feats.append(ta.rsi(self.candles, 14))
        feats.append(ta.atr(self.candles, 14))
        X = scaler.transform(np.array(feats).reshape(1, -1))
        prob = float(clf.predict_proba(X)[0, 1])
        long = float(prob > thr)
        short = float(prob < 1 - thr)
        return {'long': long, 'short': short}

    def _qty(self) -> float:
        # риск 1 % от баланса
        balance = self.capital
        risk_usd = balance * RISK_PC
        atr = self._atr()
        if atr == 0:
            return 0
        qty = utils.size_to_qty(
            risk_usd / (SL_ATR_MUL * atr),
            self.price,
            precision=self.asset_precision,
            fee_rate=self.fee_rate
        )
        # не ниже мин-ного номинала
        if qty * self.price < MIN_NOTIONAL:
            qty = utils.size_to_qty(
                MIN_NOTIONAL / self.price,
                self.price,
                precision=self.asset_precision,
                fee_rate=self.fee_rate
            )
        # не больше MAX_POS позиций
        if len(self.shared_vars.get('open_pos', [])) >= MAX_POS:
            return 0
        return qty

    def should_cancel(self):
        return True
