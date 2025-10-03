#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quantum-Scalper 1-15m auto-TF
- async BingX
- Kelly 0.25×
- max-drawdown-stop 5 %
- trailing-stop 0.8×ATR
- quick TP1 60 % at 1.2×ATR  ← исправлено
- trail40 remaining at 0.8×ATR
- breakeven + partial 1R
- auto timeframe 1m-15m
- log-reg signal (expectancy)
- фильтр времени 8-17 UTC
- фильтр новостей ±5 мин
- скачивание весов при старте
- контроль висящих ордеров
"""

import os
import sys
import signal
import asyncio
import logging
import time
import traceback
import aiohttp
from datetime import datetime, timezone

from exchange import BingXAsync
from strategy import micro_score
from risk import calc, max_drawdown_stop
from store import cache
from settings import CONFIG
from tf_selector import best_timeframe
from news_filter import is_news_time
from health_aio import start_health

print("=== DEBUG: импорты завершены ===")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    datefmt="%H:%M",
)
log = logging.getLogger("scalper")

POS: dict[str, dict] = {}
OPEN_ORDERS: dict[str, str] = {}   # symbol -> orderId
PEAK_BALANCE: float = 0.0

def human_float(n: float) -> str:
    return f"{n:.5f}".rstrip("0").rstrip(".") if n > 0.01 else f"{n:.7f}"


# ---------- position management ----------
async def manage(ex: BingXAsync, sym: str, api_pos: dict):
    pos = POS.get(sym)
    if not pos:
        return
    mark = float(api_pos["markPrice"])
    side = pos["side"]

    atr_dist = pos["atr"] * CONFIG.ATR_MULT_SL
    if side == "LONG":
        new_sl = mark - atr_dist
        if new_sl > pos["sl"]:
            pos["sl"] = new_sl
            log.info("⬆️  %s trail SL → %s", sym, human_float(new_sl))
    else:
        new_sl = mark + atr_dist
        if new_sl < pos["sl"]:
            pos["sl"] = new_sl
            log.info("⬇️  %s trail SL → %s", sym, human_float(new_sl))

    risk_dist = abs(pos["entry"] - pos["sl_orig"])
    tp1_dist = risk_dist * CONFIG.TP1_MULT
    tp1_px = pos["entry"] + tp1_dist if side == "LONG" else pos["entry"] - tp1_dist

    if (side == "LONG" and mark >= tp1_px) or (side == "SHORT" and mark <= tp1_px):
        if not pos.get("tp1_done"):
            qty60 = pos["qty"] * 0.6
            await ex.close_position(sym, "SELL" if side == "LONG" else "BUY", qty60)
            OPEN_ORDERS.pop(sym, None)
            await ex.cancel_all(sym)
            log.info("⚡ %s TP1 60%% at %s", sym, human_float(mark))
            pos["tp1_done"] = True

    if pos.get("tp1_done"):
        trail_dist = risk_dist * CONFIG.TRAIL_MULT
        if side == "LONG":
            new_sl40 = mark - trail_dist
            if new_sl40 > pos["sl"]:
                pos["sl"] = new_sl40
                log.info("⬆️  %s trail40 → %s", sym, human_float(new_sl40))
        else:
            new_sl40 = mark + trail_dist
            if new_sl40 < pos["sl"]:
                pos["sl"] = new_sl40
                log.info("⬇️  %s trail40 → %s", sym, human_float(new_sl40))

    if (side == "LONG" and mark <= pos["sl"]) or (side == "SHORT" and mark >= pos["sl"]):
        await ex.close_position(sym, "SELL" if side == "LONG" else "BUY", pos["qty"])
        POS.pop(sym)
        OPEN_ORDERS.pop(sym, None)
        await ex.cancel_all(sym)
        log.info("🛑 %s stopped at %s", sym, human_float(mark))
        return

    risk_dist = abs(pos["entry"] - pos["sl_orig"])
    tp_1r = pos["entry"] + risk_dist if side == "LONG" else pos["entry"] - risk_dist
    if (side == "LONG" and mark >= tp_1r) or (side == "SHORT" and mark <= tp_1r):
        if not pos.get("breakeven_done"):
            await ex.close_position(sym, "SELL" if side == "LONG" else "BUY", pos["part"])
            log.info("💰 %s part %.3f at %s", sym, pos["part"], human_float(mark))
            pos["sl"] = pos["entry"]
            pos["breakeven_done"] = True


async def guard(px: float, side: str, book: dict, sym: str) -> bool:
    bid, ask = float(book["bids"][0][0]), float(book["asks"][0][0])
    spread = (ask - bid) / bid
    if spread > CONFIG.MAX_SPREAD:
        log.info("⏭️  %s wide spread %.4f", sym, spread)
        return False
    return True


async def think(ex: BingXAsync, sym: str, equity: float):
    # --- контроль висящих ордеров ---
    if OPEN_ORDERS.get(sym):
        try:
            oo = await ex.fetch_order(sym, OPEN_ORDERS[sym])
            status = oo.get("data", {}).get("status", "")
            if status == "FILLED":
                OPEN_ORDERS.pop(sym, None)
            else:
                log.info("🧠 %s tf=%s atr=%.4f vol=%.0f$ side=%s long=%.2f short=%.2f",
                         sym, tf, atr_pc, vol_usd, side, score["long"], score["short"])
                return
        except Exception as e:
            log.warning("❌ не смог проверить ордер %s: %s", sym, e)
            return

    tf = await best_timeframe(ex, sym)
    try:
        klines = await ex.klines(sym, tf, 150)
        # BingX присылает поля open/close/high/low/volume/time
        # Переименуем в t,o,h,l,c,v
        klines = [
            [bar["time"], bar["open"], bar["high"], bar["low"], bar["close"], bar["volume"]]
            for bar in klines
        ]
        #log.info("RAW klines %s %s: %s", sym, tf, klines)
        book = await ex.order_book(sym, 5)
    except Exception as e:
        log.warning("❌ %s data fail: %s", sym, e)
        return

    score = micro_score(klines)
    atr_pc = score["atr_pc"]
    px = float(book["asks"][0][0]) if score["long"] > score["short"] else float(book["bids"][0][0])
    # защита от пустых/кривых свечей
    if not klines or not isinstance(klines[-1], (list, tuple)) or len(klines[-1]) < 6:
        log.warning("⏭️ %s – klines пустые или не хватает полей", sym)
        return
    vol_usd = float(klines[-1][5]) * px
    side = ("LONG" if score["long"] > score["short"] else
            "SHORT" if score["short"] > score["long"] else None)

    log.info("🧠 %s tf=%s atr=%.4f vol=%.0f$ side=%s long=%.2f short=%.2f",
             sym, tf, atr_pc, vol_usd, side, score["long"], score["short"])

    # --- фильтр времени ---
    utc_hour = datetime.now(timezone.utc).hour
    if not (CONFIG.TRADE_HOURS[0] <= utc_hour < CONFIG.TRADE_HOURS[1]):
        log.info("⏭️  %s – вне торгового окна", sym)
        return

    # --- фильтр новостей ---
    if await is_news_time(5):
        log.info("⏭️  %s – высокий импакт новостей", sym)
        return

    if atr_pc < CONFIG.MIN_ATR_PC:
        log.info("⏭️  %s low atr", sym)
        return
    if vol_usd < CONFIG.MIN_VOL_USD:
        log.info("⏭️  %s low vol", sym)
        return
    if not side:
        log.info("⏭️  %s no side", sym)
        return
    if len(POS) >= CONFIG.MAX_POS:
        log.info("⏭️  %s max pos reached", sym)
        return
    if not await guard(px, side, book, sym):
        return

    sizing = calc(px, atr_pc * px, side, equity, sym)
    if sizing.size <= 0:
        log.info("⏭️  %s sizing zero", sym)
        return

    # --- ставим плечо 50× (один раз) ---
    if sym not in POS and sym not in OPEN_ORDERS:
        try:
            await ex.set_leverage(sym, 50)
        except RuntimeError as e:
            if "leverage already set" not in str(e):
                log.warning("⚠️  set_leverage %s: %s", sym, e)

    # --- динамический минимальный номинал ---
    try:
        ci = await ex.get_contract_info(sym)
        min_qty = float(ci["data"]["minOrderQty"])
        min_nom = min_qty * px
    except Exception as e:
        log.warning("❌ minOrderQty %s: %s", sym, e)
        return

    if sizing.size * px < min_nom:
        log.info("⏭️  %s nominal %.2f < %.2f – пропуск", sym, sizing.size * px, min_nom)
        return

    bingx_side = "BUY" if side == "LONG" else "SELL"
    order = await ex.place_order(sym, bingx_side, "LIMIT", sizing.size, px, CONFIG.POST_ONLY)
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


async def download_weights_once():
    repo = os.getenv("GITHUB_REPOSITORY", "your-login/your-repo")
    for sym in CONFIG.SYMBOLS:
        for tf in CONFIG.TIME_FRAMES:
            fname = f"{sym.replace('-', '')}_{tf}.pkl"
            local = f"weights/{fname}"
            if os.path.exists(local):
                continue
            url = f"https://raw.githubusercontent.com/{repo}/weights/{fname}"
            os.makedirs("weights", exist_ok=True)
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.get(url) as r:
                        r.raise_for_status()
                        with open(local, "wb") as f:
                            f.write(await r.read())
                print(f"✅ Скачан {local}")
            except Exception as e:
                print(f"⚠️  Нет весов {local}, используем дефолт")


async def trade_loop(ex: BingXAsync):
    global PEAK_BALANCE
    await download_weights_once()
    while True:
        try:
            raw_bal = await ex.balance()
            log.info("RAW balance response: %s", raw_bal)   # ← новая строка
            data = raw_bal["data"]
            if isinstance(data, dict) and "balance" in data:
                if isinstance(data["balance"], dict):
                    equity = float(data["balance"]["equity"])   # реальная эквити
                else:
                    equity = float(data["balance"])
            else:
                equity = float(data)
        except Exception as e:
            log.error("Balance fetch: %s\n%s", e, traceback.format_exc())
            await asyncio.sleep(5)
            continue

        if PEAK_BALANCE == 0:
            PEAK_BALANCE = equity
        if max_drawdown_stop(equity, PEAK_BALANCE):
            log.error("🛑 Max DD – pause")
            await asyncio.sleep(60)
            continue
        if equity > PEAK_BALANCE:
            PEAK_BALANCE = equity
        cache.set("balance", equity)
        log.info("💰 Equity %.2f $ (peak %.2f $)", equity, PEAK_BALANCE)

        try:
            api_pos = {p["symbol"]: p for p in (await ex.fetch_positions())["data"]}
        except Exception as e:
            log.error("Positions fetch: %s\n%s", e, traceback.format_exc())
            await asyncio.sleep(5)
            continue

        for sym, p in api_pos.items():
            if float(p["positionAmt"]) != 0:
                await manage(ex, sym, p)

        for sym in CONFIG.SYMBOLS:
            if sym in api_pos:
                continue
            await think(ex, sym, equity)

        await asyncio.sleep(2)


def shutdown(sig, frame):
    log.info("⏹️  SIGTERM/SIGINT – shutting down")
    sys.exit(0)


async def main():
    asyncio.create_task(start_health())
    async with BingXAsync(os.getenv("BINGX_API_KEY"), os.getenv("BINGX_SECRET_KEY")) as ex:
        await trade_loop(ex)


if __name__ == "__main__":
    try:
        print("=== DEBUG: запускаем main() ===")
        asyncio.run(main())
    except Exception as e:
        print("CRASH in main():", e, file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
