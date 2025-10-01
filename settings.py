from dataclasses import dataclass
import os

@dataclass(slots=True)
class ScalperConfig:
    SYMBOLS         = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "DOGE-USDT")
    TIMEFRAME       = "15m"
    MAX_POS         = int(os.getenv("MAX_POS", "3"))

    RISK_PER_TRADE  = 0.25
    KELLY_F         = 0.25
    MAX_DD_STOP     = 5.0
    ATR_MULT_SL     = 0.8
    RR              = 3.0
    PARTIAL_TP      = 0.5
    MIN_VOL_USD_15m = 100_000          # ← было 200_000
    MAX_SPREAD      = 0.001
    MIN_ATR_PC      = 0.0004           # ← было 0.0008
    POST_ONLY       = True
    ORDER_TO        = 8
    HEALTH_PORT     = int(os.getenv("PORT", "10000"))

    # пороги LSTM-энсамбля
    PROBA_LONG  = 0.55
    PROBA_SHORT = 0.45

CONFIG = ScalperConfig()

# ---------- самопроверка ENV ----------
for k in ("BINGX_API_KEY", "BINGX_SECRET_KEY"):
    if not os.getenv(k):
        print(f"🔥 ENV-переменная {k} не задана – выход")
        exit(1)
