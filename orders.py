# orders.py
import os
import time
import math
import logging
import requests
import asyncio
import aiohttp
from typing import Optional, Tuple, Dict
from exchange import BingXAsync
from settings import CONFIG

logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger(__name__)

ENDPOINT = "https://open-api.bingx.com"
API_KEY = os.getenv("BINGX_API_KEY")
SECRET = os.getenv("BINGX_SECRET_KEY")
REQ_TIMEOUT = 5

async def load_min_lot_cache(ex: BingXAsync) -> None:
    """Один раз при старте качаем мин-лоты всех контрактов."""
    global _MIN_LOT_CACHE
    try:
        info = await ex._signed_request("GET", "/openApi/swap/v2/quote/contracts")
        for item in info["data"]:
            _MIN_LOT_CACHE[item["symbol"]] = {
                "minQty":   float(item["minQty"]),
                "stepSize": float(item["stepSize"]),
            }
        log.info("✅ Loaded minQty/stepSize for %d contracts", len(_MIN_LOT_CACHE))
    except Exception as e:
        log.warning("⚠️  Failed to load min-lot cache: %s", e)
        _MIN_LOT_CACHE = {}

def get_min_lot(symbol: str) -> tuple[float, float]:
    data = _MIN_LOT_CACHE.get(symbol, {})
    return data.get("minQty", 156623.0), data.get("stepSize", 1.0)


def _get_precision(symbol: str) -> Tuple[int, int]:
    """Синхронно получаем точность цены и кол-ва из кеша или дефолт."""
    public_sym = symbol
    try:
        r = requests.get(f"{ENDPOINT}/openApi/swap/v2/quote/contracts",
                         params={"symbol": public_sym}, timeout=REQ_TIMEOUT)
        r.raise_for_status()
        for s in r.json()["data"]:
            if s["symbol"] == public_sym:
                return int(s["pricePrecision"]), int(s["quantityPrecision"])
    except Exception as e:
        log.warning("⚠️ _get_precision failed for %s: %s", symbol, e)
    return 4, 3


# --------------------  АСИНХРОННЫЙ ВХОД  --------------------
async def limit_entry(ex: BingXAsync,
                      symbol: str,
                      side: str,
                      usd_qty: float,
                      leverage: int,
                      sl_price: float,
                      tp_price: float
                      ) -> Optional[Tuple[str, float, float]]:
    price_prec, lot_prec = _get_precision(symbol)

    # ---------- стакан ----------
    book = await ex.order_book(symbol, limit=5)
    if not book or not book.get("bids") or not book.get("asks"):
        log.warning("⚠️ %s – пустой стакан", symbol)
        return None

    if side == "BUY":
        entry_px = float(book["bids"][0][0]) - 10 ** -price_prec
    else:
        entry_px = float(book["asks"][0][0]) + 10 ** -price_prec

    # ---------- объём ----------
    qty_usd  = usd_qty * leverage
    qty_coin = round(qty_usd / entry_px, lot_prec)

    # ---------- мин-лот и шаг ----------
    min_qty, step_size = get_min_lot(symbol)

    # ---------- корректировка ----------
    qty_coin = max(qty_coin, min_qty)
    qty_coin = math.ceil(qty_coin / step_size) * step_size

    # ---------- строки ----------
    entry_px_str = f"{entry_px:.{price_prec}f}".rstrip("0").rstrip(".")
    qty_coin_str = f"{qty_coin:.{lot_prec}f}".rstrip("0").rstrip(".")

    params = {
        "symbol":       symbol,
        "side":         side,
        "type":         "LIMIT",
        "timeInForce":  "PostOnly",
        "positionSide": "LONG" if side == "BUY" else "SHORT",
        "price":        entry_px_str,
        "quantity":     qty_coin_str,
        "leverage":     str(leverage),
    }

        resp = await ex._signed_request("POST", "/openApi/swap/v2/trade/order", params)
    if resp.get("code") != 0 or "data" not in resp or "order" not in resp["data"]:
            log.warning("⚠️ %s – биржа отвергла ордер: %s", symbol, resp)
            return None
    log.debug("RAW RESP: %s", resp)
    
    order_id = resp["data"]["order"]["id"]
    log.info("💡 %s %s limit @ %s  qty=%s  orderId=%s",
             symbol, side, entry_px_str, qty_coin_str, order_id)
    return order_id, float(entry_px_str), float(qty_coin_str)

# --------------------  ОЖИДАНИЕ / ОТМЕНА  --------------------
async def await_fill_or_cancel(ex: BingXAsync,
                               order_id: str,
                               symbol: str,
                               max_sec: float = 8) -> Optional[float]:
    t0 = time.time()
    while time.time() - t0 < max_sec:
        try:
            order = await ex.fetch_order(symbol, order_id)
            if order.get("status") == "FILLED":
                return float(order["avgPrice"])
        except Exception as e:
            log.warning("⚠️  await_fill %s: %s", symbol, e)
        await asyncio.sleep(0.5)

    try:
        await ex._signed_request("DELETE", "/openApi/swap/v2/trade/order",
                                 {"symbol": symbol, "orderId": order_id})
        log.warning("⏭ %s лимит не исполнен – отмена", symbol)
    except Exception as e:
        log.warning("⚠️  await_cancel %s: %s", symbol, e)
    return None


# --------------------  SL / TP  --------------------
async def limit_sl_tp(ex: BingXAsync,
                      symbol: str,
                      side: str,
                      qty_coin: float,
                      sl_price: float,
                      tp_price: float) -> Tuple[str, str]:
    opposite = "SELL" if side == "BUY" else "BUY"
    ids = []
    for name, px in (("SL", sl_price), ("TP", tp_price)):
        params = {
            "symbol":       symbol,
            "side":         opposite,
            "type":         "LIMIT",
            "timeInForce":  "PostOnly",
            "positionSide": "LONG" if opposite == "SELL" else "SHORT",
            "price":        str(px),
            "quantity":     str(qty_coin),
        }
        resp = await ex._signed_request("POST", "/openApi/swap/v2/trade/order", params)
        oid = resp["data"]["order"]["id"]
        ids.append(oid)
        log.info("🛑 %s %s limit @ %s  id=%s", name, symbol, px, oid)
    return tuple(ids)
