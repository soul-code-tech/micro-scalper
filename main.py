import os
import sys
import asyncio
import logging
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

async def main():
    global PEAK_BALANCE, CYCLE, _MIN_LOT_CACHE   # ← добавьте
    
    # Валидация переменных окружения
    validate_env()
    
    # Запуск health endpoint
    asyncio.create_task(start_health())
    
    # Создаем экземпляр BingXAsync
    async with BingXAsync(os.getenv("BINGX_API_KEY"), os.getenv("BINGX_SECRET_KEY")) as ex:
        # Загружаем мин-лоты для всех контрактов
        await load_min_lot_cache(ex)
        
        # Основной торговый цикл
        while True:
            global CYCLE
            CYCLE += 1
            
            try:
                # Получаем текущий баланс
                equity = await ex.balance()
                log.info(f"Баланс: ${equity:.2f}")
                
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
                        log.error(f"❌ Ошибка при обработке {symbol}: {str(e)}")
                        log.exception(e)
                    
                    # Небольшая задержка между символами
                    await asyncio.sleep(0.5)
                
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
                
                # Пауза между циклами
                await asyncio.sleep(15)
                
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
    equity = await ex.balance()          # берём актуальный баланс
    dd = (PEAK_BALANCE - equity) / PEAK_BALANCE * 100
    if dd > CONFIG.MAX_DD_STOP:          # 10 %
        log.warning(f"🛑 MAX_DD_STOP {dd:.2f}% – закрываю {symbol}")
        await ex.close_position(symbol,
                                "SELL" if pos["side"] == "LONG" else "BUY",
                                pos["qty"])
        POS.pop(symbol, None)
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

async def open_new_position(ex: BingXAsync, symbol: str, equity: float):
    """Ищет новые возможности для входа и открывает позицию"""
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
            log.warning(f"❌ не смог проверить ордер {symbol}: {e}")
            return
    
    # Получаем лучший таймфрейм
    tf = await best_timeframe(ex, symbol)
    klines = await ex.klines(symbol, tf, 150)
    if not klines:
        log.info(f"⏭️ {symbol} {tf} – klines ПУСТО")
        return
    
    # Конвертируем словари в списки
    if isinstance(klines[0], dict):
        klines = [[d["time"], d["open"], d["high"], d["low"], d["close"], d["volume"]] for d in klines]
    
    last = klines[-1]
    log.info(f"RAW {symbol} {tf}  len={len(klines)}  last: {last}")
    log.info(f"THINK-CONTINUE {symbol} – расчёт начат")
    
    if float(last[2]) == float(last[3]):
        log.info(f"FLAT {symbol} {tf}  h=l={last[2]}")
        return
    
    # Вызываем micro_score в отдельном потоке
    log.info(f"⏳ CALLING micro_score() for {symbol}")
    score = await asyncio.get_event_loop().run_in_executor(
        concurrent.futures.ThreadPoolExecutor(max_workers=2),
        micro_score,
        klines, symbol, tf
    )
    log.info(f"✅ micro_score() DONE for {symbol}")
    
    atr_pc = score["atr_pc"]
    px = float(last[4])
    vol_usd = float(last[5]) * px
    min_vol_dyn = equity * 0.05
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
    
    # Расчёт размера
    sizing = calc(px, atr_pc * px, side, equity, symbol)
    if sizing.size <= 0:
        log.info(f"⏭️  {symbol} sizing zero")
        return
    
    # Минимальный номинал с API
    try:
        ci = await ex.get_contract_info(symbol)
        min_notional_str = ci["data"][0].get("minNotional")
        if not min_notional_str:
            raise ValueError("minNotional missing")
        min_nom = float(min_notional_str)
    except Exception as e:
        log.warning(f"⚠️  {symbol} minNotional error: {e} — использую fallback")
        min_nom = CONFIG.MIN_NOTIONAL_FALLBACK
    
    # Для дешёвых монет — снижаем порог
    if symbol in ("DOGE-USDT", "LTC-USDT", "SHIB-USDT", "XRP-USDT", "BNB-USDT", "SUI-USDT"):
        min_nom = min(CONFIG.MIN_NOTIONAL_FALLBACK * 0.5, min_nom)
    
    # Максимум: 90% × leverage
    max_nominal = equity * 0.9 * CONFIG.LEVERAGE
    if min_nom > max_nominal:
        log.info(f"⏭️  {symbol} min_nom ({min_nom:.2f}) > max_nom ({max_nominal:.2f}) — пропуск")
        return
    
    min_nom = min(min_nom, max_nominal)
    
    # Подтягиваем размер до минимума
    if sizing.size * px < min_nom:
        new_size = min_nom / px
        log.info(f"⚠️  {symbol} nominal {sizing.size * px:.2f} < {min_nom:.2f} USD — увеличиваю до {new_size:.6f} ({min_nom:.2f} USD)")
        sizing = Sizing(
            size=new_size,
            usd_risk=sizing.usd_risk,
            sl_px=sizing.sl_px,
            tp_px=sizing.tp_px,
            partial_qty=new_size * CONFIG.PARTIAL_TP,
            atr=sizing.atr
        )
    
    # FLOW-OK — все условия пройдены
    log.info(f"FLOW-OK {symbol}  px={px:.5f} sizing={sizing.size:.6f}")
    
    if symbol not in POS and symbol not in OPEN_ORDERS:
        try:
            await ex.set_leverage(symbol, CONFIG.LEVERAGE, "LONG" if side == "LONG" else "SHORT")
        except RuntimeError as e:
            if "leverage already set" not in str(e):
                log.warning(f"⚠️  set_leverage {symbol}: {e}")
        
        # Лимитный вход + OCO SL/TP
        order_data = await limit_entry(ex, symbol, "BUY" if side == "LONG" else "SELL", sizing.usd_risk, CONFIG.LEVERAGE,
                                      sizing.sl_px, sizing.tp_px)
        if order_data is None:
            log.info(f"⏭ {symbol} – пропуск (limit_entry вернул None)")
            return
        
        order_id, entry_px, qty_coin = order_data
        OPEN_ORDERS[symbol] = order_id
        
        # Ожидаем исполнения
        avg_px = await await_fill_or_cancel(ex, order_id, symbol, max_sec=8)
        if avg_px is None:
            return
        
        # Ставим SL и TP
        sl_tp_ids = await limit_sl_tp(ex, symbol, "BUY" if side == "LONG" else "SELL", qty_coin, sizing.sl_px, sizing.tp_px)
        
        # Сохраняем позицию в память
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
        )
        log.info(f"📨 {symbol} {side} {qty_coin:.6f} @ {avg_px:.5f} SL={sizing.sl_px:.5f} TP={sizing.tp_px:.5f}")

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

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logging.critical(f"CRASH in main(): {e}", exc_info=True)
        sys.exit(1)
