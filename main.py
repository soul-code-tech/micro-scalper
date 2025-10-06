#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quantum-Scalper 1-15m auto-TF
- async BingX
- Kelly 0.25×
- max-drawdown-stop 5 %
- trailing-stop 0.8×ATR (в памяти)
- quick TP1 60 % at 1.2×ATR
- trail40 remaining at 0.8×ATR
- breakeven + partial 1R
- auto timeframe 1m-15m
- log-reg signal (expectancy)
- фильтр времени 8-17 UTC
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

# ✅ Глобальный исполнитель для микроскора
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

def human_float(n: float) -> str:
    return f"{n:.5f}".rstrip("0").rstrip(".") if n > 0.01 else f"{n:.7f}"


# ---------- УПРАВЛЕНИЕ ПОЗИЦИЕЙ ----------
async def manage(ex: BingXAsync, sym: str, api_pos: dict):
    pos = POS.get(sym)
    if not pos or float(api_pos["positionAmt"]) == 0:
        return

    mark = float(api_pos["markPrice"])
    side = pos["side"]

    # --- TP1: 60% при достижении 1.4×ATR ---
    if not pos.get("tp1_done"):
        risk_dist = abs(pos["entry"] - pos["sl_orig"])
        tp1_px = pos["entry"] + risk_dist * CONFIG.TP1_MULT if side == "LONG" else pos["entry"] - risk_dist * CONFIG.TP1_MULT

        if (side == "LONG" and mark >= tp1_px) or (side == "SHORT" and mark <= tp1_px):
            qty60 = pos["qty"] * 0.6
            await ex.close_position(sym, "SELL" if side == "LONG" else "BUY", qty60)
            pos["tp1_done"] = True
            log.info("⚡ %s TP1 60%% at %s", sym, human_float(mark))

    # --- BREAKEVEN: когда цена прошла +1R ---
    if not pos.get("breakeven_done"):
        be_px = pos["entry"] + risk_dist if side == "LONG" else pos["entry"] - risk_dist
        if (side == "LONG" and mark >= be_px) or (side == "SHORT" and mark <= be_px):
            part_qty = pos["qty"] * 0.2
            await ex.close_position(sym, "SELL" if side == "LONG" else "BUY", part_qty)
            pos["breakeven_done"] = True
            pos["sl"] = pos["entry"]
            log.info("🛡️ %s breakeven @ %s", sym, human_float(pos["entry"]))

    # --- TRAILING STOP для оставшихся 40% ---
    if pos.get("tp1_done"):
        trail_dist = abs(pos["entry"] - pos["sl_orig"]) * CONFIG.TRAIL_MULT
        if side == "LONG":
            new_sl = mark - trail_dist
            if new_sl > pos["sl"]:
                pos["sl"] = new_sl
        else:
            new_sl = mark + trail_dist
            if new_sl < pos["sl"]:
                pos["sl"] = new_sl

    # --- STOP-OUT ---
    if (side == "LONG" and mark <= pos["sl"]) or (side == "SHORT" and mark >= pos["sl"]):
        await ex.close_position(sym, "SELL" if side == "LONG" else "BUY", pos["qty"])
        POS.pop(sym, None)
        OPEN_ORDERS.pop(sym, None)
        await ex.cancel_all(sym)
        log.info("🛑 %s stopped at %s", sym, human_float(mark))
        return


# ---------- ЛОГИКА ТОРГОВЛИ ----------
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

    # 🔁 Получаем лучший таймфрейм
    tf = await best_timeframe(ex, sym)
    klines = await ex.klines(sym, tf, 150)
    if not klines:
        log.info("⏭️ %s %s – klines ПУСТО", sym, tf)
        return

    # ✅ Конвертируем словари в списки
    if isinstance(klines[0], dict):
        klines = [[d["time"], d["open"], d["high"], d["low"], d["close"], d["volume"]] for d in klines]

    last = klines[-1]
    log.info("RAW %s %s  len=%d  last: %s", sym, tf, len(klines), last)
    log.info("THINK-CONTINUE %s – расчёт начат", sym)

    if float(last[2]) == float(last[3]):
        log.info("FLAT %s %s  h=l=%s", sym, tf, last[2])
        return

    # ✅ Вызываем micro_score в отдельном потоке
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

    # ✅ Фильтры
    utc_hour = datetime.now(timezone.utc).hour
    if not (CONFIG.TRADE_HOURS[0] <= utc_hour < CONFIG.TRADE_HOURS[1]):
        log.info("⏭️  %s – вне торгового окна", sym)
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

    # ✅ Расчёт размера
    sizing = calc(px, atr_pc * px, side, equity, sym)
    if sizing.size <= 0:
        log.info("⏭️  %s sizing zero", sym)
        return

    # ✅ Минимальный номинал с API
    try:
        ci = await ex.get_contract_info(sym)
        min_notional_str = ci["data"][0].get("minNotional")
        if not min_notional_str:
            raise ValueError("minNotional missing")
        min_nom = float(min_notional_str)
    except Exception as e:
        log.warning("⚠️  %s minNotional error: %s — использую fallback", sym, e)
        min_nom = CONFIG.MIN_NOTIONAL_FALLBACK

    # ✅ Для дешёвых монет — снижаем порог
    if sym in ("DOGE-USDT", "XRP-USDT", "LTC-USDT", "SUI-USDT"):
        min_nom = min(CONFIG.MIN_NOTIONAL_FALLBACK * 0.5, min_nom)

    # ✅ Максимум: 90% × leverage
    max_nominal = equity * 0.9 * CONFIG.LEVERAGE
    if min_nom > max_nominal:
        log.info("⏭️  %s min_nom (%.2f) > max_nom (%.2f) — пропуск", sym, min_nom, max_nominal)
        return

    min_nom = min(min_nom, max_nominal)

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
                log.warning("❌ Не найден orderId: %s", order_data)
                return

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
                tp1_done=False,
                breakeven_done=False,
            )
            log.info("📨 %s %s %.3f @ %s SL=%s TP=%s",
                     sym, side, sizing.size, human_float(px),
                     human_float(sizing.sl_px), human_float(sizing.tp_px))


# ---------- УРОВЕНЬ МОДУЛЯ ----------
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

    while True:
        CYCLE += 1
        
        # ✅ Защита от silent crash
        try:
            equity = await ex.balance()
        except Exception as e:
            log.error("💥 SILENT CRASH: %s\n%s", e, traceback.format_exc())
            await asyncio.sleep(5)
            continue

        if equity > PEAK_BALANCE or PEAK_BALANCE == 0:
            PEAK_BALANCE = equity

        if max_drawdown_stop(equity, PEAK_BALANCE):
            if CYCLE % 15 == 0:
                dd = (PEAK_BALANCE - equity) / PEAK_BALANCE * 100
                log.debug("⚠️  DD %.1f %% – skip cycle", dd)
            await asyncio.sleep(1)
            continue

        prev_eq = cache.get("prev_eq", 0.0)
        if abs(equity - prev_eq) > 0.01:
            log.info("💰 Equity %.2f $ (peak %.2f $)", equity, PEAK_BALANCE)
            cache.set("prev_eq", equity)

        # ✅ Каждые 10 циклов — метка жизни
        if CYCLE % 10 == 0:
            log.info("💓 ALIVE  cycle=%d  POS=%d  EQ=%.2f$", CYCLE, len(POS), equity)

        # Сводка каждые 15 циклов (~5 минут)
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
