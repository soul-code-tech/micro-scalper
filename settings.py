from dataclasses import dataclass
import os

@dataclass(slots=True)
class ScalperConfig:
    SYMBOLS: tuple = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "DOGE-USDT")
    TIMEFRAME: str = "1m"
    MAX_POS: int = int(os.getenv("MAX_POS", "3"))
    QUOTE_CURRENCY: str = "USDT"

    RISK_PER_TRADE: float = 0.3
    ATR_MULT_SL: float = 0.8
    RR: float = 3.0
    PARTIAL_TP: float = 0.5
    MAX_SLIPPAGE: float = 0.002
    MAX_SPREAD: float = 0.001
    MIN_ATR_PC: float = 0.0015
    MIN_VOL_USD_1m: float = 80_000

    POST_ONLY: bool = True
    ORDER_TO: int = 8
    REFRESH_SL_TP_EVERY: int = 15

    LOOKBACKS: tuple = (60, 120)
    PROBA_LONG: float = 0.58
    PROBA_SHORT: float = 0.42

CONFIG = ScalperConfig()
