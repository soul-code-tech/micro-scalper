from typing import NamedTuple
from settings import CONFIG

class Sizing(NamedTuple):
    size: float
    usd_risk: float
    sl_px: float
    tp_px: float
    partial_qty: float
    atr: float

def calc(entry: float, atr: float, side: str, equity: float, sym: str) -> Sizing:
    risk_amt = equity * CONFIG.RISK_PER_TRADE / 100
    sl_dist = atr * CONFIG.ATR_MULT_SL
    sl_px = entry - sl_dist if side == "LONG" else entry + sl_dist
    tp_px = entry + sl_dist * CONFIG.RR if side == "LONG" else entry - sl_dist * CONFIG.RR

    size = risk_amt / sl_dist
    size = min(size, equity * CONFIG.MAX_BALANCE_PC / entry)

    min_qty, step = get_min_lot(sym)
    size = max(size, min_qty)
    size = (size // step) * step

    partial_qty = size * CONFIG.PARTIAL_TP
    return Sizing(size, risk_amt, sl_px, tp_px, partial_qty, atr)

def get_min_lot(symbol: str):
    SAFE_MIN = {
        "DOGE-USDT": (7.0, 1.0),
        "LTC-USDT": (0.1, 0.01),
        "SHIB-USDT": (100000.0, 1000.0),
        "SUI-USDT": (1.0, 1.0),
        "BNB-USDT": (0.01, 0.001),
        "XRP-USDT": (1.0, 1.0),
    }
    return SAFE_MIN.get(symbol, (1.0, 0.001))
