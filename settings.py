from dataclasses import dataclass, field
from typing import Tuple, Dict
import os

@dataclass(slots=True)
class ScalperConfig:
    SYMBOLS: Tuple[str, ...] = ("DOGE-USDT", "LTC-USDT", "SHIB-USDT", "SUI-USDT")
    TIME_FRAMES: Tuple[str, ...] = ("5m",)
    MAX_POS: int = 4
    RISK_PER_TRADE: float = 1.0
    MAX_BALANCE_PC: float = 0.25
    MIN_NOTIONAL_FALLBACK: float = 1.0
    LEVERAGE: int = 10
    ATR_MULT_SL: float = 0.7
    TP1_MULT: float = 1.4
    TRAIL_MULT: float = 0.7
    RR: float = 2.0
    PARTIAL_TP: float = 0.6
    MIN_ATR_PC: float = 0.00015
    TRADE_HOURS: Tuple[int, int] = (0, 24)
    KELLY_F: float = 0.15

CONFIG = ScalperConfig()

def validate_env() -> None:
    for k in ("BINGX_API_KEY", "BINGX_SECRET_KEY"):
        if not os.getenv(k):
            print(f"🔥 ENV {k} не задана – выход")
            exit(1)
