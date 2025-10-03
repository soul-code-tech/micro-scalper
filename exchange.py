import asyncio
import os
import hmac
import time
import hashlib
import aiohttp
from typing import Optional, Dict, Any


class BingXAsync:
    def __init__(self, api_key: str, secret: str):
        self.key = api_key
        self.sec = secret
        self.base = "https://open-api.bingx.com"  # Убран лишний пробел!
        self.sess: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self.sess = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self.sess:
            await self.sess.close()

    def _sign(self, query: str) -> str:
        return hmac.new(self.sec.encode(), query.encode(), hashlib.sha256).hexdigest()

    async def _signed_request(self, method: str, path: str, params: Optional[Dict] = None):
        """Подписанный запрос (для приватных эндпоинтов)"""
        params = params or {}
        params["timestamp"] = str(int(time.time() * 1000))
        query = "&".join([f"{k}={v}" for k, v in params.items()])
        signature = self._sign(query)
        url = f"{self.base}{path}?{query}&signature={signature}"
        headers = {"X-BX-APIKEY": self.key}

        async with self.sess.request(method, url, headers=headers) as r:
            js = await r.json()
            if js.get("code", 0) != 0:
                raise RuntimeError(f"BingX error: {js}")
            return js

    async def _public_request(self, method: str, path: str, params: Optional[Dict] = None):
        """Публичный запрос (без подписи)"""
        params = params or {}
        url = f"{self.base}{path}"
        if params:
            query = "&".join([f"{k}={v}" for k, v in params.items()])
            url += f"?{query}"

        async with self.sess.request(method, url) as r:
            js = await r.json()
            if js.get("code", 0) != 0:
                raise RuntimeError(f"BingX error: {js}")
            return js

    # ---------- ПУБЛИЧНЫЕ МЕТОДЫ ----------
    async def get_all_contracts(self) -> dict:
        """Получить все контракты (вместо get_contract_info)"""
        return await self._public_request("GET", "/openApi/future/v1/public/getAllContracts")

    async def klines(self, symbol: str, interval: str = "1m", limit: int = 150):
        data = await self._public_request("GET", "/openApi/future/v1/market/klines", {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        })
        return data["data"]

    async def order_book(self, symbol: str, limit: int = 5):
        data = await self._public_request("GET", "/openApi/future/v1/market/depth", {
            "symbol": symbol,
            "limit": limit
        })
        return data["data"]

    # ---------- ПРИВАТНЫЕ МЕТОДЫ ----------
    async def balance(self):
        return await self._signed_request("GET", "/openApi/future/v1/account/balance")

    async def set_leverage(self, symbol: str, leverage: int, side: str) -> dict:
        """Обязательно указывать side: 'LONG' или 'SHORT'"""
        return await self._signed_request("POST", "/openApi/future/v1/position/setLeverage", {
            "symbol": symbol,
            "leverage": str(leverage),
            "side": side
        })

    async def place_order(self, symbol: str, side: str, order_type: str,
                          quantity: float, price: Optional[float] = None, post_only: bool = True):
        # BingX использует side: BUY/SELL и positionSide: LONG/SHORT
        position_side = "LONG" if side.upper() == "BUY" else "SHORT"
        payload = {
            "symbol": symbol,
            "side": side.upper(),
            "positionSide": position_side,
            "type": order_type.upper(),
            "quantity": f"{quantity:.3f}",
            "timeInForce": "GTC"
        }
        if price is not None:
            payload["price"] = f"{price:.8f}"
        if post_only:
            payload["postOnly"] = "true"

        return await self._signed_request("POST", "/openApi/future/v1/trade/order", payload)

    async def place_stop_order(self, symbol: str, side: str, qty: float,
                               stop_px: float, order_type: str = "STOP_MARKET") -> dict:
        position_side = "LONG" if side.upper() == "BUY" else "SHORT"
        payload = {
            "symbol": symbol,
            "side": side.upper(),
            "positionSide": position_side,
            "type": order_type,
            "quantity": f"{qty:.3f}",
            "stopPrice": f"{stop_px:.8f}",
            "timeInForce": "GTC"
        }
        return await self._signed_request("POST", "/openApi/future/v1/trade/order", payload)

    async def amend_stop_order(self, symbol: str, order_id: str, stop_px: float) -> dict:
        payload = {
            "symbol": symbol,
            "orderId": order_id,
            "stopPrice": f"{stop_px:.8f}"
        }
        return await self._signed_request("PUT", "/openApi/future/v1/trade/order", payload)

    async def close_position(self, symbol: str, side: str, quantity: float):
        return await self.place_order(symbol, side, "MARKET", quantity, post_only=False)

    async def fetch_positions(self):
        return await self._signed_request("GET", "/openApi/future/v1/position/allPositions")

    async def cancel_all(self, symbol: str):
        await self._signed_request("DELETE", "/openApi/future/v1/trade/allOpenOrders", {"symbol": symbol})

    async def fetch_order(self, symbol: str, order_id: str):
        return await self._signed_request("GET", "/openApi/future/v1/trade/queryOrder", {
            "symbol": symbol,
            "orderId": order_id
        })
