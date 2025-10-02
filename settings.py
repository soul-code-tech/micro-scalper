from dataclasses import dataclass
import os

@dataclass(slots=True)
class ScalperConfig:
    SYMBOLS        = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "DOGE-USDT")

    # --- тайм-фреймы (от меньшего к большему) ---
    TIME_FRAMES    = ("1m", "3m", "5m", "15m")
    TF_RECHOICE_MINS = 240          # перебираем раз в 4 ч

    # --- риск ---
    MAX_POS        = int(os.getenv("MAX_POS", "3"))
    RISK_PER_TRADE = 0.25           # % капитала
    KELLY_F        = 0.25           # консерватор
    MAX_DD_STOP    = 5.0            # %

    # --- стоп/тейк множители (новые) ---
    ATR_MULT_SL    = 0.8            # SL
    TP1_MULT       = 0.7            # быстрый 60 % выход
    TRAIL_MULT     = 0.4            # трейл оставшихся 40 %

    RR             = 3.0            # для расчёта начального TP (не используется в патче)
    PARTIAL_TP     = 0.5            # для 1R-логики (оставляем как есть)

    # --- фильтры объёма и волатильности ---
    MIN_VOL_USD    = 30_000         # было 80 000 (для 1m тоже хватит)
    MAX_SPREAD     = 0.0005         # 5 бп (было 10 бп)

    # --- волатильность под 1m / 3m ---
    MIN_ATR_PC     = 0.0005         # было 0.0004

    # --- часы торговли (UTC) ---
    TRADE_START_H  = 8
    TRADE_END_H    = 17

    # --- ордер ---
    POST_ONLY      = True
    ORDER_TO       = 8
    HEALTH_PORT    = int(os.getenv("PORT", "10000"))

CONFIG = ScalperConfig()

# --- самопроверка ключей ---
for k in ("BINGX_API_KEY", "BINGX_SECRET_KEY"):
    if not os.getenv(k):
        print(f"🔥 ENV {k} не задана – выход"); exit(1)
