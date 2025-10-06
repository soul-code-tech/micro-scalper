from dataclasses import dataclass, field
from typing import Tuple, Dict
import os

@dataclass(slots=True)
class ScalperConfig:
    SYMBOLS = ("DOGE-USDT", "XRP-USDT", "BNB-USDT")
    TIME_FRAMES = ("5m",)
    MAX_POS = 3
    RISK_PER_TRADE = 0.15
    KELLY_F = 0.15
    MAX_DD_STOP = 5.0
    ATR_MULT_SL = 0.7
    TP1_MULT = 1.4
    TRAIL_MULT = 0.8
    RR = 2.0
    MIN_ATR_PC = 0.00010
    MAX_SPREAD = 0.0010
    MIN_VOL_USD = 50_000
    ORDER_TO = 8
    HEALTH_PORT = field(default_factory=lambda: int(os.getenv("PORT", "10000")))
    TRADE_HOURS = (0, 24)
    PARTIAL_TP = 0.6
    TUNE = field(default_factory=lambda: {
        **{s: {"MIN_ATR_PC": 0.00006, "MAX_SPREAD": 0.00015} for s in ("BTC-USDT", "ETH-USDT")},
        **{s: {"MIN_ATR_PC": 0.00012, "MAX_SPREAD": 0.00035} for s in ("SOL-USDT", "BNB-USDT")},
        **{s: {"MIN_ATR_PC": 0.00015, "MAX_SPREAD": 0.00060} for s in ("DOGE-USDT", "XRP-USDT")},
    })
    LOT_STEP = 0.001
    LEVERAGE = 10
    MIN_NOTIONAL_FALLBACK = 25.0  # ↓ с $500 до $25
CONFIG = ScalperConfig()

def validate_env() -> None:
    for k in ("BINGX_API_KEY", "BINGX_SECRET_KEY"):
        if not os.getenv(k):
            print(f"🔥 ENV {k} не задана – выход")
            exit(1)

if __name__ != "importlib":
    validate_env()
