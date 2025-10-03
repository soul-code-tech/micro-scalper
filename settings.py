from dataclasses import dataclass
import os

@dataclass(slots=True)
class ScalperConfig:
    # ---------- выбор монет ----------
    SYMBOLS = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "DOGE-USDT")

    # ---------- тайм-фреймы ----------
    TIME_FRAMES = ("1m", "3m", "5m", "15m")

    # ---------- риск ----------
    MAX_POS      = 3                 # макс открытых
    RISK_PER_TRADE = 0.15            # 0.15 % equity за сделку
    KELLY_F      = 0.15              # консервативный Kelly
    MAX_DD_STOP  = 3.0               # стоп-аут -3 % от пика

    # ---------- R/R ----------
    ATR_MULT_SL  = 0.7               # стоп ближе
    TP1_MULT     = 1.4               # тейк дальше
    TRAIL_MULT   = 0.7               # трейл дальше
    RR           = 2.0               # жёсткий 1:2

    # ---------- фильтры ----------
    MIN_ATR_PC   = 0.00015           # мин ATR
    MAX_SPREAD   = 0.0003            # 0.03 % (BTC), для остальных см. ниже
    MIN_VOL_USD  = 3_000             # почти любой объём
    POST_ONLY    = True
    ORDER_TO     = 8
    HEALTH_PORT  = int(os.getenv("PORT", "10000"))

    # ---------- торговые часы ----------
    TRADE_HOURS  = (0, 24)           # 24/7 (настраивается ниже)

    # ---------- частичный тейк ----------
    PARTIAL_TP   = 0.6               # 60 % на TP1

    # ---------- ИНДИВИДУАЛЬНЫЕ ПАРАМЕТРЫ (после оптимизации) ----------
    # ключ = символ, значение = dict с перекрытиями
    TUNE = {
        "BTC-USDT": {
            "MIN_ATR_PC": 0.00012,
            "MAX_SPREAD": 0.00025,
            "TRADE_HOURS": (0, 24),
            "TP1_MULT": 1.3,
        },
        "ETH-USDT": {
            "MIN_ATR_PC": 0.00015,
            "MAX_SPREAD": 0.00035,
            "TRADE_HOURS": (0, 24),
            "TP1_MULT": 1.35,
        },
        "SOL-USDT": {
            "MIN_ATR_PC": 0.00020,
            "MAX_SPREAD": 0.00050,
            "TRADE_HOURS": (0, 24),
            "TP1_MULT": 1.4,
        },
        "XRP-USDT": {
            "MIN_ATR_PC": 0.00025,
            "MAX_SPREAD": 0.00060,
            "TRADE_HOURS": (0, 24),
            "TP1_MULT": 1.45,
        },
        "DOGE-USDT": {
            "MIN_ATR_PC": 0.00030,
            "MAX_SPREAD": 0.00080,
            "TRADE_HOURS": (0, 24),
            "TP1_MULT": 1.5,
        },
    }


CONFIG = ScalperConfig()

for k in ("BINGX_API_KEY", "BINGX_SECRET_KEY"):
    if not os.getenv(k):
        print(f"🔥 ENV {k} не задана – выход")
        exit(1)
