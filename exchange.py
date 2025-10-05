import asyncio
import hmac
import time
import hashlib
import aiohttp
from typing import Optional, Dict, Any
import logging

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


class BingXAsync:
    def __init__(self, api_key: str, secret: str,
                 session: Optional[aiohttp.ClientSession] = None):
        self.key = api_key
        self.sec = secret
        self.base = "https://open-api.bingx.com"  # ✅ ИСПРАВЛЕНО — УБРАНЫ ПРОБЕЛЫ!
        self._external_sess = session
        self.sess: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        if self._external_sess is None:
            timeout = aiohttp.ClientTimeout(total=10)
            self.sess = aiohttp.ClientSession(
                headers={"User-Agent": "Quantum-Scalper/1.0"},
                timeout=timeout
            )
        else:
            self.sess = self._external_sess
        return self

    async def __aexit__(self, exc_type, exc, tb):
        # закрываем только если создали сами
        if self._external_sess is None and self.sess:
            await self.sess.close()

    # ---------- ПОДПИСЬ ----------
    def _sign(self, query: str) -> str:
        return hmac.new(self.sec.encode(), query.encode(), hashlib.sha256).hexdigest()

    def _sign_query(self, payload: dict) -> str:
        """Сортируем, добавляем timestamp, подписываем"""
        payload = payload or {}
        payload["timestamp"] = str(int(time.time() * 1000))
        payload["recvWindow"] = "5000"
        query = "&".join(f"{k}={v}" for k, v in sorted(payload.items()))
        sign = self._sign(query)
        return query + "&signature=" + sign

    # ---------- ПУБЛИЧНЫЙ ЗАПРОС ----------
    async def _public_get(self, path: str, params: Optional[Dict] = None):
        url = f"{self.base}{path}"
        if params:
            url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
        async with self.sess.get(url) as r:
            js = await r.json()
            if js.get("code", 0) != 0:
                raise RuntimeError(f"BingX public error: {js}")
            return js

    # ---------- ПРИВАТНЫЙ ЗАПРОС ----------
    async def _signed_request(self, method: str, path: str, payload: Optional[Dict] = None):
        query = self._sign_query(payload or {})
        url = f"{self.base}{path}?{query}"
        headers = {"X-BX-APIKEY": self.key}
        async with self.sess.request(method, url, headers=headers) as r:
            js = await r.json()
            if js.get("code", 0) != 0:
                raise RuntimeError(f"BingX signed error: {js}")
            return js

    # ---------- ПУБЛИЧНЫЕ МЕТОДЫ ----------
    async def klines(self, symbol: str, interval: str = "1m", limit: int = 150):
        try:
            data = await self._public_get("/openApi/swap/v2/quote/klines",
                                          {"symbol": symbol, "interval": interval, "limit": limit})
            return data["data"]
        except Exception as e:
            log.warning("❌ %s klines fail: %s", symbol, e)
            return []

    async def order_book(self, symbol: str, limit: int = 5):
        try:
            data = await self._public_get("/openApi/swap/v2/quote/depth",
                                          {"symbol": symbol, "limit": limit})
            return data["data"]
        except Exception as e:
            log.warning("❌ %s order_book fail: %s", symbol, e)
            return {"bids": [], "asks": []}

    # ---------- ПРИВАТНЫЕ МЕТОДЫ ----------
    
    # Обязательно внутри класса BingXAsync
    async def balance(self):
        raw = await self._signed_request("GET", "/openApi/swap/v3/user/balance")
        data = raw.get("data", [])

        if not data:
            raise RuntimeError("Empty balance data")

        # Ищем USDT
        for entry in data:
            if entry.get("asset") == "USDT":
                equity_str = entry.get("equity", "0")
                try:
                    return float(equity_str)
                except ValueError as e:
                    raise RuntimeError(f"Cannot parse equity '{equity_str}': {e}")
    
        # Если USDT не найден — берём первый актив
        equity_str = data[0].get("equity", "0")
        return float(equity_str)

    async def set_leverage(self, symbol: str, leverage: int, side: str) -> dict:
        return await self._signed_request("POST", "/openApi/swap/v2/trade/leverage",
                                          {"symbol": symbol, "leverage": leverage, "side": side})

   
    async def place_order(self, symbol, side, type, quantity, price, time_in_force="GTC"):
        payload = {
            "symbol": symbol,
            "side": side,
            "type": type,
            "quantity": str(quantity),
            "price": f"{price:.8f}",
            "timeInForce": time_in_force,
            "positionSide": side,   # ← теперь точно LONG / SHORT
        }
        return await self._signed_request("POST", "/openApi/swap/v2/trade/order", payload)

    async def amend_stop_order(self, symbol: str, order_id: str, stop_px: float) -> dict:
        payload = {
            "symbol": symbol,
            "orderId": order_id,
            "stopPrice": f"{stop_px:.8f}",
        }
        return await self._signed_request("PUT", "/openApi/swap/v2/trade/order", payload)

    async def close_position(self, symbol: str, side: str, quantity: float):
        return await self.place_order(symbol, side, "MARKET", quantity, post_only=False)

    async def fetch_positions(self):
        return await self._signed_request("GET", "/openApi/swap/v2/user/positions")

    async def cancel_all(self, symbol: str):
        await self._signed_request("DELETE", "/openApi/swap/v2/trade/allOpenOrders", {"symbol": symbol})

    async def fetch_order(self, symbol: str, order_id: str):
        resp = await self._signed_request("GET", "/openApi/swap/v2/trade/order", {
            "symbol": symbol,
            "orderId": order_id
        })
        return resp.get("data", {})
