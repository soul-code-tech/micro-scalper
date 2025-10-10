import os
import time
import math
import logging
import asyncio
from typing import Optional, Tuple
from exchange import BingXAsync
from settings import CONFIG

log = logging.getLogger(__name__)
_MIN_LOT_CACHE = {}

async def load_min_lot_cache(ex: BingXAsync) -> None:
    global _MIN_LOT_CACHE
    try:
        info = await ex._public_get("/openApi/swap/v2/quote/contracts")
        for item in info["data"]:
            sym = item.get("symbol")
            if sym:
                _MIN_LOT_CACHE[sym] = {
                    "minQty": float(item.get("minQty", 1.0)),
                    "stepSize": float(item.get("stepSize", 0.001)),
                }
        log.info("✅ Loaded min-lot cache for %d symbols", len(_MIN_LOT_CACHE))
    except Exception as e:
        log.warning("⚠️ Failed to load min-lot cache: %s", e)

def get_min_lot(symbol: str) -> tuple[float, float]:
    data = _MIN_LOT_CACHE.get(symbol)
    if data:
        return data["minQty"], data["stepSize"]
    SAFE_MIN = {
        "DOGE-USDT": (7.0, 1.0),
        "LTC-USDT": (0.1, 0.01),
        "SHIB-USDT": (100000.0, 1000.0),
        "SUI-USDT": (1.0, 1.0),
        "BNB-USDT": (0.01, 0.001),
        "XRP-USDT": (1.0, 1.0),
    }
    return SAFE_MIN.get(symbol, (1.0, 0.001))

async def limit_entry(ex: BingXAsync, symbol: str, side: str, qty_coin: float, entry_px: float, sl_price: float, tp_price: float, equity: float):
    free_margin = await ex.get_free_margin()
    required = (qty_coin * entry_px) / CONFIG.LEVERAGE * 1.1
    if required > free_margin:
        return None

    book = await ex.order_book(symbol, 5)
    if not book.get("bids") or not book.get("asks"):
        return None

    tick = 0.00001
    if side == "BUY":
        entry_px = float(book["bids"][0][0]) - tick * 3
    else:
        entry_px = float(book["asks"][0][0]) + tick * 3

    min_qty, step_size = get_min_lot(symbol)
    qty_coin = max(qty_coin, min_qty)
    qty_coin = math.ceil(qty_coin / step_size) * step_size
    if step_size.is_integer():
        qty_coin = int(qty_coin)

    nominal = qty_coin * entry_px
    if nominal < 0.01:
        return None

    position_side = "LONG" if side == "BUY" else "SHORT"
    params = {
        "symbol": symbol,
        "side": side,
        "type": "LIMIT",
        "timeInForce": "PostOnly",
        "price": f"{entry_px:.8f}",
        "quantity": str(qty_coin),
        "positionSide": position_side,
    }

    resp = await ex._signed_request("POST", "/openApi/swap/v2/trade/order", params)
    if resp.get("code") != 0:
        return None

    order_data = resp.get("data", {}).get("order", {})
    order_id = order_data.get("orderId")
    if not order_id:
        return None

    log.info("💡 %s %s @ %.8f qty=%s id=%s", symbol, side, entry_px, qty_coin, order_id)
    return order_id, entry_px, float(qty_coin)

async def await_fill_or_cancel(ex: BingXAsync, order_id: str, symbol: str, max_sec: float = 8) -> Optional[float]:
    t0 = time.time()
    while time.time() - t0 < max_sec:
        try:
            order = await ex.fetch_order(symbol, order_id)
            if order.get("status") == "FILLED":
                return float(order["avgPrice"])
        except:
            pass
        await asyncio.sleep(0.5)

    try:
        await ex._signed_request("DELETE", "/openApi/swap/v2/trade/order",
            {"symbol": symbol, "orderId": order_id})
    except:
        pass
    return None

async def limit_sl_tp(ex: BingXAsync, symbol: str, side: str, qty_coin: float, sl_price: float, tp_price: float):
    ids = []
    for px in (sl_price, tp_price):
        opposite = "SELL" if side == "BUY" else "BUY"
        pos_side = "LONG" if opposite == "SELL" else "SHORT"
        params = {
            "symbol": symbol,
            "side": opposite,
            "type": "LIMIT",
            "timeInForce": "PostOnly",
            "price": f"{px:.8f}",
            "quantity": f"{qty_coin:.8f}",
            "positionSide": pos_side,
        }
        resp = await ex._signed_request("POST", "/openApi/swap/v2/trade/order", params)
        oid = resp["data"]["order"]["orderId"]
        ids.append(oid)
    return tuple(ids)
