from dataclasses import dataclass, field
from typing import Tuple, Dict
import os

@dataclass(slots=True)
class ScalperConfig:
    SYMBOLS: Tuple[str, ...] = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "DOGE-USDT")
    TIME_FRAMES: Tuple[str, ...] = ("3m", "5m",)
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
    MIN_VOL_USD: int = 1_000
    POST_ONLY: bool = True
    ORDER_TO: int = 8
    HEALTH_PORT: int = field(default_factory=lambda: int(os.getenv("PORT", "10000")))
    TRADE_HOURS: Tuple[int, int] = (0, 24)
    PARTIAL_TP: float = 0.6
    TUNE: Dict[str, Dict[str, float]] = field(default_factory=lambda: {
        **{s: {"MIN_ATR_PC": 0.00006, "MAX_SPREAD": 0.00015} for s in ("BTC-USDT", "ETH-USDT")},
        **{s: {"MIN_ATR_PC": 0.00012, "MAX_SPREAD": 0.00035} for s in ("SOL-USDT", "BNB-USDT", "ADA-USDT")},
        **{s: {"MIN_ATR_PC": 0.00020, "MAX_SPREAD": 0.00060} for s in ("DOGE-USDT", "MATIC-USDT", "FTM-USDT")},
    })
    LOT_STEP: float = 0.001  # ✅ ДОБАВЛЕНО — минимальный шаг лота
    LEVERAGE: int = 20
CONFIG = ScalperConfig()

def validate_env() -> None:
    for k in ("BINGX_API_KEY", "BINGX_SECRET_KEY"):
        if not os.getenv(k):
            print(f"🔥 ENV {k} не задана – выход")
            exit(1)

if __name__ != "importlib":
    validate_env()
