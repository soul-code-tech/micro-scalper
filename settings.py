from dataclasses import dataclass
import os

@dataclass(slots=True)
class ScalperConfig:
    SYMBOLS        = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "DOGE-USDT")
    TIMEFRAME      = "15m"
    MAX_POS        = int(os.getenv("MAX_POS", "3"))

    RISK_PER_TRADE = 0.25
    KELLY_F        = 0.25
    MAX_DD_STOP    = 5.0
    ATR_MULT_SL    = 0.8
    RR             = 3.0
    PARTIAL_TP     = 0.5
    MIN_VOL_USD_15m= 80_000
    MAX_SPREAD     = 0.001
    MIN_ATR_PC     = 0.0004
    POST_ONLY      = True
    ORDER_TO       = 8
    HEALTH_PORT    = int(os.getenv("PORT", "10000"))

    # торговые часы (UTC)
    TRADE_START_H  = 9
    TRADE_END_H    = 17

CONFIG = ScalperConfig()

for k in ("BINGX_API_KEY", "BINGX_SECRET_KEY"):
    if not os.getenv(k):
        print(f"🔥 ENV {k} не задана – выход"); exit(1)
