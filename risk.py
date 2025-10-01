from typing import NamedTuple
from settings import CONFIG
import math

class Sizing(NamedTuple):
    size: float
    sl_px: float
    tp_px: float
    partial_qty: float

def kelly_size(win_rate: float, avg_rr: float, equity: float, last_price: float) -> float:
    """Возвращает долю капитала в монете (0-1) по Kelly, обрезано F×0.25"""
    if win_rate <= 0 or avg_rr <= 0:
        return 0.0
    p, b = win_rate, avg_rr
    kelly = (p * b - (1 - p)) / b
    kelly = max(0, min(kelly, 0.25))          # 0.25× conservative
    return kelly * equity / last_price

def calc(entry: float, atr: float, side: str, equity: float,
         win_rate: float = 0.55, avg_rr: float = 2.2) -> Sizing:
    risk_amt = equity * CONFIG.RISK_PER_TRADE / 100
    sl_dist = atr * CONFIG.ATR_MULT_SL
    sl_px = entry - sl_dist if side == "LONG" else entry + sl_dist
    tp_dist = sl_dist * CONFIG.RR
    tp_px = entry + tp_dist if side == "LONG" else entry - tp_dist

    # Kelly-размер
    kelly_coin = kelly_size(win_rate, avg_rr, equity, entry)
    max_risk_coin = risk_amt / sl_dist
    size = min(kelly_coin, max_risk_coin)

    partial_qty = size * CONFIG.PARTIAL_TP
    return Sizing(size, sl_px, tp_px, partial_qty)

def max_drawdown_stop(current_equity: float, peak: float) -> bool:
    """True – торговлю останавливаем"""
    dd = (peak - current_equity) / peak * 100
    return dd > CONFIG.MAX_DD_STOP
