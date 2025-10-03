from dataclasses import dataclass
import os

@dataclass(slots=True)
class ScalperConfig:
    # ---------- монеты (низкий minNominal) ----------
    SYMBOLS = ("PEPE-USDT", "DOGE-USDT", "XRP-USDT")

    # ---------- тайм-фреймы ----------
    TIME_FRAMES = ("1m", "3m", "5m", "15m")

    # ---------- риск ----------
    MAX_POS      = 3
    RISK_PER_TRADE = 0.15            # 0.15 % equity
    KELLY_F      = 0.15
    MAX_DD_STOP  = 3.0               # -3 % к пику

    # ---------- R/R ----------
    ATR_MULT_SL  = 0.7
    TP1_MULT     = 1.4
    TRAIL_MULT   = 0.7
    RR           = 2.0

    # ---------- фильтры ----------
    MIN_ATR_PC   = 0.00015
    MAX_SPREAD   = 0.0003
    MIN_VOL_USD  = 3_000
    POST_ONLY    = True
    ORDER_TO     = 8
    HEALTH_PORT  = int(os.getenv("PORT", "10000"))

    # ---------- торговые часы (24/7) ----------
    TRADE_HOURS  = (0, 24)

    # ---------- частичный тейк ----------
    PARTIAL_TP   = 0.6

    # ---------- индивидуальные настройки ----------
    TUNE = {
        "PEPE-USDT": {
            "MIN_ATR_PC": 0.00035,
            "MAX_SPREAD": 0.0010,
            "TRADE_HOURS": (0, 24),
            "TP1_MULT": 1.5,
        },
        "DOGE-USDT": {
            "MIN_ATR_PC": 0.00030,
            "MAX_SPREAD": 0.0008,
            "TRADE_HOURS": (0, 24),
            "TP1_MULT": 1.4,
        },
        "XRP-USDT": {
            "MIN_ATR_PC": 0.00025,
            "MAX_SPREAD": 0.0006,
            "TRADE_HOURS": (0, 24),
            "TP1_MULT": 1.45,
        },
    }


CONFIG = ScalperConfig()

for k in ("BINGX_API_KEY", "BINGX_SECRET_KEY"):
    if not os.getenv(k):
        print(f"🔥 ENV {k} не задана – выход")
        exit(1)
