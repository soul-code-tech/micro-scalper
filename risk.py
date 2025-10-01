from typing import NamedTuple
from settings import CONFIG

class Sizing(NamedTuple):
    size: float
    sl_px: float
    tp_px: float
    partial_qty: float

def calc(entry: float, atr: float, side: str, equity: float) -> Sizing:
    risk_amt = equity * CONFIG.RISK_PER_TRADE / 100
    sl_dist = atr * CONFIG.ATR_MULT_SL
    sl_px = entry - sl_dist if side == "LONG" else entry + sl_dist
    tp_dist = sl_dist * CONFIG.RR
    tp_px = entry + tp_dist if side == "LONG" else entry - tp_dist
    size = risk_amt / sl_dist
    partial_qty = size * CONFIG.PARTIAL_TP
    return Sizing(size, sl_px, tp_px, partial_qty)
