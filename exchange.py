import asyncio
import hmac
import time
import hashlib
import aiohttp
from typing import Optional, Dict, Any
import logging

log = logging.getLogger(__name__)

class BingXAsync:
    def __init__(self, api_key: str, secret: str):
        self.key = api_key
        self.sec = secret
        self.base = "https://open-api.bingx.io"  # ✅ Обход Cloudflare
        self.sess: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        timeout = aiohttp.ClientTimeout(total=10)
        self.sess = aiohttp.ClientSession(
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; TradingBot/1.0)",
                "Accept": "application/json",
            },
            timeout=timeout
        )
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self.sess:
            await self.sess.close()

    def _sign(self, query: str) -> str:
        return hmac.new(self.sec.encode(), query.encode(), hashlib.sha256).hexdigest()

    def _sign_query(self, payload: dict) -> str:
        payload = payload.copy()
        payload["timestamp"] = str(int(time.time() * 1000))
        payload["recvWindow"] = "5000"
        query = "&".join(f"{k}={v}" for k, v in sorted(payload.items()))
        sign = self._sign(query)
        return query + "&signature=" + sign

    async def _public_get(self, path: str, params: Optional[Dict] = None):
        url = f"{self.base}{path}"
        if params:
            url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
        async with self.sess.get(url) as r:
            js = await r.json()
            if js.get("code", 0) != 0:
                raise RuntimeError(f"BingX public error: {js}")
            return js

    async def _signed_request(self, method: str, path: str, payload: Optional[Dict] = None):
        query = self._sign_query(payload or {})
        url = f"{self.base}{path}?{query}"
        headers = {"X-BX-APIKEY": self.key}
        async with self.sess.request(method, url, headers=headers) as r:
            js = await r.json()
            if js.get("code", 0) != 0:
                raise RuntimeError(f"BingX signed error: {js}")
            return js

    async def get_free_margin(self) -> float:
        raw = await self._signed_request("GET", "/openApi/swap/v2/user/balance")
        data = raw.get("data", {})
        if isinstance(data, dict) and "balance" in data:
            return float(data["balance"].get("availableMargin", 0))
        return 0.0

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

    async def fetch_positions(self):
        return await self._signed_request("GET", "/openApi/swap/v2/user/positions")

    async def close_position(self, symbol: str, side: str, quantity: float):
        position_side = "LONG" if side == "SELL" else "SHORT"
        return await self._signed_request("POST", "/openApi/swap/v2/trade/order", {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": f"{quantity:.8f}",
            "positionSide": position_side,
        })

    async def cancel_all(self, symbol: str):
        await self._signed_request("DELETE", "/openApi/swap/v2/trade/allOpenOrders", {"symbol": symbol})

    async def fetch_order(self, symbol: str, order_id: str):
        resp = await self._signed_request("GET", "/openApi/swap/v2/trade/order",
            {"symbol": symbol, "orderId": order_id})
        return resp.get("data", {})
