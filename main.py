#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quantum-Scalper 5-15m auto-TF
- async BingX
- Kelly 0.25×
- max-drawdown-stop 5 %
- trailing-stop 0.8×ATR
- breakeven + partial 1R
- auto timeframe 5m/15m (top 15m)
"""

import os
import sys
import signal
import asyncio
import logging
import time
import traceback
from datetime import datetime

from exchange import BingXAsync
from strategy import micro_score
from risk import calc, max_drawdown_stop
from store import cache
from health import run_web
from settings import CONFIG
from tf_selector import best_timeframe

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("scalper")

POS: dict[str, dict] = {}          # symbol -> {side, qty, entry, sl, tp, part, oid, atr, breakeven_done, sl_orig}
PEAK_BALANCE: float = 0.0


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

    # 1. trailing-stop 0.8×ATR (только в прибыльную сторону)
    atr_dist = pos["atr"] * 0.8
    if side == "LONG":
        new_sl = mark - atr_dist
        if new_sl > pos["sl"]:
            pos["sl"] = new_sl
            log.info("⬆️  %s trail SL → %s", sym, human_float(new_sl))
    else:  # SHORT
        new_sl = mark + atr_dist
        if new_sl < pos["sl"]:
            pos["sl"] = new_sl
            log.info("⬇️  %s trail SL → %s", sym, human_float(new_sl))

    # 2. обычный стоп-лосс
    if (side == "LONG" and mark <= pos["sl"]) or (side == "SHORT" and mark >= pos["sl"]):
        await ex.close_position(sym, "SELL" if side == "LONG" else "BUY", pos["qty"])
        POS.pop(sym)
        log.info("🛑 %s stopped at %s", sym, human_float(mark))
        return

    # 3. partial 1R + breakeven
    risk_dist = abs(pos["entry"] - pos["sl_orig"])
    tp_1r = pos["entry"] + risk_dist if side == "LONG" else pos["entry"] - risk_dist
    if (side == "LONG" and mark >= tp_1r) or (side == "SHORT" and mark <= tp_1r):
        if not pos.get("breakeven_done"):
            await ex.close_position(sym, "SELL" if side == "LONG" else "BUY", pos["part"])
            log.info("💰 %s part %.3f at %s", sym, pos["part"], human_float(mark))
            pos["sl"] = pos["entry"]                 # безубыток
            pos["breakeven_done"] = True


# ---------- guard ----------
async def guard(px: float, side: str, book: dict, sym: str) -> bool:
    bid, ask = float(book["bids"][0][0]), float(book["asks"][0][0])
    spread = (ask - bid) / bid
    if spread > CONFIG.MAX_SPREAD:
        log.info("⏭️  %s wide spread %.4f", sym, spread)
        return False
    return True


# ---------- мысли вслух ----------
async def think(ex: BingXAsync, sym: str, equity: float):
    tf = await best_timeframe(ex, sym)          # ← выбираем TF
    try:
        klines = await ex.klines(sym, tf, 150)  # ← используем его
        book   = await ex.order_book(sym, 5)
    except Exception as e:
        log.warning("❌ %s data fail: %s", sym, e)
        return

    score = micro_score(klines)
    atr_pc = score["atr_pc"]
    px = float(book["asks"][0][0]) if score["long"] > score["short"] else float(book["bids"][0][0])
    vol_usd = float(klines[-1][5]) * px
    side = ("LONG" if score["long"] > score["short"] else
            "SHORT" if score["short"] > score["long"] else None)

    log.info("🧠 %s tf=%s atr=%.4f vol=%.0f$ side=%s long=%.2f short=%.2f",
             sym, tf, atr_pc, vol_usd, side, score["long"], score["short"])

    if atr_pc < CONFIG.MIN_ATR_PC:
        log.info("⏭️  %s low atr", sym); return
    if vol_usd < CONFIG.MIN_VOL_USD:
        log.info("⏭️  %s low vol", sym); return
    if not side:
        log.info("⏭️  %s no side", sym); return
    if len(POS) >= CONFIG.MAX_POS:
        log.info("⏭️  %s max pos", sym); return
    if not await guard(px, side, book, sym):
        return

    sizing = calc(px, atr_pc * px, side, equity)
    if sizing.size <= 0:
        log.info("⏭️  %s sizing zero", sym); return

    order = await ex.place_order(sym, side, "LIMIT", sizing.size, px, CONFIG.POST_ONLY)
    if order and order.get("code") == 0:
        oid = order["data"]["orderId"]
        POS[sym] = dict(
            side=side,
            qty=sizing.size,
            entry=px,
            sl=sizing.sl_px,
            sl_orig=sizing.sl_px,
            tp=sizing.tp_px,
            part=sizing.partial_qty,
            oid=oid,
            atr=atr_pc * px,
            breakeven_done=False,
        )
        log.info("📨 %s %s %.3f @ %s SL=%s TP=%s",
                 sym, side, sizing.size, human_float(px),
                 human_float(sizing.sl_px), human_float(sizing.tp_px))


# ---------- основной цикл ----------
async def trade_loop(ex: BingXAsync):
    global PEAK_BALANCE
    while True:
        try:
            equity = float((await ex.balance())["data"]["balance"])
        except Exception as e:
            log.error("Balance fetch: %s\n%s", e, traceback.format_exc())
            await asyncio.sleep(5); continue

        if PEAK_BALANCE == 0:
            PEAK_BALANCE = equity
        if max_drawdown_stop(equity, PEAK_BALANCE):
            log.error("🛑 Max DD – pause"); await asyncio.sleep(60); continue
        if equity > PEAK_BALANCE:
            PEAK_BALANCE = equity
        cache.set("balance", equity)
        log.info("💰 Equity %.2f $ (peak %.2f $)", equity, PEAK_BALANCE)

        try:
            api_pos = {p["symbol"]: p for p in (await ex.fetch_positions())["data"]}
        except Exception as e:
            log.error("Positions fetch: %s\n%s", e, traceback.format_exc())
            await asyncio.sleep(5); continue

        for sym, p in api_pos.items():
            if float(p["positionAmt"]) != 0:
                await manage(ex, sym, p)

        for sym in CONFIG.SYMBOLS:
            if sym in api_pos:
                continue
            await think(ex, sym, equity)

        await asyncio.sleep(2)


# ---------- graceful shutdown ----------
def shutdown(sig, frame):
    log.info("⏹️  SIGTERM/SIGINT – shutdown")
    sys.exit(0)


# ---------- entry ----------
async def main():
    asyncio.create_task(asyncio.to_thread(run_web))
    async with BingXAsync(os.getenv("BINGX_API_KEY"), os.getenv("BINGX_SECRET_KEY")) as ex:
        await trade_loop(ex)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    asyncio.run(main())
