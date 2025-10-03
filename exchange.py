import asyncio, os, hmac, time, hashlib, aiohttp
from typing import Optional, Dict, Any

class BingXAsync:
    def __init__(self, api_key: str, secret: str):
        self.key = api_key
        self.sec = secret
        self.base = "https://open-api.bingx.com"
        self.sess: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self.sess = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.sess.close()

    def _sign(self, query: str) -> str:
        return hmac.new(self.sec.encode(), query.encode(), hashlib.sha256).hexdigest()

    async def _request(self, method: str, path: str, payload: Optional[Dict] = None):
        ts = str(int(time.time() * 1000))
        payload = payload or {}
        payload["timestamp"] = ts
        query = "&".join([f"{k}={v}" for k, v in payload.items()])
        signature = self._sign(query)
        url = f"{self.base.rstrip()}{path}?{query}&signature={signature}"
        headers = {"X-BX-APIKEY": self.key}

        async with self.sess.request(method, url, headers=headers) as r:
            r.raise_for_status()
            js = await r.json()
            if js.get("code", 0) != 0:
                raise RuntimeError(f"BingX error: {js}")
            return js
    async def get_contract_info(self, symbol: str) -> dict:
        path = "/openApi/swap/v2/public/contractInfo"
        return await self._request("GET", path, {"symbol": symbol})

    async def set_leverage(self, symbol: str, leverage: int) -> dict:
        path = "/openApi/swap/v2/trade/leverage"
        return await self._request("POST", path, {"symbol": symbol, "leverage": leverage})

    async def klines(self, symbol: str, interval: str = "1m", limit: int = 150):
        path = "/openApi/swap/v2/quote/klines"
        data = await self._request("GET", path, {"symbol": symbol, "interval": interval, "limit": limit})
        return data["data"]

    async def order_book(self, symbol: str, limit: int = 5):
        path = "/openApi/swap/v2/quote/depth"
        data = await self._request("GET", path, {"symbol": symbol, "limit": limit})
        return data["data"]

    async def balance(self):
        path = "/openApi/swap/v2/user/balance"
        return await self._request("GET", path)

    async def place_order(self, symbol: str, side: str, order_type: str,
                          quantity: float, price: Optional[float] = None, post_only: bool = True):
        path = "/openApi/swap/v2/trade/order"
        # режим Hedge → LONG / SHORT, а не BOTH
        hedge_side = "LONG" if side.upper() == "BUY" else "SHORT"

        payload = {
            "symbol": symbol,
            "side": side.upper(),
            "type": order_type.upper(),
            "quantity": f"{quantity:.3f}",
            "positionSide": hedge_side,   # <- исправлено
            "timeInForce": "GTC",
            "postOnly": post_only,
        }
        if price:
            payload["price"] = f"{price:.5f}"
        return await self._request("POST", path, payload)

    async def close_position(self, symbol: str, side: str, quantity: float):
        return await self.place_order(symbol, side, "MARKET", quantity, post_only=False)

    async def fetch_positions(self):
        path = "/openApi/swap/v2/user/positions"
        return await self._request("GET", path)

    async def cancel_all(self, symbol: str):
        path = "/openApi/swap/v2/trade/allOpenOrders"
        await self._request("DELETE", path, {"symbol": symbol})
