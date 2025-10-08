from dataclasses import dataclass, field
from typing import Tuple, Dict
import os

@dataclass(slots=True)
class ScalperConfig:
    SYMBOLS: Tuple[str, ...] = ("DOGE-USDT", "LTC-USDT", "SHIB-USDT", "SUI-USDT")
    TIME_FRAMES: Tuple[str, ...] = ("15m",)
    MAX_POS: int = 3
    RISK_PER_TRADE: float = 0.05
    KELLY_F: float = 0.15
    MAX_DD_STOP: float = 10.0
    ATR_MULT_SL: float = 0.7
    TP1_MULT: float = 1.4
    TRAIL_MULT: float = 0.7
    RR: float = 2.0
    MIN_ATR_PC: float = 0.00015
    MAX_SPREAD: float = 0.0010
    MIN_VOL_USD: int = 30_000
    ORDER_TO: int = 8
    HEALTH_PORT: int = field(default_factory=lambda: int(os.getenv("PORT", "10000")))
    TRADE_HOURS: Tuple[int, int] = (0, 24)
    PARTIAL_TP: float = 0.6
    TUNE: Dict[str, Dict[str, float]] = field(default_factory=lambda: {
        **{s: {"MIN_ATR_PC": 0.00015, "MAX_SPREAD": 0.00060} for s in ("LTC-USDT", "SUI-USDT")},
        **{s: {"MIN_ATR_PC": 0.00012, "MAX_SPREAD": 0.00035} for s in ("SHIB-USDT", "BNB-USDT")},
        **{s: {"MIN_ATR_PC": 0.00015, "MAX_SPREAD": 0.00060} for s in ("DOGE-USDT", "XRP-USDT")},
    })
    LOT_STEP: float = 0.001
    LEVERAGE: int = 10
    MIN_NOTIONAL_FALLBACK: float = 5
    MAX_BALANCE_PC: float = 0.05

CONFIG = ScalperConfig()
class CONFIG:
    TAKE_PROFIT_PCT = 0.02   # 2 % от стартового баланса
# ✅ ВНЕ class — глобальные константы
PRICE_PRECISION = {
    "DOGE-USDT": 5,
    "XRP-USDT": 4,
    "LTC-USDT": 4,
    "SHIB-USDT": 7,
    "SUI-USDT": 3,
    "BNB-USDT": 2,
}

def validate_env() -> None:
    for k in ("BINGX_API_KEY", "BINGX_SECRET_KEY"):
        if not os.getenv(k):
            print(f"🔥 ENV {k} не задана – выход")
            exit(1)

if __name__ != "importlib":
    validate_env()
