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
    # Копируем параметры, чтобы не менять оригинал
    params = params.copy()

    # 1. Добавляем timestamp (без signature!)
    params["timestamp"] = int(time.time() * 1000)

    # 2. Сортируем параметры и создаем строку для подписи — БЕЗ signature!
    sorted_items = sorted(params.items())
    query_str = "&".join(f"{k}={v}" for k, v in sorted_items)

    # 3. Подписываем строку (без signature!)
    signature = _sign(params)

    # 4. Теперь добавляем signature в params — уже после подписи
    params["signature"] = signature

    # 5. Формируем URL
    url = ENDPOINT.rstrip() + endpoint.lstrip()
    headers = {
        "X-BX-APIKEY": API_KEY,
        "Content-Type": "application/x-www-form-urlencoded",
    }

    # 🌐 ПОПЫТКА ИСПОЛЬЗОВАТЬ ПРОКСИ — ДИНАМИЧЕСКИЙ ВЫБОР
    proxies = None
    try:
        # Получаем список бесплатных прокси (работает на Render)
        resp = requests.get("https://www.free-proxy-list.net/", timeout=8)
        if resp.status_code == 200:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, 'html.parser')
            proxies_list = []
            for row in soup.find('table', id='proxylisttable').find_all('tr')[1:10]:
                cols = row.find_all('td')
                if len(cols) > 6 and cols[6].text.strip() == 'yes':  # HTTPS = yes
                    ip = cols[0].text.strip()
                    port = cols[1].text.strip()
                    proxies_list.append(f"http://{ip}:{port}")
            if proxies_list:
                proxies = {"http": random.choice(proxies_list), "https": random.choice(proxies_list)}
                logging.info("🔄 Используем прокси: %s", proxies["http"])
    except Exception as e:
        logging.warning("⚠️ Не удалось получить прокси: %s", e)

    # 6. Отправляем запрос — ОДИН РАЗ — с подписью и прокси (если есть)
    print(f"=== MAYAK ===")
    print(f"METHOD : {method}")
    print(f"URL    : {url}")
    print(f"QUERY  : {query_str}")  # ← ЭТО СТРОКА, КОТОРУЮ ПОДПИСАЛИ
    print(f"SIGNATURE: {signature}")
    print(f"HEADERS: {headers}")
    print(f"PROXIES: {proxies}")
    print(f"=== END MAYAK ===")

    try:
        r = requests.request(
            method,
            url,
            params=params,
            headers=headers,
            timeout=REQ_TIMEOUT,
            proxies=proxies,
            verify=False  # Игнорируем SSL — прокси могут быть ненадёжными
        )

        print(f"STATUS : {r.status_code}")
        print(f"TEXT   : {r.text[:300]}")
        print(f"=== END MAYAK ===")

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
    print("DBG limit_entry", symbol, side, usd_qty, leverage) 
    public_sym = symbol

    # ---------- стакан ----------
    try:
        raw_resp = requests.get(
            f"{ENDPOINT}/openApi/swap/v2/quote/depth",
            params={"symbol": public_sym, "limit": 5},
            timeout=REQ_TIMEOUT
        )
        raw_resp.raise_for_status()
        raw = raw_resp.json()
    except Exception as e:
        logging.warning("⚠️ %s – ошибка запроса стакана: %s", symbol, e)
        return None

    book = raw.get("data", {})
    if not book or "asks" not in book or "bids" not in book or not book["asks"] or not book["bids"]:
        logging.warning("⚠️ %s – пустой стакан", symbol)
        return None

    # цена входа          
    if side == "BUY":
        entry_px = float(book["bids"][0][0]) - 10 ** -price_prec
    else:
        entry_px = float(book["asks"][0][0]) + 10 ** -price_prec

    # ---------- марковая цена ----------
    try:
        mark_resp = requests.get(
            f"{ENDPOINT}/openApi/swap/v2/quote/price",
            params={"symbol": public_sym},
            timeout=REQ_TIMEOUT
        )
        mark_resp.raise_for_status()
        mark_raw = mark_resp.json()
    except Exception as e:
        logging.warning("⚠️ %s – ошибка запроса марковой цены: %s", symbol, e)
        return None

    if not mark_raw or mark_raw.get("code") != 0 or "data" not in mark_raw or not mark_raw["data"]:
        logging.warning("⚠️ %s – невалидный ответ марковой цены: %s", symbol, mark_raw)
        return None
    mark = float(mark_raw["data"]["price"])

    # 4. объём и ордер
    qty_usd = usd_qty * leverage
    qty_coin = round(qty_usd / entry_px, lot_prec)
    
    # ---------- нормализация по биржевым правилам ----------
    entry_px = format(round(entry_px, price_prec), f".{price_prec}f").rstrip('0').rstrip('.')
    qty_coin = str(int(round(qty_coin, lot_prec))) if lot_prec == 0 else \
               format(round(qty_coin, lot_prec), f".{lot_prec}f").rstrip('0').rstrip('.')
    if float(qty_coin) <= 0:
        logging.warning("⚠️ %s – quantity ≤ 0", symbol)
        return None

    # ← УБИРАЕМ дефис для private endpoints
    symbol_private = symbol.replace("-", "")

    # ← НИКАКИХ timestamp, signature — только базовые параметры!
    params = {
        "symbol": symbol_private,
        "side": side,
        "type": "LIMIT",
        "timeInForce": "POST_ONLY",
        "price": entry_px,
        "quantity": qty_coin,
        "leverage": leverage,
    }

    # ← _private_request сам добавит timestamp и signature
    resp = _private_request("POST", "/openApi/swap/v2/trade/order", params)

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
        resp = _private_request("POST", "/openApi/swap/v2/trade/order", params)
        logging.info("🛑 %s %s limit @ %s", name, symbol, px)
