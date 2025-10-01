#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quantum-Scalper 1-min
- async BingX
- Kelly-size 0.25×
- max-drawdown-stop 5 %
- health-endpoint for UptimeRobot
"""

import os
import sys
import signal
import asyncio
import logging
from datetime import datetime

from exchange import BingXAsync
from strategy import micro_score
from risk import calc, max_drawdown_stop
from lstm_micro import predict_ensemble   # ← теперь есть
from store import cache
from health import run_web
from settings import CONFIG

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("scalper")

POS: dict[str, dict] = {}          # symbol -> {side, qty, entry, sl, tp, part, oid}
PEAK_BALANCE: float = 0.0          # высокая вода


# ---------- helpers ----------
def human_float(n: float) -> str:
    return f"{n:.5f}".rstrip("0").rstrip(".") if n > 0.01 else f"{n:.7f}"


# ---------- position management ----------
async def manage(ex: BingXAsync, sym: str, api_pos: dict):
    pos = POS.get(sym)
    if not pos:
        return
    mark = float(api_pos["markPrice"])
    side = pos["side"]

    # stop-loss
    if (side == "LONG" and mark <= pos["sl"]) or (side == "SHORT" and mark >= pos["sl"]):
        await ex.close_position(sym, "SELL" if side == "LONG" else "BUY", pos["qty"])
        POS.pop(sym)
        log.info("🛑 %s stopped at %s", sym, human_float(mark))
        return

    # partial at 1R
    risk_dist = abs(pos["entry"] - pos["sl"])
    tp_1r = pos["entry"] + risk_dist if side == "LONG" else pos["entry"] - risk_dist
    if (side == "LONG" and mark >= tp_1r) or (side == "SHORT" and mark <= tp_1r):
        await ex.close_position(sym, "SELL" if side == "LONG" else "BUY", pos["part"])
        log.info("💰 %s partial %.3f at %s", sym, pos["part"], human_float(mark))
        # move SL to breakeven
        pos["sl"] = pos["entry"]


# ---------- guard ----------
async def guard(entry: float, side: str, book: dict) -> bool:
    bid, ask = float(book["bids"][0][0]), float(book["asks"][0][0])
    spread = (ask - bid) / bid
    if spread > CONFIG.MAX_SPREAD:
        log.warning("SKIP %s – wide spread %.3f", sym, spread)
        return False
    slippage = (entry - ask) / ask if side == "LONG" else (bid - entry) / bid
    if slippage > CONFIG.MAX_SLIPPAGE:
        log.warning("SKIP %s – bad slippage %.3f", sym, slippage)
    return True


# ---------- main loop ----------
async def trade_loop(ex: BingXAsync):
    global PEAK_BALANCE
    while True:
        try:
            equity = float((await ex.balance())["data"]["balance"])
        except Exception as e:
            log.error("Balance fetch: %s", e)
            await asyncio.sleep(5)
            continue

        # init peak
        if PEAK_BALANCE == 0:
            PEAK_BALANCE = equity
        # max-drawdown stop
        if max_drawdown_stop(equity, PEAK_BALANCE):
            log.error("🛑 Max drawdown reached – trading paused")
            await asyncio.sleep(60)
            continue
        if equity > PEAK_BALANCE:
            PEAK_BALANCE = equity

        cache.set("balance", equity)

        # активные позиции BingX
        try:
            api_pos = {p["symbol"]: p for p in (await ex.fetch_positions())["data"]}
        except Exception as e:
            log.error("Positions fetch: %s", e)
            await asyncio.sleep(5)
            continue

        for sym in CONFIG.SYMBOLS:
            pos = api_pos.get(sym)
            if pos and float(pos["positionAmt"]) != 0:
                await manage(ex, sym, pos)
                continue
            if len(POS) >= CONFIG.MAX_POS:
                continue

            # данные
            try:
                klines = await ex.klines(sym, CONFIG.TIMEFRAME, 150)
                book = await ex.order_book(sym, 5)
            except Exception as e:
                log.warning("Data %s: %s", sym, e)
                continue

            score = micro_score(klines)
            atr_pc = score["atr_pc"]
            if atr_pc < CONFIG.MIN_ATR_PC:
                continue

            px = float(book["asks"][0][0]) if score["long"] > score["short"] else float(book["bids"][0][0])
            vol_usd = float(klines[-1][5]) * px
            if vol_usd < CONFIG.MIN_VOL_USD_1m:
                continue

            lstm_prob = predict_ensemble(klines)
            side = ("LONG" if lstm_prob > CONFIG.PROBA_LONG else
                    "SHORT" if lstm_prob < CONFIG.PROBA_SHORT else None)
            if not side or not await guard(px, side, book):
                continue

            sizing = calc(px, atr_pc * px, side, equity)
            if sizing.size <= 0:
                continue

            order = await ex.place_order(sym, side, "LIMIT", sizing.size, px, CONFIG.POST_ONLY)
            if order and order["code"] == 0:
                oid = order["data"]["orderId"]
                POS[sym] = dict(side=side, qty=sizing.size, entry=px,
                                sl=sizing.sl_px, tp=sizing.tp_px,
                                part=sizing.partial_qty, oid=oid)
                log.info("📨 %s %s %.3f @ %s  SL=%s  TP=%s",
                         sym, side, sizing.size, human_float(px),
                         human_float(sizing.sl_px), human_float(sizing.tp_px))

        await asyncio.sleep(1)


# ---------- graceful shutdown ----------
def shutdown(sig, frame):
    log.info("⏹️  SIGTERM/SIGINT – shutting down")
    sys.exit(0)


# ---------- entry ----------
async def main():
    # фоновый веб-сервер для UptimeRobot
    asyncio.create_task(asyncio.to_thread(run_web))

    async with BingXAsync(os.getenv("BINGX_API_KEY"), os.getenv("BINGX_SECRET_KEY")) as ex:
        await trade_loop(ex)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    asyncio.run(main())
