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
import sys, warnings
warnings.filterwarnings("error", category=ImportWarning)

from exchange import BingXAsync
from strategy import micro_score
from risk import calc, max_drawdown_stop, Sizing
from store import cache
from settings import CONFIG
from tf_selector import best_timeframe
from health_aio import start_health
from orders import limit_entry, await_fill_or_cancel, limit_sl_tp   # ← должно быть

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
    risk_dist = abs(pos["entry"] - pos["sl_orig"])   # ← ОБЪЯВЛЯЕМ СРАЗУ

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
        # считаем комиссию 0,1 % (пример)
        fee = pos["qty"] * mark * 0.001
        pnl = (mark - pos["entry"]) * pos["qty"] * (1 if side == "LONG" else -1) - fee
        log.info("🛑 %s stopped at %s  qty=%.3f  fee=%.4f$  pnl=%.4f$", sym, human_float(mark), pos["qty"], fee, pnl)
        await ex.close_position(sym, "SELL" if side == "LONG" else "BUY", pos["qty"])
        POS.pop(sym, None)
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
    min_vol_dyn = equity * 0.05          # ← ОБЪЯВЛЯЕМ СРАЗУ ПОСЛЕ vol_usd
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
   # if vol_usd < CONFIG.MIN_VOL_USD:
   #     log.info("⏭️ %s low vol (stat %.0f$)", sym, CONFIG.MIN_VOL_USD)
   #     return
    if vol_usd < min_vol_dyn:
        log.info("⏭️ %s low vol (dyn %.0f$)", sym, min_vol_dyn)
        return
    if len(POS) >= CONFIG.MAX_POS:
        log.info("⏭️  %s max pos reached", sym)
        return
    if sym in POS:
        log.info("⏭️ %s already in POS – skip", sym)
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
    if sym in ("DOGE-USDT", "LTC-USDT", "SHIB-USDT", "XRP-USDT", "BNB-USDT", "SUI-USDT"):
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
            usd_risk=sizing.usd_risk,  # ← добавь
            sl_px=sizing.sl_px,
            tp_px=sizing.tp_px,
            partial_qty=new_size * CONFIG.PARTIAL_TP,
            atr=sizing.atr  # ← добавь
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
        
        # ----------  ЛИМИТНЫЙ ВХОД + OCO SL/TP  ----------
        order_data = limit_entry(sym, side, sizing.usd_risk, CONFIG.LEVERAGE,
                         sizing.sl_px, sizing.tp_px)
        if order_data is None:
            log.info("⏭ %s – пропуск сигнала (limit_entry вернул None)", sym)
            return

        # Теперь можно await-ить
        order_id, entry_px, qty_coin = order_data

        avg_px = await await_fill_or_cancel(order_id, sym, max_sec=8)
        if avg_px is None:                       # не успели за 8 с
            return

        # ставим лимитные SL и TP
        await limit_sl_tp(sym, side, qty_coin, sizing.sl_px, sizing.tp_px)

        # сохраняем позицию в память
        POS[sym] = dict(
            side=side,
            qty=qty_coin,
            entry=avg_px,
            sl=sizing.sl_px,
            sl_orig=sizing.sl_px,
            tp=sizing.tp_px,
            part=qty_coin * CONFIG.PARTIAL_TP,
            atr=sizing.atr,
            tp1_done=False,
            breakeven_done=False,
        )
        log.info("📨 %s %s %.3f @ %s SL=%s TP=%s",
                 sym, side, qty_coin, human_float(avg_px),
                 human_float(sizing.sl_px), human_float(sizing.tp_px))
        # -------------------------------------------------


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

        try:
            equity = await ex.balance()
        except Exception as e:
            log.error("💥 SILENT CRASH: %s", e)
            await asyncio.sleep(10)
            continue

        if equity > PEAK_BALANCE or PEAK_BALANCE == 0:
            PEAK_BALANCE = equity

        # --- Получаем позиции ---
        try:
            raw_pos = (await ex.fetch_positions())["data"]
            api_pos = {p["symbol"]: p for p in raw_pos}
        except Exception as e:
            log.error("❌ fetch_positions fail: %s", e)
            await asyncio.sleep(10)
            continue

        # --- Синхронизация локальных позиций ---
        for sym in list(POS.keys()):
            if sym not in api_pos or float(api_pos.get(sym, {}).get("positionAmt", 0)) == 0:
                POS.pop(sym, None)
                OPEN_ORDERS.pop(sym, None)
                await ex.cancel_all(sym)
                log.info("🧹 %s сброшена (нет на бирже)", sym)

        # --- Управление или открытие ---
        for sym in CONFIG.SYMBOLS:
            try:
                if sym in api_pos and float(api_pos[sym]["positionAmt"]) != 0:
                    await manage(ex, sym, api_pos[sym])
                else:
                    await think(ex, sym, equity)
            except Exception as e:
                log.warning("❌ %s cycle error: %s", sym, e)
            await asyncio.sleep(30)

        # 💰 Total PnL — закрыть всё при +2%
        if CYCLE % 20 == 0:
            total_pnl = 0.0
            try:
                # Мы уже получили api_pos выше!
                for sym in POS:
                    pos = POS[sym]
                    if sym not in api_pos:
                        continue
                    mark = float(api_pos[sym]["markPrice"])
                    fee = pos["qty"] * mark * 0.001
                    pnl = (mark - pos["entry"]) * pos["qty"]
                    if pos["side"] == "SHORT":
                        pnl *= -1
                    pnl -= fee
                    total_pnl += pnl
            except Exception as e:
                log.warning("⚠️  Не смог рассчитать PnL: %s", e)
                total_pnl = 0.0

            if total_pnl > equity * 0.02:
                log.info("💰 TOTAL PnL = %.2f$ > 2%% – закрываю все позиции", total_pnl)
                for s in list(POS.keys()):
                    side = "SELL" if POS[s]["side"] == "LONG" else "BUY"
                    await ex.close_position(s, side, POS[s]["qty"])
                    POS.pop(s, None)
                    await ex.cancel_all(s)
                log.info("✅ Все позиции закрыты по общему PnL")

        # 💓 ALIVE
        if CYCLE % 10 == 0:
            log.info("💓 ALIVE  cycle=%d  POS=%d  EQ=%.2f$", CYCLE, len(POS), equity)

        # 📊 Сводка
        if CYCLE % 15 == 0:
            dd = (PEAK_BALANCE - equity) / PEAK_BALANCE * 100 if PEAK_BALANCE else 0.0
            log.info("📊 EQ:%.2f $  Peak:%.2f $  DD:%.2f%%  POS:%d  ORD:%d",
                     equity, PEAK_BALANCE, dd, len(POS), len(OPEN_ORDERS))

        await asyncio.sleep(15)

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
