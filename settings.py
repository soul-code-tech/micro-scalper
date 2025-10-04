from dataclasses import dataclass, field
from typing import Tuple, Dict
import os

@dataclass(slots=True)
class ScalperConfig:
    SYMBOLS: Tuple[str, ...] = ("DOGE-USDT", "XRP-USDT")
    TIME_FRAMES: Tuple[str, ...] = ("5m")
    MAX_POS: int = 3
    RISK_PER_TRADE: float = 0.15
    KELLY_F: float = 0.15
    MAX_DD_STOP: float = 3.0
    ATR_MULT_SL: float = 0.7
    TP1_MULT: float = 1.4
    TRAIL_MULT: float = 0.7
    RR: float = 2.0
    MIN_ATR_PC: float = 0.00015
    MAX_SPREAD: float = 0.0003
    MIN_VOL_USD: int = 3_000
    POST_ONLY: bool = True
    ORDER_TO: int = 8
    HEALTH_PORT: int = field(default_factory=lambda: int(os.getenv("PORT", "10000")))
    TRADE_HOURS: Tuple[int, int] = (0, 24)
    PARTIAL_TP: float = 0.6

    TUNE: Dict[str, Dict[str, float]] = field(default_factory=lambda: {
        "DOGE-USDT": {
            "MIN_ATR_PC": 0.00030,
            "MAX_SPREAD": 0.0008,
            "TRADE_HOURS": (0, 24),
            "TP1_MULT": 1.4,
        },
        "XRP-USDT": {
            "MIN_ATR_PC": 0.00025,
            "MAX_SPREAD": 0.0006,
            "TRADE_HOURS": (0, 24),
            "TP1_MULT": 1.45,
        },
    })

CONFIG = ScalperConfig()

def validate_env() -> None:
    for k in ("BINGX_API_KEY", "BINGX_SECRET_KEY"):
        if not os.getenv(k):
            print(f"🔥 ENV {k} не задана – выход")
            exit(1)

if __name__ != "importlib":
    validate_env()
