import asyncio
import json
import os
import sys
from core.exchange import BingXAsync
from config import CONFIG

STATE_FILE = "state.json"

def load_state() -> dict:
    return json.load(open(STATE_FILE)) if os.path.exists(STATE_FILE) else {}

def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

class GridManager:
    def __init__(self, symbol: str, center: float, equity: float):
        self.symbol = symbol
        self.center = center
        self.equity = equity

    # ---------- deploy сетки (с красивыми логами) ----------
    async def deploy(self, ex: BingXAsync):
        await ex.cancel_all(self.symbol)
        info      = await ex.get_contract_info(self.symbol)
        min_qty   = float(info["minQty"])
        step_size = float(info["stepSize"])
        price_prec = int(info["pricePrecision"])

        range_abs = self.center * CONFIG.GRID_RANGE_PCT
        step      = (2 * range_abs) / CONFIG.GRID_LEVELS
        qty_raw   = (self.equity * CONFIG.RISK_PER_GRID) / (CONFIG.GRID_LEVELS * self.center)
        qty       = max(min_qty, round(qty_raw / step_size) * step_size)
        if qty * self.center < 0.5:
            return False

        state = load_state()
        state[self.symbol] = {"orders": []}

        for i in range(CONFIG.GRID_LEVELS):
            px_buy  = round(self.center - range_abs + i * step, price_prec)
            px_sell = round(px_buy + step * 0.8, price_prec)

            # --- красивые логи ---
            log_buy(qty, px_buy, self.symbol)
            log_sell(qty, px_sell, self.symbol)

            await ex.place_order(self.symbol, "BUY",  qty, px_buy,  "LONG")
            await ex.place_order(self.symbol, "SELL", qty, px_sell, "SHORT")
            state[self.symbol]["orders"].append({"buy": px_buy, "sell": px_sell})

        save_state(state)
        print(f"✅  СЕТКА {self.symbol}  центр {self.center:.2f}", flush=True)
        return True

    # ---------- обновление / emergency ----------
    async def update(self, ex: BingXAsync):
        positions = await ex.fetch_positions()
        if self.symbol not in positions:                       # нет позиции – выходим
            return
        mark = float(positions[self.symbol]["markPrice"])
        if mark < self.center * (1 - CONFIG.GRID_RANGE_PCT * 1.2) or mark > self.center * (1 + CONFIG.GRID_RANGE_PCT * 1.2):
            await self.emergency_close(ex)

    async def emergency_close(self, ex: BingXAsync):
        print(f"🚨 EMERGENCY CLOSE {self.symbol}", flush=True)
        await ex.cancel_all(self.symbol)
        pos = await ex.fetch_positions()
        if self.symbol in pos and float(pos[self.symbol]["positionAmt"]) != 0:
            side = "SELL" if float(pos[self.symbol]["positionAmt"]) > 0 else "BUY"
            qty  = abs(float(pos[self.symbol]["positionAmt"]))
            await ex.close_position(self.symbol, side, qty)
