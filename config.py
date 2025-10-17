import os
from dataclasses import dataclass

@dataclass
class Config:
    # ==== BingX DEMO (VST) ==== #
    API_KEY      = os.getenv("BINGX_API_KEY", "")
    SECRET_KEY   = os.getenv("BINGX_SECRET_KEY", "")
    BASE_URL     = "https://open-api.bingx.io"   # без пробелов!

    # ==== Торговые параметры ==== #
    SYMBOLS          = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "SHIB-USDT", "DOG-USDT", "ARB-USDT", "BNB-USDT"]
    GRID_RANGE_PCT   = 0.015          # ±1,5 %
    GRID_LEVELS      = 10
    RISK_PER_GRID    = 0.01           # 1 % equity на сетку
    LEVERAGE         = 5              # плечо для VST
    ADX_THRESHOLD    = 20             # чуть выше = реже вход
    ATR_PCT_THRESHOLD= 0.003          # <0,3 % волатильность
    TP_PCT           = 0.012          # +1,2 %
    SL_PCT           = 0.018          # -1,8 %

    # ==== Окружение ==== #
    TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
    PORT             = int(os.getenv("PORT", "10000"))

CONFIG = Config()

def validate_env():
    for k in ("BINGX_API_KEY", "BINGX_SECRET_KEY"):
        if not os.getenv(k):
            raise EnvironmentError(f"Missing env var: {k}")
