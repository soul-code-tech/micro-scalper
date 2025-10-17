import asyncio
import hmac
import time
import hashlib
import aiohttp
import sys
import logging
from config import CONFIG

logger = logging.getLogger()

class BingXAsync:
    def __init__(self, api_key: str, secret: str):
        self.key  = api_key
        self.sec  = secret
        self.base = CONFIG.BASE_URL
        self.sess = None

    async def __aenter__(self):
        self.sess = aiohttp.ClientSession(
            headers={"User-Agent": "BingX-VST-Grid/1.0"},
            timeout=aiohttp.ClientTimeout(total=10)
        )
        return self

    async def __aexit__(self, *_):
        if self.sess:
            await self.sess.close()

    # ---------- подпись ----------
    def _sign(self, params: dict) -> str:
        p = params.copy()
        p["timestamp"] = str(int(time.time() * 1000))
        p["recvWindow"] = "5000"
        query = "&".join(f"{k}={v}" for k, v in sorted(p.items()))
        sig   = hmac.new(self.sec.encode(), query.encode(), hashlib.sha256).hexdigest()
        return f"{query}&signature={sig}"

    async def _request(self, method: str, path: str, params: dict | None = None, signed: bool = True):
        url = f"{self.base}{path}"
        if signed:
            url += "?" + self._sign(params or {})
        async with self.sess.request(method, url, headers={"X-BX-APIKEY": self.key}) as r:
            js = await r.json()
            if js.get("code") != 0:
                raise RuntimeError(f"BingX error: {js}")
            return js["data"]

    # ---------- API ----------
    async def get_balance(self) -> float:
        raw = await self._request("GET", "/openApi/swap/v2/user/balance")
        balance_info = raw.get("balance", {})
        if isinstance(balance_info, dict) and balance_info.get("asset") == "USDT":
            return float(balance_info.get("availableMargin", 0))
        return 0.0

    async def fetch_positions(self):
        raw = await self._request("GET", "/openApi/swap/v2/user/positions")
        print(f"DEBUG fetch_positions: {type(raw)} → {raw}", file=sys.stderr, flush=True)
        if isinstance(raw, list):
            return {p["symbol"]: p for p in raw if float(p.get("positionAmt", 0)) != 0}
        return {}

    async def klines(self, symbol: str, tf: str = "15m", limit: int = 50):
        # без подписи, параметры в query-string
        url = f"{self.base}/openApi/swap/v2/quote/klines?symbol={symbol}&interval={tf}&limit={limit}"
        async with self.sess.get(url) as r:
            js = await r.json()
            if js.get("code") != 0:
                raise RuntimeError(f"BingX error: {js}")
            return js["data"]

    async def place_order(self, symbol: str, side: str, qty: float, px: float, pos_side: str):
        params = {
            "symbol": symbol,
            "side": side,
            "type": "LIMIT",
            "timeInForce": "PostOnly",
            "price": f"{px:.8f}",
            "quantity": f"{qty:.8f}",
            "positionSide": pos_side
        }
        res = await self._request("POST", "/openApi/swap/v2/trade/order", params)
        print(f"✅ ORDER {side} {qty}@{px} {symbol} {pos_side}", file=sys.stderr, flush=True)
        return res
    async def close_position(self, symbol: str, side: str, qty: float):
        params = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": f"{qty:.8f}",
            "positionSide": "LONG" if side == "SELL" else "SHORT"
        }
        return await self._request("POST", "/openApi/swap/v2/trade/order", params)

    async def cancel_all(self, symbol: str):
        await self._request("DELETE", "/openApi/swap/v2/trade/allOpenOrders", {"symbol": symbol})

    async def set_leverage(self, symbol: str, leverage: int, side: str = "LONG"):
        await self._request("POST", "/openApi/swap/v2/trade/leverage", {
            "symbol": symbol,
            "leverage": str(leverage),
            "side": side
        })
