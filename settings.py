from dataclasses import dataclass, field
from typing import Tuple, Dict
import os

@dataclass(slots=True)
class ScalperConfig:
    # --- торговые символы и тайм-фреймы ---
    SYMBOLS: Tuple[str, ...] = ("DOGE-USDT", "LTC-USDT", "SHIB-USDT", "SUI-USDT")
    TIME_FRAMES: Tuple[str, ...] = ("5m",)

    # --- риск и деньги ---
    MAX_POS: int = 10                    # макс одновременных позиций
    RISK_PER_TRADE: float = 1        # 5 % от баланса на сделку
    MAX_BALANCE_PC: float = 1        # макс % баланса в одной сделке (новое)
    TAKE_PROFIT_PCT: float = 0.02       # закрыть всё при +2 % к старту (новое)
    MIN_NOTIONAL_FALLBACK: float = 2.0  # мин $ на вход
    MAX_POS_NOMINAL: float = 20.0       # ← не больше 20 $ на одну позицию
    
    # --- плечо и лимиты ---
    LEVERAGE: int = 10
    LOT_STEP: float = 1
    MAX_NOMINAL_USD: float = 46.0  # лимит BingX для плеча (новое)

    # --- стоп-лосс / тейк-профит ---
    ATR_MULT_SL: float = 0.7
    TP1_MULT: float = 1.4
    TRAIL_MULT: float = 0.7
    RR: float = 2.0
    PARTIAL_TP: float = 0.6

    # --- фильтры ---
    MIN_ATR_PC: float = 0.00015
    MAX_SPREAD: float = 0.0010
    MIN_VOL_USD: int = 10_000
    MAX_DD_STOP: float = 0.5        # % просадки до стопа

    # --- волатильность под символ ---
    TUNE: Dict[str, Dict[str, float]] = field(default_factory=lambda: {
        **{s: {"MIN_ATR_PC": 0.00015, "MAX_SPREAD": 0.00060} for s in ("LTC-USDT", "SUI-USDT")},
        **{s: {"MIN_ATR_PC": 0.00012, "MAX_SPREAD": 0.00035} for s in ("SHIB-USDT", "BNB-USDT")},
        **{s: {"MIN_ATR_PC": 0.00015, "MAX_SPREAD": 0.00060} for s in ("DOGE-USDT", "XRP-USDT")},
    })

    # --- прочее ---
    ORDER_TO: int = 8
    HEALTH_PORT: int = field(default_factory=lambda: int(os.getenv("PORT", "10000")))
    TRADE_HOURS: Tuple[int, int] = (0, 24)
    KELLY_F: float = 0.15

    # --- новые технические константы ---
    STOP_ORDER_TYPE: str = "STOP_MARKET"   # STOP_MARKET | LIMIT (видно на графике)
    PRICE_PREC: Dict[str, int] = field(default_factory=lambda: {
        "DOGE-USDT": 5, "XRP-USDT": 4, "LTC-USDT": 4,
        "SHIB-USDT": 7, "SUI-USDT": 3, "BNB-USDT": 2,
    })

# -------------------- единый объект конфига --------------------
CONFIG = ScalperConfig()

# -------------------- валидация env --------------------
def validate_env() -> None:
    for k in ("BINGX_API_KEY", "BINGX_SECRET_KEY"):
        if not os.getenv(k):
            print(f"🔥 ENV {k} не задана – выход")
            exit(1)

if __name__ != "importlib":
    validate_env()
