from dataclasses import dataclass
import os

@dataclass(slots=True)
class ScalperConfig:
    # --- базовые ---
    SYMBOLS: tuple = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "DOGE-USDT")
    TIMEFRAME: str = "1m"
    MAX_POS: int = int(os.getenv("MAX_POS", "3"))

    # --- риск / мани ---
    RISK_PER_TRADE: float = 0.25          # % от баланса на 1 сделку
    KELLY_F: float = 0.25                 # Kelly multiplier (0.25× conservative)
    MAX_DD_STOP: float = 5.0              # если просадка > 5 % – стоп-торговли
    ATR_MULT_SL: float = 0.8
    RR: float = 3.0
    PARTIAL_TP: float = 0.5

    # --- фильтры ---
    MIN_VOL_USD_1m: float = 80_000
    MAX_SPREAD: float = 0.001
    MIN_ATR_PC: float = 0.0015

    # --- execution ---
    POST_ONLY: bool = True
    ORDER_TO: int = 8
    HEALTH_PORT: int = int(os.getenv("PORT", "10000"))

CONFIG = ScalperConfig()
