import os
import sys
import asyncio
import logging
import time
from datetime import datetime, timezone
import concurrent.futures
from typing import Dict, List

# Импортируем необходимые модули
from exchange import BingXAsync
from settings import CONFIG, validate_env
from orders import load_min_lot_cache, limit_entry, await_fill_or_cancel, limit_sl_tp
from strategy import micro_score
from risk import calc, max_drawdown_stop, Sizing
from tf_selector import best_timeframe
from health_aio import start_health


# ---------- общий пул потоков ----------
EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=2)
# Инициализация глобальных переменных
POS: Dict[str, Dict] = {}
OPEN_ORDERS: Dict[str, str] = {}
PEAK_BALANCE: float = 0.0
CYCLE: int = 0
_MIN_LOT_CACHE: Dict[str, Dict] = {}  # Инициализируем глобальную переменную

# Настройка логгера
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("scalper.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger("scalper")
log = logging.getLogger("scalper")

# ---------- СКАЧИВАНИЕ ВЕСОВ из папки weights ветки weights ----------
import os, requests

BASE_RAW = "https://raw.githubusercontent.com/soul-code-tech/micro-scalper/weights/weights"
LOCAL_DIR = os.path.join(os.path.dirname(__file__), "weights")
os.makedirs(LOCAL_DIR, exist_ok=True)

FILES = [
    "DOGEUSDT_5m.pkl", "LTCUSDT_5m.pkl", "SUIUSDT_5m.pkl",
    "SHIBUSDT_5m.pkl", "BNBUSDT_5m.pkl", "XRPUSDT_5m.pkl",
]

for fname in FILES:
    local_path = os.path.join(LOCAL_DIR, fname)
    if not os.path.exists(local_path):
        url = f"{BASE_RAW}/{fname}"
        log.info("📥 Скачиваю %s...", fname)
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            with open(local_path, "wb") as f:
                f.write(r.content)
            log.info("✅ %s скачан", fname)
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                log.warning("⚠️ %s не найден на GitHub, пропуск", fname)
            else:
                log.error("❌ %s – HTTP %d: %s", fname, e.response.status_code, e)
        except Exception as e:
            log.error("❌ %s – ошибка: %s", fname, e)
# ---------- ПРОВЕРКА ВЕСОВ ----------
from strategy import MODEL_DIR, load_model
log.info("📁 MODEL_DIR = %s", MODEL_DIR)
s, c, t = load_model("DOGE-USDT", "5m")
log.info("📦 DOGE-USDT 5m  scaler=%s  clf=%s  thr=%.2f", s is not None, c is not None, t)
def calculate_used_nominal() -> float:
    """Считает общий номинал всех открытых позиций."""
    total = 0.0
    for pos in POS.values():
        total += pos.get("qty", 0) * pos.get("entry", 0)
    return total

async def main():
    global PEAK_BALANCE, CYCLE, _MIN_LOT_CACHE   # ← добавьте
    
    # Валидация переменных окружения
    validate_env()
    
    # Запуск health endpoint
    asyncio.create_task(start_health())
    port = 1000
    log.info("💓 Health endpoint started on port %d", port)
    # Создаем экземпляр BingXAsync
    async with BingXAsync(os.getenv("BINGX_API_KEY"), os.getenv("BINGX_SECRET_KEY")) as ex:
        # Загружаем мин-лоты для всех контрактов
        await load_min_lot_cache(ex)
        # ---------- СИНХРОНИЗАЦИЯ ПОЗИЦИЙ ПРИ СТАРТЕ ----------
        positions = await ex.fetch_positions()
        api_pos = {p["symbol"]: p for p in positions.get("data", [])}
        for sym, api in api_pos.items():
            if float(api.get("positionAmt", 0)) != 0:
                POS[sym] = dict(
                    side="LONG" if float(api["positionAmt"]) > 0 else "SHORT",
                    qty=abs(float(api["positionAmt"])),
                    entry=float(api["entryPrice"]),
                    sl_orig=float(api.get("stopLoss", 0)),
                    tp=float(api.get("takeProfit", 0)),
                    ts_open=time.time(),
                )
                log.info("📥 Синхронизировал %s: %s  qty=%.3f  entry=%.5f",
                         sym, POS[sym]["side"], POS[sym]["qty"], POS[sym]["entry"])
        
        
        # Основной торговый цикл
        while True:
            global CYCLE
            CYCLE += 1
            
            try:
                # Получаем текущий баланс
                free_margin = await ex.get_free_margin() 
                equity        = free_margin          # работаем только на свободные деньги 
                log.info("💰 Free margin: $%.2f", free_margin)
                
                
                # Обновляем пиковый баланс
                if equity > PEAK_BALANCE or PEAK_BALANCE == 0:
                    PEAK_BALANCE = equity
                
                # Получаем текущие позиции
                positions = await ex.fetch_positions()
                api_pos = {p["symbol"]: p for p in positions.get("data", [])}
                
                # Синхронизация локальных позиций
                for sym in list(POS.keys()):
                    if sym not in api_pos or float(api_pos.get(sym, {}).get("positionAmt", 0)) == 0:
                        POS.pop(sym, None)
                        OPEN_ORDERS.pop(sym, None)
                        await ex.cancel_all(sym)
                        log.info(f"🧹 {sym} сброшена (нет на бирже)")
                
                # Обработка каждого символа
                for symbol in CONFIG.SYMBOLS:
                    try:
                        # Проверяем, есть ли у нас открытая позиция по этому символу
                        if symbol in api_pos and float(api_pos[symbol].get("positionAmt", 0)) != 0:
                            # Управляем существующей позицией
                            await manage_position(ex, symbol, api_pos[symbol])
                        else:
                            # Ищем новые возможности для входа
                            await open_new_position(ex, symbol, equity)
                    except Exception as e:
                        # молчаливый пропуск – не ломаем цикл
                        if "101204" in str(e) or "101485" in str(e) or "insufficient" in str(e).lower():
                            log.info("⏭️ %s – пропуск (маржа/лот): %s", symbol, e)
                        else:
                            log.warning("⚠️ %s – пропуск: %s", symbol, e)
                                                   
                    # Небольшая задержка между символами
                    await asyncio.sleep(15)
                
                # Проверка общего PnL
                if CYCLE % 20 == 0:
                    await check_total_pnl(ex, equity)   # ← добавить параметр
                
                # Логирование статуса
                if CYCLE % 10 == 0:
                    log.info(f"💓 ALIVE  cycle={CYCLE}  POS={len(POS)}  EQ=${equity:.2f}")
                
                # Сводка
                if CYCLE % 15 == 0:
                    dd = (PEAK_BALANCE - equity) / PEAK_BALANCE * 100 if PEAK_BALANCE else 0.0
                    log.info(f"📊 EQ:${equity:.2f}  Peak:${PEAK_BALANCE:.2f}  DD:{dd:.2f}%  POS:{len(POS)}  ORD:{len(OPEN_ORDERS)}")
                # ---------- Health каждые 30 сек ----------
                if CYCLE % 30 == 0:
                    await check_total_pnl(ex, equity)
                
                # Пауза между циклами
                await asyncio.sleep(10)
                
            except Exception as e:
                log.error(f"💥 Критическая ошибка в основном цикле: {str(e)}")
                log.exception(e)
                await asyncio.sleep(60)

async def manage_position(ex: BingXAsync, symbol: str, api_pos: dict):
    """Управляет существующей позицией"""
    pos = POS.get(symbol)
    if not pos:
        return
    
    mark = float(api_pos["markPrice"])
    side = pos["side"] 
    # ---------- выход по +5 % к цене входа ----------
    gain_pc = (mark - pos["entry"]) / pos["entry"] * 100
    if gain_pc >= 5.0:  # пиковый профит ≥ 5 %
        log.info("🎯 %s +5%% reached (%.2f%%) – closing entire position", symbol, gain_pc)
        await ex.close_position(symbol, "SELL" if side == "LONG" else "BUY", pos["qty"])
        POS.pop(symbol, None)
        await ex.cancel_all(symbol)
        return  # выходим из manage_position сразу# ← добавить
    risk_dist = abs(pos["entry"] - pos["sl_orig"])  # ← добавить
    # ---------- ЖЁСТКИЙ 10 % стоп ----------
    if not pos.get("sl_10_done"):
        sl_10 = pos["entry"] * (0.90 if side == "LONG" else 1.10)
        if (side == "LONG" and mark <= sl_10) or (side == "SHORT" and mark >= sl_10):
            await ex.close_position(symbol, "SELL" if side == "LONG" else "BUY", pos["qty"])
            POS.pop(symbol, None)
            log.info("🛑 %s 10%% SL triggered at %.5f", symbol, mark)
            return
    
    # TP1: 60% при достижении 1.4×ATR
    if not pos.get("tp1_done"):
        tp1_px = pos["entry"] + risk_dist * CONFIG.TP1_MULT if side == "LONG" else pos["entry"] - risk_dist * CONFIG.TP1_MULT
        if (side == "LONG" and mark >= tp1_px) or (side == "SHORT" and mark <= tp1_px):
            qty60 = pos["qty"] * 0.6
            await ex.close_position(symbol, "SELL" if side == "LONG" else "BUY", qty60)
            pos["tp1_done"] = True
            log.info(f"⚡ {symbol} TP1 60% at {mark:.5f}")
    
    # BREAKEVEN: когда цена прошла +1R
    if not pos.get("breakeven_done"):
        be_px = pos["entry"] + risk_dist if side == "LONG" else pos["entry"] - risk_dist
        if (side == "LONG" and mark >= be_px) or (side == "SHORT" and mark <= be_px):
            part_qty = pos["qty"] * 0.2
            await ex.close_position(symbol, "SELL" if side == "LONG" else "BUY", part_qty)
            pos["breakeven_done"] = True
            pos["sl"] = pos["entry"]
            log.info(f"🛡️ {symbol} breakeven @ {pos['entry']:.5f}")
    
    # TRAILING STOP для оставшихся 40%
    trail_dist = abs(pos["entry"] - pos["sl_orig"]) * CONFIG.TRAIL_MULT
    if pos["side"] == "LONG":
        new_sl = mark - trail_dist
        pos["sl"] = max(pos["sl"], new_sl)   # только вперёд
    else:
        new_sl = mark + trail_dist
        pos["sl"] = min(pos["sl"], new_sl)
    
    # STOP-OUT
    if (side == "LONG" and mark <= pos["sl"]) or (side == "SHORT" and mark >= pos["sl"]):
        fee = pos["qty"] * mark * 0.001
        pnl = (mark - pos["entry"]) * pos["qty"] * (1 if side == "LONG" else -1) - fee
        log.info(f"🛑 {symbol} stopped at {mark:.5f}  qty={pos['qty']:.3f}  fee={fee:.4f}$  pnl={pnl:.4f}$")
        await ex.close_position(symbol, "SELL" if side == "LONG" else "BUY", pos["qty"])
        POS.pop(symbol, None)
    # ---------- быстрый выход +12 % ----------
    if not pos.get("tp_fast_done"):
        tp_fast = pos["entry"] * (1.06 if side == "LONG" else 0.88)
        if (side == "LONG" and mark >= tp_fast) or (side == "SHORT" and mark <= tp_fast):
            await ex.close_position(symbol, "SELL" if side == "LONG" else "BUY", pos["qty"])
            POS.pop(symbol, None)
            log.info("🎯 %s +6%% closed at %.5f", symbol, mark)
            return  

async def open_new_position(ex: BingXAsync, symbol: str, equity: float):
    """Ищет новые возможности для входа и открывает позицию"""
    
    # ---------- ПРОВЕРКА СВОБОДНОЙ МАРЖИ ----------
    free_margin = await ex.get_free_margin()
    if free_margin < 1.0:
        log.info("⏭️ Свободной маржи %.2f < 1 $ – пропуск символа %s", free_margin, symbol)
        return  # ✅ ВЫХОДИМ из функции, а не из цикла

    # Проверяем, есть ли уже открытый ордер по этому символу
    if OPEN_ORDERS.get(symbol):
        try:
            oo = await ex.fetch_order(symbol, OPEN_ORDERS[symbol])
            status = oo.get("data", {}).get("status", "")
            if status == "FILLED":
                OPEN_ORDERS.pop(symbol, None)
            else:
                return
        except Exception as e:
            if "101204" in str(e) or "101209" in str(e):
                log.warning("⚠️ %s – маржа мала, пропуск", symbol)
            else:
                log.exception(e)
        return

    # Получаем лучший таймфрейм
    tf = await best_timeframe(ex, symbol)
    klines = await ex.klines(symbol, tf, 150)
    if not klines:
        log.info(f"⏭️ {symbol} {tf} – klines ПУСТО")
        return

    if isinstance(klines[0], dict):
        klines = [[d["time"], d["open"], d["high"], d["low"], d["close"], d["volume"]] for d in klines]

    last = klines[-1]
    log.info(f"RAW {symbol} {tf}  len={len(klines)}  last: {last}")
    log.info(f"THINK-CONTINUE {symbol} – расчёт начат")

    if float(last[2]) == float(last[3]):
        log.info(f"FLAT {symbol} {tf}  h=l={last[2]}")
        return

    log.info(f"⏳ CALLING micro_score() for {symbol}")
    score = await asyncio.get_event_loop().run_in_executor(
        concurrent.futures.ThreadPoolExecutor(max_workers=5),
        micro_score,
        klines, symbol, tf
    )
    log.info(f"✅ micro_score() DONE for {symbol}")

    atr_pc = score["atr_pc"]
    px = float(last[4])
    vol_usd = float(last[5]) * px
    min_vol_dyn = equity * 1.0
    side = ("LONG" if score["long"] > score["short"] else
            "SHORT" if score["short"] > score["long"] else None)

    log.info(f"🧠 {symbol} tf={tf} atr={atr_pc:.4f} vol={vol_usd:.0f}$ side={side} long={score['long']:.2f} short={score['short']:.2f}")

    # Фильтры
    utc_hour = datetime.now(timezone.utc).hour
    if not (CONFIG.TRADE_HOURS[0] <= utc_hour < CONFIG.TRADE_HOURS[1]):
        log.info(f"⏭️  {symbol} – вне торгового окна")
        return

    if atr_pc < CONFIG.MIN_ATR_PC:
        log.info(f"⏭️  {symbol} low atr")
        return

    if vol_usd < min_vol_dyn:
        log.info(f"⏭️ {symbol} low vol (dyn {min_vol_dyn:.0f}$)")
        return

    if len(POS) >= CONFIG.MAX_POS:
        log.info(f"⏭️  {symbol} max pos reached")
        return

    if symbol in POS:
        log.info(f"⏭️ {symbol} already in POS – skip")
        return

    # ---------- РАСЧЁТ РАЗМЕРА ----------
    sizing = calc(px, atr_pc * px, side, equity, symbol)
    if sizing.size <= 0:
        log.info(f"⏭️  {symbol} sizing zero")
        return

    # ---------- ОГРАНИЧЕНИЕ: не более MAX_BALANCE_PC от equity ----------
    max_nom_per_trade = equity * CONFIG.MAX_BALANCE_PC
    if sizing.size * px > max_nom_per_trade:
        new_size = max_nom_per_trade / px
        sizing = Sizing(
            size=new_size,
            usd_risk=sizing.usd_risk * (new_size / sizing.size),
            sl_px=sizing.sl_px,
            tp_px=sizing.tp_px,
            partial_qty=new_size * CONFIG.PARTIAL_TP,
            atr=sizing.atr
        )
        log.info(f"📉 {symbol} урезан до {CONFIG.MAX_BALANCE_PC*100:.0f}% баланса: nominal=${new_size * px:.2f}")

    # ---------- УЧЁТ УЖЕ ЗАНЯТОЙ МАРЖИ ----------
    used_nominal = calculate_used_nominal()
    theoretical_max = equity * CONFIG.LEVERAGE
    available_nominal = theoretical_max - used_nominal

    if available_nominal <= 0:
        log.info(f"⏭️ {symbol} — нет свободной маржи (used: ${used_nominal:.2f})")
        return

    # Безопасный лимит: 80% от свободной маржи
    safe_nominal = available_nominal * 0.8
    max_coins = safe_nominal / px
    final_size = min(sizing.size, max_coins)

    if final_size <= 0:
        log.info(f"⏭️ {symbol} — недостаточно маржи даже для минимального входа")
        return

    # ---------- МИНИМАЛЬНЫЙ НОМИНАЛ ----------
    min_nom = CONFIG.MIN_NOTIONAL_FALLBACK * 0.5 if symbol in (
        "DOGE-USDT", "LTC-USDT", "SHIB-USDT", "XRP-USDT", "BNB-USDT", "SUI-USDT"
    ) else CONFIG.MIN_NOTIONAL_FALLBACK
    min_nom = min(min_nom, safe_nominal)

    if final_size * px < min_nom:
        final_size = min_nom / px
        # Но не больше, чем позволяет свободная маржа
        final_size = min(final_size, max_coins)
        if final_size * px < min_nom:
            log.info(f"⏭️ {symbol} — не хватает маржи даже на мин. номинал ${min_nom:.2f}")
            return
        log.info(f"⚠️ {symbol} увеличен до мин. номинала: {final_size * px:.2f}$")

    # ---------- ФИНАЛЬНЫЙ SIZING ----------
    sizing = Sizing(
        size=final_size,
        usd_risk=sizing.usd_risk * (final_size / sizing.size) if sizing.size > 0 else 0,
        sl_px=sizing.sl_px,
        tp_px=sizing.tp_px,
        partial_qty=final_size * CONFIG.PARTIAL_TP,
        atr=sizing.atr
    )

    # ---------- РИСК НЕ БОЛЕЕ 20% БАЛАНСА ----------
    max_risk_usd = equity * 0.20
    if sizing.usd_risk > max_risk_usd:
        k = max_risk_usd / sizing.usd_risk
        new_size = sizing.size * k
        sizing = Sizing(
            size=new_size,
            usd_risk=max_risk_usd,
            sl_px=sizing.sl_px,
            tp_px=sizing.tp_px,
            partial_qty=new_size * CONFIG.PARTIAL_TP,
            atr=sizing.atr
        )
        log.info("⚖️ %s риск урезан до 20%% баланса", symbol)

    log.info(f"FLOW-OK {symbol}  px={px:.5f} sizing={sizing.size:.6f}")

    if symbol not in POS and symbol not in OPEN_ORDERS:
        try:
            await ex.set_leverage(symbol, CONFIG.LEVERAGE, "LONG" if side == "LONG" else "SHORT")
        except RuntimeError as e:
            if "leverage already set" not in str(e):
                log.warning(f"⚠️ set_leverage {symbol}: {e}")

        order_data = await limit_entry(
            ex, symbol,
            "BUY" if side == "LONG" else "SELL",
            sizing.size,
            px,
            sizing.sl_px,
            sizing.tp_px,
            equity
        )
        if order_data is None:
            log.info(f"⏭ {symbol} – пропуск (limit_entry вернул None)")
            return

        order_id, entry_px, qty_coin = order_data
        OPEN_ORDERS[symbol] = order_id

        avg_px = await await_fill_or_cancel(ex, order_id, symbol, max_sec=8)
        if avg_px is None:
            return

        sl_tp_ids = await limit_sl_tp(
            ex, symbol,
            "BUY" if side == "LONG" else "SELL",
            qty_coin,
            sizing.sl_px,
            sizing.tp_px
        )

        POS[symbol] = dict(
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
            sl_10_done=False,
            tp_fast_done=False,
        )
        log.info(f"📨 {symbol} {side} {qty_coin:.6f} @ {avg_px:.5f} SL={sizing.sl_px:.5f} TP={sizing.tp_px:.5f}")
    # ---------- ФИНАЛЬНЫЙ ПРОПУСК – если не вошли ----------
    if symbol not in POS and symbol not in OPEN_ORDERS:
        log.info("⏭️ %s – нет входа, идём дальше", symbol)    

async def check_total_pnl(ex: BingXAsync, equity: float):
    """Проверяет общий PnL и закрывает все позиции при +2%"""
    total_pnl = 0.0
    try:
        positions = await ex.fetch_positions()
        api_pos = {p["symbol"]: p for p in positions.get("data", [])}
        
        for sym in POS:
            if sym not in api_pos:
                continue
            pos = POS[sym]
            mark = float(api_pos[sym]["markPrice"])
            fee = pos["qty"] * mark * 0.001
            pnl = (mark - pos["entry"]) * pos["qty"] * (1 if pos["side"] == "LONG" else -1) - fee
            total_pnl += pnl
        
        if total_pnl > equity * 0.02:
            log.info(f"💰 TOTAL PnL = {total_pnl:.2f}$ > 2% – закрываю все позиции")
            for s in list(POS.keys()):
                side = "SELL" if POS[s]["side"] == "LONG" else "BUY"
                await ex.close_position(s, side, POS[s]["qty"])
                POS.pop(s, None)
                await ex.cancel_all(s)
            log.info("✅ Все позиции закрыты по общему PnL")
    except Exception as e:
        log.warning(f"⚠️  Не смог рассчитать PnL: {e}")
 
async def self_diagnose(ex: BingXAsync):
    """Проверяет здоровье системы и корректирует параметры"""
    try:
        info = await ex._public_get("/openApi/swap/v2/server/time")
        server_time = info["data"]["serverTime"]
        local_time = int(time.time() * 1000)
        time_diff = abs(server_time - local_time)
        
        if time_diff > 5000:
            log.warning("⏰ Разница времени: %d мс → возможны ошибки", time_diff)
            # Можно автоматически перезапустить
            return False
        
        # Проверка контрактов
        contracts = await ex._public_get("/openApi/swap/v2/quote/contracts")
        symbols_online = [c["symbol"] for c in contracts["data"]]
        for s in CONFIG.SYMBOLS:
            if s.replace("-", "") not in symbols_online:
                log.warning("⚠️ Символ %s не активен", s)
        
        return True
    except Exception as e:
        log.error("🔧 Самодиагностика провалилась: %s", e)
        return False       

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logging.critical(f"CRASH in main(): {e}", exc_info=True)
        sys.exit(1)
