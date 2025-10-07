import os, time, math, hmac, hashlib, requests, logging
from typing import Optional, Tuple
from settings import CONFIG

ENDPOINT = "https://open-api.bingx.com"
API_KEY  = os.getenv("BINGX_API_KEY")
SECRET   = os.getenv("BINGX_SECRET_KEY")

def _get_precision(symbol: str) -> Tuple[int, int]:
    """price_precision, lot_precision"""
    try:
        r = requests.get(f"{ENDPOINT}/openApi/swap/v2/quote/contracts").json()
        for s in r["data"]:
            if s["symbol"] == symbol:
                return int(s["pricePrecision"]), int(s["quantityPrecision"])
    except Exception as e:
        logging.warning("⚠️ _get_precision failed for %s: %s", symbol, e)
    return 4, 3  # fallback

def _sign(params: dict) -> str:
    query = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
    return hmac.new(SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()

def limit_entry(symbol: str, side: str, usd_qty: float, leverage: int,
                sl_price: float, tp_price: float) -> Optional[Tuple[str, float, float]]:
    price_prec, lot_prec = _get_precision(symbol)

    # 1. стакан ➜ требует -USDT
    public_sym = symbol.replace("USDT", "-USDT")
    book = requests.get(f"{ENDPOINT}/openApi/swap/v2/quote/depth",
                        params={"symbol": public_sym, "limit": 5}).json()
    if not book or "asks" not in book or "bids" not in book or not book["asks"] or not book["bids"]:
        logging.warning("⚠️ %s – пустой стакан, пропуск", symbol)
        return None

    # 2. цена
    if side == "BUY":
        entry_px = float(book["bids"][0]["price"]) - math.pow(10, -price_prec)
    else:
        entry_px = float(book["asks"][0]["price"]) + math.pow(10, -price_prec)
    entry_px = round(entry_px, price_prec)

    # 3. цена маркировки ➜ тоже публичный энд-поинт
    mark_resp = requests.get(f"{ENDPOINT}/openApi/swap/v2/quote/price",
                             params={"symbol": public_sym}).json()
    if not mark_resp or "price" not in mark_resp:
        logging.warning("⚠️ %s – нет цены, пропуск", symbol)
        return None
    mark = float(mark_resp["price"])

    # 4. объём и ордер
    qty_usd = usd_qty * leverage
    qty_coin = round(qty_usd / entry_px, lot_prec)
    params = {
        "symbol": symbol,          # ← приватный энд-поинт: без дефиса
        "side": side,
        "type": "LIMIT",
        "timeInForce": "POST_ONLY",
        "price": entry_px,
        "quantity": qty_coin,
        "leverage": leverage,
        "timestamp": int(time.time() * 1000),
    }
    params["signature"] = _sign(params)
    r = requests.post(f"{ENDPOINT}/openApi/swap/v2/trade/order", params=params)
    r.raise_for_status()
    order_id = r.json()["data"]["order"]["id"]
    logging.info("💡 %s %s limit @ %s  qty=%s  orderId=%s",
                 symbol, side, entry_px, qty_coin, order_id)
    return order_id, entry_px, qty_coin

def await_fill_or_cancel(order_id: str, symbol: str, max_sec: float = 8) -> Optional[float]:
    """Ждёт fill max_sec. Возвращает avgPrice или None."""
    t0 = time.time()
    while time.time() - t0 < max_sec:
        params = {"symbol": symbol, "orderId": order_id, "timestamp": int(time.time() * 1000)}
        params["signature"] = _sign(params)
        r = requests.get(f"{ENDPOINT}/openApi/swap/v2/trade/order", params=params)
        r.raise_for_status()
        data = r.json()["data"]
        if data["status"] == "FILLED":
            return float(data["avgPrice"])
        time.sleep(0.5)

    # не успели – отменяем
    params = {"symbol": symbol, "orderId": order_id, "timestamp": int(time.time() * 1000)}
    params["signature"] = _sign(params)
    requests.delete(f"{ENDPOINT}/openApi/swap/v2/trade/order", params=params)
    logging.warning("⏭ %s лимит не исполнен – отмена", symbol)
    return None

def limit_sl_tp(symbol: str, side: str, qty_coin: float, sl_price: float, tp_price: float):
    """Создаёт 2 лимитных ордера (SL и TP) одновременно."""
    opposite = "SELL" if side == "BUY" else "BUY"
    for name, px in (("SL", sl_price), ("TP", tp_price)):
        params = {
            "symbol": symbol,
            "side": opposite,
            "type": "LIMIT",
            "timeInForce": "POST_ONLY",
            "price": px,
            "quantity": qty_coin,
            "timestamp": int(time.time() * 1000),
        }
        params["signature"] = _sign(params)
        r = requests.post(f"{ENDPOINT}/openApi/swap/v2/trade/order", params=params)
        r.raise_for_status()
        logging.info("🛑 %s %s limit @ %s", name, symbol, px)
