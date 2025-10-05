#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quantum-Scalper 1-15m auto-TF
- async BingX
- Kelly 0.25×
- max-drawdown-stop 5 %
- trailing-stop 0.8×ATR
- quick TP1 60 % at 1.2×ATR
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
import asyncio
import logging
import traceback
import aiohttp
import subprocess
from datetime import datetime, timezone
from datetime import datetime as dt
import concurrent.futures

from exchange import BingXAsync
from strategy import micro_score
from risk import calc, max_drawdown_stop, Sizing
from store import cache
from settings import CONFIG
from tf_selector import best_timeframe
from health_aio import start_health

print("=== DEBUG: импорты завершены ===")
COL = {
    "GRN": "\33[32m", "RED": "\33[31m", "YEL": "\33[33m",
    "BLU": "\33[34m", "MAG": "\33[35m", "RST": "\33[0m"
}
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)

class ColouredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        t = dt.fromtimestamp(record.created, tz=timezone.utc).strftime("%H:%M")
        lvl_col = {"INFO": COL["GRN"], "WARNING": COL["YEL"],
                   "ERROR": COL["RED"]}.get(record.levelname, "")
        msg = record.getMessage()
        return f"{COL['BLU']}{t}{COL['RST']} {lvl_col}{record.levelname:>4}{COL['RST']} {msg}"

console = logging.StreamHandler(sys.stdout)
console.setFormatter(ColouredFormatter())
logging.basicConfig(level=logging.INFO, handlers=[console], force=True)

log = logging.getLogger("scalper")

POS: dict[str, dict] = {}
OPEN_ORDERS: dict[str, str] = {}   # symbol -> orderId
PEAK_BALANCE: float = 0.0
CYCLE: int = 0

# ✅ Глобальный исполнитель для тяжёлых функций
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

def human_float(n: float) -> str:
    return f"{n:.5f}".rstrip("0").rstrip(".") if n > 0.01 else f"{n:.7f}"


# ---------- управление позицией ----------
async def manage(ex: BingXAsync, sym: str, api_pos: dict):
    pos = POS.get(sym)
    if not pos:
        return

    # ✅ Защита: если нет SL/TP — закрываем позицию
    if not pos.get("sl_order_id") and not pos.get("tp_order_id"):
        log.warning("⚠️  %s позиция без SL/TP — закрываю принудительно", sym)
        await ex.close_position(sym, "SELL" if pos["side"] == "LONG" else "BUY", pos["qty"])
        POS.pop(sym, None)
        OPEN_ORDERS.pop(sym, None)
        await ex.cancel_all(sym)
        log.info("🛑 %s закрыта принудительно (нет SL/TP)", sym)
        return

    mark = float(api_pos["markPrice"])
    side = pos["side"]

    atr_dist = pos["atr"] * CONFIG.ATR_MULT_SL
    if side == "LONG":
        new_sl = max(pos["sl"], mark - atr_dist)
    else:
        new_sl = min(pos["sl"], mark + atr_dist)

    if new_sl != pos["sl"]:
        pos["sl"] = new_sl
        log.info("⬆️" if side == "LONG" else "⬇️", "%s trail SL → %s", sym, human_float(new_sl))
        if pos.get("sl_order_id"):
            try:
                await ex.amend_stop_order(sym, pos["sl_order_id"], new_sl)
                log.info("🔒 %s amend SL on exchange", sym)
            except Exception as e:
                log.debug("❌ amend SL %s: %s", sym, e)

    # TP1 60 % at 1.2×ATR
    if not pos.get("tp1_done"):
        risk_dist = abs(pos["entry"] - pos["sl_orig"])
        tp1_px = pos["entry"] + risk_dist * CONFIG.TP1_MULT if side == "LONG" else pos["entry"] - risk_dist * CONFIG.TP1_MULT
        if (side == "LONG" and mark >= tp1_px) or (side == "SHORT" and mark <= tp1_px):
            qty60 = pos["qty"] * 0.6
            await ex.close_position(sym, "SELL" if side == "LONG" else "BUY", qty60)
            pos["tp1_done"] = True
            log.info("⚡ %s TP1 60%% at %s", sym, human_float(mark))

    # trail40
    if pos.get("tp1_done"):
        trail_dist = abs(pos["entry"] - pos["sl_orig"]) * CONFIG.TRAIL_MULT
        if side == "LONG":
            new_sl40 = mark - trail_dist
            if new_sl40 > pos["sl"]:
                pos["sl"] = new_sl40
        else:
            new_sl40 = mark + trail_dist
            if new_sl40 < pos["sl"]:
                pos["sl"] = new_sl40

    # breakeven
    if not pos.get("breakeven_done"):
        risk_dist = abs(pos["entry"] - pos["sl_orig"])
        be_px = pos["entry"] + risk_dist if side == "LONG" else pos["entry"] - risk_dist
        if (side == "LONG" and mark >= be_px) or (side == "SHORT" and mark <= be_px):
            part_qty = pos["qty"] * 0.2
            await ex.close_position(sym, "SELL" if side == "LONG" else "BUY", part_qty)
            pos["breakeven_done"] = True
            pos["sl"] = pos["entry"]
            log.info("🛡️ %s breakeven @ %s", sym, human_float(pos["entry"]))

    # stop-out
    if (side == "LONG" and mark <= pos["sl"]) or (side == "SHORT" and mark >= pos["sl"]):
        await ex.close_position(sym, "SELL" if side == "LONG" else "BUY", pos["qty"])
        POS.pop(sym, None)
        OPEN_ORDERS.pop(sym, None)
        await ex.cancel_all(sym)
        log.info("🛑 %s stopped at %s", sym, human_float(mark))
        return


# ---------- проверка спреда ----------
async def guard(px: float, side: str, book: dict, sym: str) -> bool:
    bids = book.get("bids", [])
    asks = book.get("asks", [])

    if not bids or not asks:
        log.info("⏭️  %s empty order book — skipping spread check", sym)
        return True

    bid, ask = float(bids[0][0]), float(asks[0][0])
    spread = (ask - bid) / bid
    if spread > CONFIG.MAX_SPREAD:
        log.info("⏭️  %s wide spread %.4f", sym, spread)
        return False
    return True


# ---------- логика торговли ----------
async def think(ex: BingXAsync, sym: str, equity: float):
    if OPEN_ORDERS.get(sym):
        try:
            oo = await ex.fetch_order(sym, OPEN_ORDERS[sym])
            status = oo.get("data", {}).get("status", "")
            if status == "FILLED":
                OPEN_ORDERS.pop(sym, None)
            else:
                return
        except Exception as e:
            log.warning("❌ не смог проверить ордер %s: %s", sym, e)
            return

    tf = await best_timeframe(ex, sym)
    klines = await ex.klines(sym, tf, 150)

    if not klines:
        log.info("⏭️ %s %s – klines ПУСТО", sym, tf)
        return

    # ✅ Преобразуем словари в списки
    if isinstance(klines[0], dict):
        klines = [
            [d["time"], d["open"], d["high"], d["low"], d["close"], d["volume"]]
            for d in klines
        ]

    last = klines[-1]
    log.info("RAW %s %s  len=%d  last: %s", sym, tf, len(klines), last)
    log.info("THINK-CONTINUE %s – расчёт начат", sym)

    if float(last[2]) == float(last[3]):
        log.info("FLAT %s %s  h=l=%s", sym, tf, last[2])
        return

    # ✅ Получаем стакан
    book = await ex.order_book(sym, 5)
    log.info("✅ ORDER BOOK FETCHED %s", sym)

    # ✅ Вызываем микроскор в отдельном потоке
    log.info("⏳ CALLING micro_score() for %s", sym)
    score = await asyncio.get_event_loop().run_in_executor(
        _executor,
        micro_score,
        klines, sym, tf
    )
    log.info("✅ micro_score() DONE for %s", sym)

    atr_pc = score["atr_pc"]
    px = float(klines[-1][4])
    vol_usd = float(klines[-1][5]) * px
    side = ("LONG" if score["long"] > score["short"] else
            "SHORT" if score["short"] > score["long"] else None)

    log.info("🧠 %s tf=%s atr=%.4f vol=%.0f$ side=%s long=%.2f short=%.2f",
             sym, tf, atr_pc, vol_usd, side, score["long"], score["short"])

    # ✅ Проверяем спред после определения side
    if not await guard(px, side, book, sym):
        return

    # ---------- Фильтры ----------
    utc_hour = datetime.now(timezone.utc).hour
    if not (CONFIG.TRADE_HOURS[0] <= utc_hour < CONFIG.TRADE_HOURS[1]):
        log.info("⏭️  %s – вне торгового окна", sym)
        return

    if atr_pc > 0 and atr_pc < CONFIG.MIN_ATR_PC:
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

    # ✅ Расчёт размера
    sizing = calc(px, atr_pc * px, side, equity, sym)
    if sizing.size <= 0:
        log.info("⏭️  %s sizing zero", sym)
        return

    # ✅ Минимальный номинал с биржи
    try:
        ci = await ex.get_contract_info(sym)
        min_notional_str = ci["data"][0].get("minNotional")
        if min_notional_str is None:
            raise ValueError("minNotional not found")
        min_nom = float(min_notional_str)
    except Exception as e:
        log.warning("⚠️  %s minNotional error: %s — использую fallback", sym, e)
        min_nom = CONFIG.MIN_NOTIONAL_FALLBACK

    # ✅ Максимум 95% баланса × плечо
    max_margin_usd = equity * 0.10
    max_nom = max_margin_usd * CONFIG.LEVERAGE
    min_nom = min(min_nom, max_nom)

    # ✅ Подтягиваем размер до минимума
    if sizing.size * px < min_nom:
        new_size = min_nom / px
        log.info("⚠️  %s nominal %.2f < %.2f USD — увеличиваю до %.6f (%.2f USD)",
                 sym, sizing.size * px, min_nom, new_size, min_nom)
        sizing = Sizing(
            size=new_size,
            sl_px=sizing.sl_px,
            tp_px=sizing.tp_px,
            partial_qty=new_size * CONFIG.PARTIAL_TP
        )

    # ✅ FLOW-OK — все условия пройдены
    log.info("FLOW-OK %s  px=%s sizing=%s book_depth_ask=- book_depth_bid=-",
             sym, human_float(px), sizing.size)

    if sym not in POS and sym not in OPEN_ORDERS:
        try:
            await ex.set_leverage(sym, CONFIG.LEVERAGE, "LONG" if side == "LONG" else "SHORT")
        except RuntimeError as e:
            if "leverage already set" not in str(e):
                log.warning("⚠️  set_leverage %s: %s", sym, e)

        position_side = "LONG" if side == "LONG" else "SHORT"
        order = await ex.place_order(sym, position_side, "LIMIT", sizing.size, px, "GTC")
        if not order:
            log.warning("❌ place_order вернул None для %s", sym)
            return

        log.info("PLACE-RESP %s %s", sym, order)

        if order.get("code") == 0:
            order_data = order["data"].get("order")
            if not order_data:
                log.warning("❌ Нет данных 'order' в ответе: %s", order)
                return
            oid = order_data.get("orderId")
            if not oid:
                log.warning("❌ Не найден orderId в ответе: %s", order_data)
                
        else:
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

            sl_side = "SELL" if side == "LONG" else "BUY"
            tp_side = "SELL" if side == "LONG" else "BUY"

            try:
                sl_order = await ex.place_stop_order(sym, sl_side, sizing.size, sizing.sl_px, "STOP_MARKET")
                tp_order = await ex.place_stop_order(sym, tp_side, sizing.size, sizing.tp_px, "TAKE_PROFIT_MARKET")

                # ✅ Проверка SL
                if sl_order and sl_order.get("code") == 0:
                    sl_oid = sl_order["data"]["orderId"]
                    POS[sym]["sl_order_id"] = sl_oid
                    log.info("✅ %s SL=%s выставлен (ID: %s)", sym, human_float(sizing.sl_px), sl_oid)
                else:
                    log.warning("⚠️  %s не смог выставить SL: %s", sym, sl_order)

                # ✅ Проверка TP
                if tp_order and tp_order.get("code") == 0:
                    tp_oid = tp_order["data"]["orderId"]
                    POS[sym]["tp_order_id"] = tp_oid
                    log.info("✅ %s TP=%s выставлен (ID: %s)", sym, human_float(sizing.tp_px), tp_oid)
                else:
                    log.warning("⚠️  %s не смог выставить TP: %s", sym, tp_order)

                # ✅ Лог успеха
                if sl_order and sl_order.get("code") == 0 and tp_order and tp_order.get("code") == 0:
                    log.info("🔒 %s SL=%s TP=%s (ордера на бирже)", sym, human_float(sizing.sl_px), human_float(sizing.tp_px))
                else:
                    log.warning("⚠️  %s ордера SL/TP не выставлены полностью — позиция рискованна!", sym)

            except Exception as e:
                log.warning("❌ не смог выставить SL/TP %s: %s", sym, e)


# ---------- уровень модуля ----------
async def download_weights_once():
    repo = os.getenv("GITHUB_REPOSITORY", "soul-code-tech/micro-scalper")
    os.makedirs("weights", exist_ok=True)
    subprocess.run([
        "git", "clone", "--branch", "weights", "--single-branch",
        f"https://github.com/{repo}.git", "weights_tmp"
    ], check=False)
    subprocess.run("cp -r weights_tmp/*.pkl weights/ 2>/dev/null || true", shell=True)
    subprocess.run("rm -rf weights_tmp", shell=True)
    print("✅ Веса подтянуты из ветки weights")


async def trade_loop(ex: BingXAsync):
    global PEAK_BALANCE, CYCLE
    await download_weights_once()

    if not any(os.path.isfile(f"weights/{s.replace('-','')}_{tf}.pkl")
               for s in CONFIG.SYMBOLS for tf in CONFIG.TIME_FRAMES):
        log.warning("⚠️  Ни одной модели не найдено – будем использовать fallback-правила")

    while True:
        CYCLE += 1
        try:
            equity = await ex.balance()
        except Exception as e:
            log.error("Balance fetch: %s\n%s", e, traceback.format_exc())
            await asyncio.sleep(5)
            continue

        # Обновляем пиковый баланс
        if equity > PEAK_BALANCE or PEAK_BALANCE == 0:
            PEAK_BALANCE = equity

        # Max drawdown stop
        if max_drawdown_stop(equity, PEAK_BALANCE):
            if CYCLE % 15 == 0:
                dd = (PEAK_BALANCE - equity) / PEAK_BALANCE * 100
                log.debug("⚠️  DD %.1f %% – skip cycle", dd)
            await asyncio.sleep(1)
            continue

        # Обновляем текущий баланс
        prev_eq = cache.get("prev_eq", 0.0)
        if abs(equity - prev_eq) > 0.01:
            log.info("💰 Equity %.2f $ (peak %.2f $)", equity, PEAK_BALANCE)
            cache.set("prev_eq", equity)

        # Сводка каждые 15 циклов
        if CYCLE % 15 == 0:
            dd = (PEAK_BALANCE - equity) / PEAK_BALANCE * 100 if PEAK_BALANCE else 0.0
            log.info("📊 EQ:%.2f $  Peak:%.2f $  DD:%.2f%%  POS:%d  ORD:%d",
                     equity, PEAK_BALANCE, dd, len(POS), len(OPEN_ORDERS))

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

        await asyncio.sleep(20)


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
