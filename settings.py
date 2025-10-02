from dataclasses import dataclass
import os

@dataclass(slots=True)
class ScalperConfig:
    SYMBOLS = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "DOGE-USDT")
    TIME_FRAMES = ("1m", "3m", "5m", "15m")
    MAX_POS = int(os.getenv("MAX_POS", "3"))

    RISK_PER_TRADE = 0.25
    KELLY_F = 0.25
    MAX_DD_STOP = 5.0
    ATR_MULT_SL = 0.8
    TP1_MULT   = 1.2        # было 0.7
    TRAIL_MULT = 0.8        # было 0.4
    MIN_VOL_USD = 5_000
    MAX_SPREAD = 0.0008
    MIN_ATR_PC = 0.0001
    POST_ONLY = True
    ORDER_TO = 8
    HEALTH_PORT = int(os.getenv("PORT", "10000"))

    TRADE_HOURS = (0, 24)          # UTC
    RR: float = 2.0                # Risk/Reward ratio

    # 👇 ДОБАВЛЕНО: доля позиции для частичного тейк-профита
    PARTIAL_TP: float = 0.5        # например, 50% позиции закрывается на TP1


CONFIG = ScalperConfig()

# Проверка обязательных переменных окружения
for k in ("BINGX_API_KEY", "BINGX_SECRET_KEY"):
    if not os.getenv(k):
        print(f"🔥 ENV {k} не задана – выход")
        exit(1)
