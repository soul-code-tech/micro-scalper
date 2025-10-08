#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Минимальный бот с автоплечом для BingX (LTC-USDT)
"""
import ccxt
import os
import sys

# ---------- 1. НАСТРОЙКИ (меняем только тут) ----------
API_KEY     = os.getenv("BINGX_KEY")   or "ВАШ_API_KEY"
API_SECRET  = os.getenv("BINGX_SEC")   or "ВАШ_SECRET"
SYMBOL      = "LTC-USDT"               # торговая пара
USD_RISK    = 1.0                      # сколько USD хотите рискнуть
MAX_NOTIONAL= 600_000                  # ваш жёсткий потолок номинала
# --------------------------------------------------------

exchange = ccxt.bingx({
    "apiKey": API_KEY,
    "secret": API_SECRET,
    "options": {"defaultType": "future"},
})

def auto_leverage_size(symbol: str, usd_risk: float, max_own: float):
    """
    Возвращает (leverage, qty_coin, notional_usd)
    Гарантированно: notional_usd <= max_own
    """
    # 1. данные биржи
    tiers = exchange.fetch_leverage_tiers([symbol])[symbol]
    price = float(exchange.fetch_ticker(symbol)["last"])

    # 2. биржевые лимиты
    max_lev_exchange = min(t["maxLeverage"] for t in tiers)
    max_n_exchange   = max(t["notionalCap"] for t in tiers)

    # 3. итоговый потолок
    cap = min(max_own, max_n_exchange)

    # 4. максимально возможное кол-во монет при этом потолке
    qty_max = cap / price

    # 5. округляем до шага лота
    qty = float(exchange.amount_to_precision(symbol, qty_max))

    # 6. если меньше минимального номинала – поднимаем до минимума
    min_n = CONFIG["min_notional"]
    if qty * price < min_n:
        qty = float(exchange.amount_to_precision(symbol, min_n / price))

    final_nominal = qty * price
    leverage = max(1.0, round(final_nominal / usd_risk, 1))
    leverage = min(leverage, max_lev_exchange)

    return leverage, qty, final_nominal

def open_long():
    lev, qty, nom = auto_leverage_size(SYMBOL, USD_RISK, MAX_NOTIONAL)
    print(f"Автоплечо {lev}×, объём {qty} LTC, номинал ${nom:.2f}")

    # выставляем плечо
    exchange.set_leverage(lev, SYMBOL)

    # рыночный ордер на покупку
    order = exchange.create_order(
        symbol=SYMBOL,
        type="market",
        side="buy",
        amount=qty,
        params={"positionSide": "LONG"}
    )
    print("Ордер исполнен:", order["id"])

if __name__ == "__main__":
    try:
        open_long()
    except ccxt.BaseError as e:
        print("Ошибка биржи:", e)
        sys.exit(1)
