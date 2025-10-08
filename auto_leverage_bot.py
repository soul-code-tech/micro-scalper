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
USD_RISK    = 2.5                      # сколько USD хотите рискнуть
MAX_NOTIONAL= 150_000                  # ваш жёсткий потолок номинала
# --------------------------------------------------------

exchange = ccxt.bingx({
    "apiKey": API_KEY,
    "secret": API_SECRET,
    "options": {"defaultType": "future"},
})

def auto_leverage_size(symbol, usd_risk, max_notional):
    """Возвращает (leverage, qty_coin)"""
    # 1. лимиты биржи
    tiers = exchange.fetch_leverage_tiers([symbol])[symbol]
    max_lev = min(tier["maxLeverage"] for tier in tiers)
    max_n   = min(max_notional, max(tier["maxNotional"] for tier in tiers))

    # 2. цена
    price = float(exchange.fetch_ticker(symbol)["last"])

    # 3. максимально возможное кол-во монет
    qty = max_n / price
    leverage = min(max_lev, max_n / usd_risk)

    # 4. округляем до шага лота
    qty = float(exchange.amount_to_precision(symbol, qty))
    return round(leverage, 1), qty

def open_long():
    lev, qty = auto_leverage_size(SYMBOL, USD_RISK, MAX_NOTIONAL)
    print(f"Автоплечо {lev}×, объём {qty} LTC")

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
