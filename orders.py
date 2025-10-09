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
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("aiohttp").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)

ENDPOINT = "https://open-api.bingx.com"
ALTERNATE_ENDPOINT = "https://open-api.bingx.io"  # ← альтернатива
API_KEY = os.getenv("BINGX_API_KEY")
SECRET = os.getenv("BINGX_SECRET_KEY")
REQ_TIMEOUT = 5

async def _private_request(method: str, endpoint: str, params: dict, max_retries=3) -> dict:
    for attempt in range(max_retries):
        try:
            url = ENDPOINT + endpoint
            if attempt > 0:
                url = ALTERNATE_ENDPOINT + endpoint  # попробовать запасной домен
            
            query = self._sign_query(params)
            full_url = f"{url}?{query}"
            
            async with self.sess.request(method, full_url, headers={"X-BX-APIKEY": self.key}) as r:
                js = await r.json()
                if js.get("code") != 0:
                    raise RuntimeError(js["msg"])
                return js
                
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(2 ** attempt)  # экспоненциальная задержка

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

SAFE_MIN = {
    "DOGE-USDT": (7.0, 1.0),
    "LTC-USDT":  (0.1, 0.01),
    "SUI-USDT":  (1.0, 1.0),
    "SHIB-USDT": (100000.0, 1000.0),
    "BNB-USDT":  (0.01, 0.001),
    "XRP-USDT":  (1.0, 1.0),
}

def get_min_lot(symbol: str) -> tuple[float, float]:
    data = _MIN_LOT_CACHE.get(symbol, {})
    if data:
        return float(data["minQty"]), float(data["stepSize"])
    # Fallback — точные значения BingX
    return SAFE_MIN.get(symbol, (1.0, 0.001))
    
    if min_qty is None or step_size is None:
        log.error(f"⚠️ minQty/stepSize не найдены для {symbol}! Использую безопасные дефолты.")
        # Безопасные дефолты для разных пар:
        if "SHIB" in symbol:
            return 100000.0, 1000.0
        elif "DOGE" in symbol:
            return 100.0, 1.0
        else:
            return 1.0, 0.001  # для LTC, SUI, BNB и т.д.
    
    return float(min_qty), float(step_size)


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
                      side: str,  # "BUY" для LONG, "SELL" для SHORT
                      qty_coin: float,
                      entry_px: float,
                      sl_price: float,
                      tp_price: float,
                      equity: float) -> Optional[Tuple[str, float, float]]:
    price_prec, lot_prec = _get_precision(symbol)
    if qty_coin * entry_px > equity * CONFIG.LEVERAGE:
        log.error(f"❌ {symbol} — номинал (${qty_coin * entry_px:.2f}) превышает маржу! Отмена.")
        return None
    book = await ex.order_book(symbol, limit=5)
    if not book or not book.get("bids") or not book.get("asks"):
        log.warning("⚠️ %s – пустой стакан", symbol)
        return None

    # Рассчитываем цену лимитного входа
    tick = 10 ** -price_prec
    if side == "BUY":  # LONG - покупаем чуть ниже текущей цены
        entry_px = float(book["bids"][0][0]) - tick * 3
    else:  # SHORT - продаем чуть выше текущей цены
        entry_px = float(book["asks"][0][0]) + tick * 3

    # Проверка минимального номинала — но не выше разумного
    min_nom = 2.5
    current_nom = qty_coin * entry_px
    if current_nom < min_nom:
        # Но не увеличиваем, если это нарушит лимиты или маржу
        proposed_qty = min_nom / entry_px
        # Если даже min_nom слишком большой — пропускаем
        if proposed_qty > qty_coin * 3:  # не более чем в 3 раза увеличиваем
            log.warning(f"⏭️ {symbol} — min_nom требует слишком большой объём. Пропуск.")
            return None
        qty_coin = proposed_qty

    # Округление количества
    min_qty, step_size = get_min_lot(symbol)
    qty_coin = max(qty_coin, min_qty)
    qty_coin = math.ceil(qty_coin / step_size) * step_size

    # ⚠️ УДАЛЕНО: проверка max_nom — она уже сделана в main.py

    log.info("♻️ %s equity=%.2f$  qty=%.6f  nominal=%.2f$",
             symbol, equity, qty_coin, qty_coin * entry_px)

    entry_px_str = f"{entry_px:.{price_prec}f}".rstrip("0").rstrip(".")
    qty_coin_str = f"{qty_coin:.{lot_prec}f}".rstrip("0").rstrip(".")

    # Правильный лимитный ордер для входа
    position_side = "LONG" if side == "BUY" else "SHORT"

    params = {
        "symbol":       symbol,
        "side":         side,
        "type":         "LIMIT",
        "timeInForce":  "PostOnly",
        "price":        entry_px_str,
        "quantity":     qty_coin_str,
        "positionSide": position_side,
    }

    resp = await ex._signed_request("POST", "/openApi/swap/v2/trade/order", params)
    if resp.get("code") != 0:
        log.warning("⚠️ %s – биржа отвергла ордер: %s", symbol, resp)
        return None

    order_data = resp.get("data", {}).get("order", {})
    if not order_data or "id" not in order_data:
        log.warning("⚠️ %s – в ответе нет order.id: %s", symbol, resp)
        return None

    order_id = order_data["id"]
    log.info("💡 %s %s limit @ %s  qty=%s  orderId=%s",
             symbol, side, entry_px_str, qty_coin_str, order_id)
    return order_id, float(entry_px_str), float(qty_coin)
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
    ids = []
    for name, px in (("SL", sl_price), ("TP", tp_price)):
        opposite = "SELL" if side == "BUY" else "BUY"   # ← ЗДЕСЬ, внутри цикла
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
