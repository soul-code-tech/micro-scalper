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
                     
    async def get_free_margin(self) -> float:
    """Returns USDT amount available for **new** positions (cross-margin)."""
    acc = await self._signed_request("GET", "/openApi/swap/v2/user/balance")
    data = acc.get("data", [])

    # ---------- защита от пустого ответа ----------
    if not data:
        log.warning("[get_free_margin] data пусто: %s", acc)
        return 0.0

    # ---------- если data — список словарей ----------
    if isinstance(data, list):
        for b in data:
            if isinstance(b, dict) and b.get("asset") == "USDT":
                return float(b.get("availableBalance", 0))
        log.warning("[get_free_margin] USDT не найдено в списке: %s", data)
        return 0.0

    # ---------- если data — dict (один актив) ----------
    if isinstance(data, dict) and data.get("asset") == "USDT":
        return float(data.get("availableBalance", 0))

    log.error("[get_free_margin] Неизвестная структура data: %s", data)
    return 0.0
    
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
        # публичный энд-поинт требует дефис
        public_sym = symbol
        try:
            data = await self._public_get("/openApi/swap/v2/quote/klines",
                                      {"symbol": public_sym, "interval": interval, "limit": limit})
            return data["data"]
        except Exception as e:
            log.warning("❌ %s klines fail: %s", symbol, e)
            return []

    async def order_book(self, symbol: str, limit: int = 5):
        # ✅ ВАЛИДАЦИЯ limit — только разрешённые значения
        VALID_LIMITS = {5, 10, 20, 50, 100, 500, 1000}
        if limit not in VALID_LIMITS:
            log.warning("⚠️  Invalid order_book limit=%d for %s — using 5", limit, symbol)
            limit = 5

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

        # ищем именно «USDT»
        for entry in data:
            if entry.get("asset") == "USDT":
                equity_str = entry.get("equity", "0")
                try:
                    return float(equity_str)
                except ValueError as e:
                    raise RuntimeError(f"Cannot parse equity '{equity_str}': {e}")

        # fallback – первый актив
        equity_str = data[0].get("equity", "0")
        try:
            return float(equity_str)
        except ValueError as e:
            raise RuntimeError(f"Cannot parse equity '{equity_str}': {e}")
    async def set_leverage(self, symbol: str, leverage: int, side: str) -> dict:
        return await self._signed_request("POST", "/openApi/swap/v2/trade/leverage",
                                          {"symbol": symbol, "leverage": leverage, "side": side})

    
    async def place_order(self, symbol: str, position_side: str, order_type: str,
                          quantity: float, price: Optional[float] = None,
                          post_only: bool = False):
        order_side = "BUY" if position_side == "LONG" else "SELL"
        time_in_force = "PostOnly" if post_only else "GTC"

        payload = {
            "symbol": symbol,
            "side": order_side,
            "type": order_type.upper(),
            "quantity": f"{quantity:.3f}",
            "price": f"{price:.8f}" if price is not None else None,
            "timeInForce": time_in_force,
            "positionSide": position_side,
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        return await self._signed_request("POST", "/openApi/swap/v2/trade/order", payload)
                              
    async def close_position(self, symbol: str, side: str, quantity: float):
        """
        side = "SELL" или "BUY" — направление рыночного ордера
        BingX требует positionSide: LONG / SHORT
        """
        position_side = "LONG" if side == "SELL" else "SHORT"
        return await self.place_order(symbol, position_side, "MARKET", quantity)

    async def fetch_positions(self):
        return await self._signed_request("GET", "/openApi/swap/v2/user/positions")
    
    async def get_contract_info(self, symbol: str) -> dict:
        """Минимальные шаги и лоты контракта (публично)"""
        return await self._public_get("/openApi/swap/v2/quote/contracts",
                                      {"symbol": symbol})

    async def cancel_all(self, symbol: str):
        await self._signed_request("DELETE", "/openApi/swap/v2/trade/allOpenOrders", {"symbol": symbol})

    async def fetch_order(self, symbol: str, order_id: str):
        resp = await self._signed_request("GET", "/openApi/swap/v2/trade/order", {
            "symbol": symbol,
            "orderId": order_id
        })
        return resp.get("data", {})
