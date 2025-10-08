import os, time, math, hmac, hashlib, requests, logging
from typing import Optional, Tuple
from settings import CONFIG
import random

logging.basicConfig(level=logging.DEBUG)

ENDPOINT = "https://open-api.bingx.com"
API_KEY  = os.getenv("BINGX_API_KEY")
SECRET   = os.getenv("BINGX_SECRET_KEY")

REQ_TIMEOUT = 5   # ← общий таймаут для всех запросов


import os
import time
import math
import hmac
import hashlib
import requests
import logging
from typing import Optional, Dict, Any
from settings import CONFIG

logging.basicConfig(level=logging.DEBUG)

ENDPOINT = "https://open-api.bingx.com"
API_KEY = os.getenv("BINGX_API_KEY")
SECRET = os.getenv("BINGX_SECRET_KEY")

REQ_TIMEOUT = 5

def _get_precision(symbol: str) -> Tuple[int, int]:
    public_sym = symbol
    try:
        r = requests.get(f"{ENDPOINT}/openApi/swap/v2/quote/contracts",
                         params={"symbol": public_sym}, timeout=REQ_TIMEOUT)
        r.raise_for_status()
        for s in r.json()["data"]:
            if s["symbol"] == public_sym:
                return int(s["pricePrecision"]), int(s["quantityPrecision"])
    except Exception as e:
        logging.warning("⚠️ _get_precision failed for %s: %s", symbol, e)
    return 4, 3

def _sign(params: dict) -> str:
    query = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
    return hmac.new(SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()

def _private_request(method: str, endpoint: str, params: dict) -> dict:
    params = params.copy()
    params["timestamp"] = int(time.time() * 1000)

    # 1. сортируем и строим query-string
    sorted_items = sorted(params.items())
    query_str = "&".join(f"{k}={v}" for k, v in sorted_items)

    # 2. подпись
    signature = hmac.new(SECRET.encode(), query_str.encode(), hashlib.sha256).hexdigest()
    query_str += f"&signature={signature}"

    # 3. финальный URL
    url = ENDPOINT.rstrip("/") + "/" + endpoint.lstrip("/") + "?" + query_str
    headers = {"X-BX-APIKEY": API_KEY}

    # 4. запрос БЕЗ params, чтобы requests не трогал порядок
    r = requests.request(method, url, headers=headers, timeout=REQ_TIMEOUT, verify=False)

    print("=== MAYAK ===")
    print("METHOD :", method)
    print("URL    :", url)
    print("STATUS :", r.status_code)
    print("TEXT   :", r.text[:300])
    print("=== END ===")

    r.raise_for_status()
    return r.json()

    except Exception as e:
        logging.error("❌ Ошибка при запросе через прокси: %s", e)
        raise RuntimeError(f"Не удалось выполнить запрос: {e}")

def _get_precision(symbol: str) -> Tuple[int, int]:
    public_sym = symbol
    try:
        r = requests.get(f"{ENDPOINT}/openApi/swap/v2/quote/contracts",
                         params={"symbol": public_sym}, timeout=REQ_TIMEOUT)
        r.raise_for_status()
        for s in r.json()["data"]:
            if s["symbol"] == public_sym:
                return int(s["pricePrecision"]), int(s["quantityPrecision"])
    except Exception as e:
        logging.warning("⚠️ _get_precision failed for %s: %s", symbol, e)
    return 4, 3

def _sign(params: dict) -> str:
    query = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
    return hmac.new(SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()

def limit_entry(symbol: str, side: str, usd_qty: float, leverage: int,
                sl_price: float, tp_price: float) -> Optional[Tuple[str, float, float]]:
    price_prec, lot_prec = _get_precision(symbol)
    public_sym = symbol

    # ---------- стакан ----------
    try:
        raw = requests.get(
            f"{ENDPOINT}/openApi/swap/v2/quote/depth",
            params={"symbol": public_sym, "limit": 5}, timeout=REQ_TIMEOUT
        ).json()["data"]
    except Exception as e:
        logging.warning("⚠️ %s – ошибка стакана: %s", symbol, e)
        return None

    if side == "BUY":
        entry_px = float(raw["bids"][0][0]) - 10 ** -price_prec
    else:
        entry_px = float(raw["asks"][0][0]) + 10 ** -price_prec

    # ---------- объём ----------
    qty_usd = usd_qty * leverage
    qty_coin = round(qty_usd / entry_px, lot_prec)

    # ---------- НОРМАЛИЗУЕМ К СТРОКЕ ----------
    entry_px_str = f"{entry_px:.{price_prec}f}".rstrip("0").rstrip(".")
    qty_coin_str = f"{qty_coin:.{lot_prec}f}".rstrip("0").rstrip(".")
    if float(qty_coin_str) <= 0:
        logging.warning("⚠️ %s – quantity ≤ 0", symbol)
        return None

    params = {
        "symbol": symbol.replace("-", ""),
        "side": side,
        "type": "LIMIT",
        "timeInForce": "POST_ONLY",
        "price": entry_px_str,        # ← строка
        "quantity": qty_coin_str,     # ← строка
        "leverage": str(leverage),    # ← строка
    }

    resp = _private_request("POST", "/openApi/swap/v2/trade/order", params)
    if resp.get("code") != 0:
        logging.warning("⚠️ %s – биржа отвергла ордер: %s", symbol, resp)
        return None

    order_id = resp["data"]["order"]["id"]
    logging.info("💡 %s %s limit @ %s  qty=%s  orderId=%s",
                 symbol, side, entry_px_str, qty_coin_str, order_id)
    return order_id, float(entry_px_str), float(qty_coin_str)

    # ---------- размещение ордера ----------
    try:
        if not resp or resp.get("code") != 0 or "data" not in resp or not resp["data"] or "order" not in resp["data"]:
            logging.warning("⚠️ %s – биржа отвергла ордер: %s", symbol, resp)
            return None
        order_id = resp["data"]["order"]["id"]
    except Exception as e:
        logging.warning("⚠️ %s – исключение при размещении ордера: %s", symbol, e)
        return None

    logging.info("💡 %s %s limit @ %s  qty=%s  orderId=%s",
                 symbol, side, entry_px, qty_coin, order_id)
    print("DBG перед успехом", symbol, order_id, entry_px, qty_coin)
    return order_id, entry_px, qty_coin
    

def await_fill_or_cancel(order_id: str, symbol: str, max_sec: float = 8) -> Optional[float]:
    t0 = time.time()
    print("DBG await_fill_or_cancel", symbol, order_id)
    while time.time() - t0 < max_sec:
        # ---------- проверка статуса ----------
        try:
            resp = _private_request("GET", "/openApi/swap/v2/trade/order",
                                    {"symbol": symbol, "orderId": order_id})
            order = resp.get("data", {})
            if order.get("status") == "FILLED":
                return float(order["avgPrice"])
        except Exception as e:
            print("DBG await exception", e)
            logging.warning("⚠️  await_fill %s: %s", symbol, e)
        time.sleep(0.5)

    # не успели – отменяем
    try:
        _private_request("DELETE", "/openApi/swap/v2/trade/order",
                         {"symbol": symbol, "orderId": order_id})
        logging.warning("⏭ %s лимит не исполнен – отмена", symbol)
    except Exception as e:
        logging.warning("⚠️  await_cancel %s: %s", symbol, e)
    return None
   

def limit_sl_tp(symbol: str, side: str, qty_coin: float,
                sl_price: float, tp_price: float) -> Tuple[str, str]:
    """Создаёт 2 лимитных ордера (SL и TP) одновременно.
    Возвращает (orderId_SL, orderId_TP)"""
    opposite = "SELL" if side == "BUY" else "BUY"
    ids = []
    for name, px in (("SL", sl_price), ("TP", tp_price)):
        params = {
            "symbol": symbol.replace("-", ""),   # убираем дефис
            "side": opposite,
            "type": "LIMIT",
            "timeInForce": "POST_ONLY",
            "price": str(px),
            "quantity": str(qty_coin),
            # timestamp НЕ добавляем – добавит _private_request
        }
        resp = _private_request("POST", "/openApi/swap/v2/trade/order", params)
        oid = resp["data"]["order"]["id"]
        ids.append(oid)
        logging.info("🛑 %s %s limit @ %s  id=%s", name, symbol, px, oid)
    return tuple(ids)
