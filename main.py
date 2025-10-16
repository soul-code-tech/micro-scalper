#!/usr/bin/env python3
import os
import asyncio
import signal
import pandas as pd
import sys
from config        import CONFIG, validate_env
from core.exchange import BingXAsync
from core.grid_manager import GridManager, load_state, save_state
from core.logger   import log
from indicators.ta import adx, atr_percent
from health        import start_health

ACTIVE_GRIDS = {}
LAST_DEPLOY  = {}
SHUTDOWN     = False

async def is_sideways(symbol: str, ex: BingXAsync) -> bool:
    k = await ex.klines(symbol, "1h", 50)
    if len(k) < 50: return False
    df = pd.DataFrame(k, columns=["t","o","h","l","c","v"]).astype(float)
    adx_val = adx(df["h"], df["l"], df["c"])
    atr_pct = atr_percent(df["h"], df["l"], df["c"])
    return adx_val < CONFIG.ADX_THRESHOLD and atr_pct < CONFIG.ATR_PCT_THRESHOLD

async def shutdown():
    global SHUTDOWN
    SHUTDOWN = True
    await log("🛑 Graceful shutdown …")
    for sym in list(ACTIVE_GRIDS):
        GridManager(sym, 0, 0).emergency_close_now()
    save_state({})

async def main():
    validate_env()
    await start_health()
    await log("🚀 BingX-VST-Grid started")
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: asyncio.create_task(shutdown()))

    async with BingXAsync(CONFIG.API_KEY, CONFIG.SECRET_KEY) as ex:
        # 1. Устанавливаем плечо 1 раз на каждый символ/сторону (игнорим ошибки)
        for symbol in CONFIG.SYMBOLS:
            for side in ("LONG", "SHORT"):
                try:
                    await ex.set_leverage(symbol, CONFIG.LEVERAGE, side)
                except RuntimeError as e:
                    # 109415 «already set» или 429 – не критично
                    if "already set" in str(e) or "429" in str(e):
                        continue
                    raise

        # 2. Чистим ордера при старте
        for symbol in CONFIG.SYMBOLS:
            await ex.cancel_all(symbol)

        # 3. Основной цикл
        while not SHUTDOWN:
            try:
                equity = await ex.get_balance()
                positions = await ex.fetch_positions()

                # убираем завершённые
                for s in list(ACTIVE_GRIDS):
                    if s not in positions:
                        ACTIVE_GRIDS.pop(s, None)

                for symbol in CONFIG.SYMBOLS:
                    if SHUTDOWN: break
                    if symbol in ACTIVE_GRIDS:                       # уже работает
                        await ACTIVE_GRIDS[symbol].update(ex)
                        continue

                    if not await is_sideways(symbol, ex):   # <-- добавьте await                  # фильтр
                        continue

                    center = float((await ex.klines(symbol, "15m", 1))[0][4])
                    grid   = GridManager(symbol, center, equity)
                    if await grid.deploy(ex):
                        ACTIVE_GRIDS[symbol] = grid
                        LAST_DEPLOY[symbol]  = asyncio.get_event_loop().time()
                        await log(f"✅ Grid {symbol} @ {center:.4f}")

                await asyncio.sleep(60)
            except Exception as e:
                import traceback
                traceback.print_exc(file=sys.stderr)   # <-- полный стек
                await log(f"💥 Loop error: {e}")
                await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())
