from typing import NamedTuple
from settings import CONFIG
from dataclasses import dataclass
import math

# ------------------------------ структура ------------------------------
class Sizing(NamedTuple):
    size: float
    usd_risk: float   # ← добавьте эту строку
    sl_px: float
    tp_px: float
    partial_qty: float
    atr: float 

# ------------------------------ Kelly ------------------------------
def kelly_size(win_rate: float, avg_rr: float, equity: float, last_price: float) -> float:
    """Доля капитала (0-1) по Kelly, обрезано F×0.25"""
    if win_rate <= 0 or avg_rr <= 0:
        return 0.0
    p, b = win_rate, avg_rr
    kelly = (p * b - (1 - p)) / b
    kelly = max(0, min(kelly, CONFIG.KELLY_F))          # глобальный лимит
    return kelly * equity / last_price

# ------------------------------ основной расчёт ------------------------------
def calc(entry: float, atr: float, side: str, equity: float, sym: str,
         win_rate: float = 0.55, avg_rr: float = 2.2) -> Sizing:
    """
    entry  – цена входа
    atr    – абсолютный ATR (в долларах)
    side   – "LONG" / "SHORT"
    equity – equity в $
    sym    – символ (BTC-USDT и т.д.) для индивидуальных настроек
    """
    # 1. параметры по умолчанию
    risk_pc   = CONFIG.RISK_PER_TRADE
    atr_mult  = CONFIG.ATR_MULT_SL
    rr        = CONFIG.RR
    tp_mult   = CONFIG.TP1_MULT

    # 2. если для пары задана тонкая настройка – берём оттуда
    if sym and sym in getattr(CONFIG, 'TUNE', {}):
        atr_mult = CONFIG.TUNE[sym].get("ATR_MULT_SL", atr_mult)
        rr       = CONFIG.TUNE[sym].get("RR",         rr)
        tp_mult  = CONFIG.TUNE[sym].get("TP1_MULT",   tp_mult)

    # 3. расстояние стопа и тейка
    risk_amt = equity * risk_pc / 100     
    sl_dist = atr * atr_mult
    sl_px    = entry - sl_dist if side == "LONG" else entry + sl_dist
    tp_dist  = sl_dist * rr
    tp_px    = entry + tp_dist if side == "LONG" else entry - tp_dist
    
    # 4. размер позиции
    kelly_coin    = kelly_size(win_rate, avg_rr, equity, entry)
    sl_dist       = max(atr * atr_mult, entry * 0.001)
    max_risk_coin = risk_amt / sl_dist
    size          = min(kelly_coin, max_risk_coin)

    # --- максимальный номинал под текущий депозит ---
    max_nom   = equity * CONFIG.LEVERAGE * 0.9   # 90 % от доступной маржи
    max_coins = max_nom / entry
    size      = min(size, max_coins)

    # 5. шаг лота
    lot_step = getattr(CONFIG, "LOT_STEP", 0.001)
    size     = round(size / lot_step) * lot_step
    size     = max(size, lot_step)
    # 6. частичный тейк
    partial_qty = size * CONFIG.PARTIAL_TP
    return Sizing(size, risk_amt, sl_px, tp_px, partial_qty, atr)
# ------------------------------ стоп-аут ------------------------------
def max_drawdown_stop(current_equity: float, peak: float) -> bool:
    if peak <= 0:
        return False
    dd = (peak - current_equity) / peak * 100
    return dd > CONFIG.MAX_DD_STOP
