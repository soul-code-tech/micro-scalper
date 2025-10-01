from dataclasses import dataclass
import os

@dataclass(slots=True)
class ScalperConfig:
    SYMBOLS      = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "DOGE-USDT")
    TIMEFRAME    = "1m"
    MAX_POS      = int(os.getenv("MAX_POS", "3"))

    RISK_PER_TRADE = 0.25                       # % equity
    KELLY_F        = 0.25                       # 0.25× conservative
    MAX_DD_STOP    = 5.0                        # просадка 5 % → стоп
    ATR_MULT_SL    = 0.8
    RR             = 3.0
    PARTIAL_TP     = 0.5
    MIN_VOL_USD_1m = 80_000
    MAX_SPREAD     = 0.001
    MIN_ATR_PC     = 0.0015                     # ≥ 0.15 %

    POST_ONLY  = True
    ORDER_TO   = 8
    HEALTH_PORT = int(os.getenv("PORT", "10000"))

CONFIG = ScalperConfig()
