import asyncio
import hmac
import time
import hashlib
import aiohttp
from typing import Optional, Dict, Any
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

class BingXAsync:
    def __init__(self, api_key: str, secret: str):
        self.key = api_key
        self.sec = secret
        self.base = "https://open-api.bingx.com"  # ← ИСПРАВЛЕНО: пробелы удалены
        self.sess: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self.sess = aiohttp.ClientSession(
            headers={"User-Agent": "Quantum-Scalper/1.0"}
        )
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self.sess:
            await self.sess.close()

    def _sign(self, query: str) -> str:
        return hmac.new(self.sec.encode(), query.encode(), hashlib.sha256).hexdigest()

    # ---------- ПУБЛИЧНЫЙ ЗАПРОС (без подписи) ----------
    async def _public_get(self, path: str, params: Optional[Dict] = None):
        url = f"{self.base}{path}"
        if params:
            query = "&".join([f"{k}={v}" for k, v in params.items()])
            url += f"?{query}"
        try:
            async with self.sess.get(url) as r:
                js = await r.json()
                if js.get("code", 0) != 0:
                    raise RuntimeError(f"BingX error: {js}")
                return js
        except Exception as e:
            log.error(f"Error in _public_get: {e}")
            raise

    # ---------- ПОДПИСАННЫЙ ЗАПРОС ----------
    async def _signed_request(self, method: str, path: str, payload: Optional[Dict] = None):
        ts = str(int(time.time() * 1000))
        payload = payload or {}
        payload["timestamp"] = ts
        query = "&".join([f"{k}={v}" for k, v in payload.items()])
        signature = self._sign(query)
        url = f"{self.base}{path}?{query}&signature={signature}"
        headers = {"X-BX-APIKEY": self.key}
        try:
            async with self.sess.request(method, url, headers=headers) as r:
                js = await r.json()
                if js.get("code", 0) != 0:
                    raise RuntimeError(f"BingX error: {js}")
                return js
        except Exception as e:
            log.error(f"Error in _signed_request: {e}")
            raise

    # ---------- ПУБЛИЧНЫЕ МЕТОДЫ ----------
    async def get_all_contracts(self) -> dict:
        """Получить все фьючерсные контракты (публичный эндпоинт)"""
        return await self._public_get("/openApi/swap/v3/market/contracts")

    async def klines(self, symbol: str, interval: str = "1m", limit: int = 150):
        try:
            data = await self._public_get("/openApi/swap/v3/quote/klines",
                                          {"symbol": symbol,
                                           "interval": interval,
                                           "limit": limit})
            return data["data"]
        except Exception as e:
            log.warning("❌ %s klines fail: %s", symbol, e)
            return []

    async def order_book(self, symbol: str, limit: int = 5):
        try:
            data = await self._public_get("/openApi/swap/v3/quote/depth",
                                          {"symbol": symbol, "limit": limit})
            return data["data"]
        except Exception as e:
            log.warning("❌ %s order_book fail: %s", symbol, e)
            return {"bids": [], "asks": []}

    # ---------- ПРИВАТНЫЕ МЕТОДЫ ----------
    async def balance(self):
        raw = await self._signed_request("GET", "/openApi/swap/v3/user/balance")
        # теперь всегда массив счетов
        arr = raw.get("data", [])
        if not arr:
            raise RuntimeError("balance empty")
        # первый элемент – основной фьючерсный счёт
        equity_str = arr[0].get("balance", {}).get("equity", "0")
        return float(equity_str)

    async def set_leverage(self, symbol: str, leverage: int, side: str) -> dict:
        """Установить плечо (требуется side: 'LONG' или 'SHORT')"""
        return await self._signed_request("POST", "/openApi/swap/v3/trade/leverage", {
            "symbol": symbol,
            "leverage": leverage,
            "side": side
        })

    async def place_order(self, symbol: str, side: str, order_type: str,
                          quantity: float, price: Optional[float] = None, post_only: bool = True):
        payload = {
            "symbol": symbol,
            "side": side.upper(),
            "type": order_type.upper(),
            "quantity": f"{quantity:.3f}",
            "positionSide": "BOTH",
            "timeInForce": "PO" if post_only else "GTC",
        }
        if price is not None:
            payload["price"] = f"{price:.8f}"
        return await self._signed_request("POST", "/openApi/swap/v3/trade/order", payload)

    async def place_stop_order(self, symbol: str, side: str, qty: float,
                               stop_px: float, order_type: str = "STOP_MARKET") -> dict:
        payload = {
            "symbol": symbol,
            "side": side.upper(),
            "type": order_type,
            "quantity": f"{qty:.3f}",
            "stopPrice": f"{stop_px:.8f}",
            "positionSide": "BOTH",
            "timeInForce": "GTC",
        }
        return await self._signed_request("POST", "/openApi/swap/v3/trade/order", payload)

    async def amend_stop_order(self, symbol: str, order_id: str, stop_px: float) -> dict:
        payload = {
            "symbol": symbol,
            "orderId": order_id,
            "stopPrice": f"{stop_px:.8f}",
        }
        return await self._signed_request("PUT", "/openApi/swap/v3/trade/order", payload)

    async def close_position(self, symbol: str, side: str, quantity: float):
        return await self.place_order(symbol, side, "MARKET", quantity, post_only=False)

    async def fetch_positions(self):
        return await self._signed_request("GET", "/openApi/swap/v3/user/positions")

    async def cancel_all(self, symbol: str):
        await self._signed_request("DELETE", "/openApi/swap/v3/trade/allOpenOrders", {"symbol": symbol})

    async def fetch_order(self, symbol: str, order_id: str):
        response = await self._signed_request("GET", "/openApi/swap/v3/trade/order", {
            "symbol": symbol,
            "orderId": order_id
        })
        return response.get("data", {})
