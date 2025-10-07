from dataclasses import dataclass, field
from typing import Tuple, Dict
import os

@dataclass(slots=True)
class ScalperConfig:
    SYMBOLS: Tuple[str, ...] = ("DOGEUSDT", "LTCUSDT", "SHIBUSDT", "SUIUSDT")
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
        **{s: {"MIN_ATR_PC": 0.00015, "MAX_SPREAD": 0.00060} for s in ("LTCUSDT", "SUIUSDT")},
        **{s: {"MIN_ATR_PC": 0.00012, "MAX_SPREAD": 0.00035} for s in ("SHIBUSDT", "BNBUSDT")},
        **{s: {"MIN_ATR_PC": 0.00015, "MAX_SPREAD": 0.00060} for s in ("DOGEUSDT", "XRPUSDT")},
    })
    LOT_STEP: float = 0.001
    LEVERAGE: int = 20
    MIN_NOTIONAL_FALLBACK: float = 15.0
    MAX_BALANCE_PC: float = 0.05

CONFIG = ScalperConfig()

# ✅ ВНЕ class — глобальные константы
PRICE_PRECISION = {
    "DOGEUSDT": 5,
    "XRPUSDT": 4,
    "LTCUSDT": 4,
    "SHIBUSDT": 7,
    "SUIUSDT": 3,
    "BNBUSDT": 2,
}

def validate_env() -> None:
    for k in ("BINGX_API_KEY", "BINGX_SECRET_KEY"):
        if not os.getenv(k):
            print(f"🔥 ENV {k} не задана – выход")
            exit(1)

if __name__ != "importlib":
    validate_env()
