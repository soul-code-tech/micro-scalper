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
TICK_SEC     = 10           # минимальный шаг между символами

async def is_sideways(symbol: str, ex: BingXAsync) -> bool:
    k = await ex.klines(symbol, "1h", 50)
    if len(k) < 50: 
        return False
    df = pd.DataFrame(k, columns=["t","o","h","l","c","v"]).astype(float)
    adx_val = adx(df["h"], df["l"], df["c"])
    atr_pct = atr_percent(df["h"], df["l"], df["c"])
    return adx_val < CONFIG.ADX_THRESHOLD and atr_pct < CONFIG.ATR_PCT_THRESHOLD

async def shutdown():
    global SHUTDOWN
    SHUTDOWN = True
    print("🛑 Graceful shutdown …", flush=True)
    for sym in list(ACTIVE_GRIDS):
        await ACTIVE_GRIDS[sym].emergency_close_now()
    save_state({})

# ---------- ВЕЧНИЙ ЦИКЛ (никогда не выходит) ----------
async def main():
    validate_env()
    await start_health()
    print("🚀 BingX-VST-Grid started (вечный цикл)", flush=True)

    async with BingXAsync(CONFIG.API_KEY, CONFIG.SECRET_KEY) as ex:
        # 1. Плечо 1 раз
        for symbol in CONFIG.SYMBOLS:
            for side in ("LONG", "SHORT"):
                try:
                    await ex.set_leverage(symbol, CONFIG.LEVERAGE, side)
                except RuntimeError as e:
                    if "already set" in str(e) or "429" in str(e):
                        continue
                    print(f"⚠️  leverage skip: {e}", flush=True)

        # 2. Чистый старт
        for symbol in CONFIG.SYMBOLS:
            await ex.cancel_all(symbol)

        # 3. ВЕЧНИЙ while True – никаких break/return/sys.exit
        iteration = 0
        while True:
            try:
                iteration += 1
                equity   = await ex.get_balance()
                positions = await ex.fetch_positions()

                for symbol in CONFIG.SYMBOLS:
                    if SHUTDOWN: 
                        break
                    print(f"🔍 CHECK {symbol}", flush=True)
                    if symbol in ACTIVE_GRIDS:
                        await ACTIVE_GRIDS[symbol].update(ex)
                        continue
                    if not await is_sideways(symbol, ex):
                        print(f"⏭️  SKIP {symbol} (not sideways)", flush=True)
                        continue

                    # 4-часовой дедуп
                    now = asyncio.get_event_loop().time()
                    if symbol in LAST_DEPLOY and now - LAST_DEPLOY[symbol] < 4 * 3600:
                        continue

                    center = float((await ex.klines(symbol, "15m", 1))[0][4])
                    grid   = GridManager(symbol, center, equity)
                    if await grid.deploy(ex):
                        ACTIVE_GRIDS[symbol] = grid
                        LAST_DEPLOY[symbol]  = now
                        print(f"✅ Grid deployed for {symbol} @ {center:.6f}", flush=True)

                    await asyncio.sleep(10)   # между символами

                if SHUTDOWN:
                    break
                await asyncio.sleep(60)       # после цикла по символам

            except Exception as e:
                # **ЛЮБАЯ** ошибка – логируем и **ПРОДОЛЖАЕМ**
                print(f"💥 Loop error (continuing): {e}", flush=True)
                import traceback
                traceback.print_exc(file=sys.stderr)
                await asyncio.sleep(30)

        # **только если пришёл SIGTERM** – выходим
        print("👋 Bot stopped", flush=True)

if __name__ == "__main__":
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: asyncio.create_task(shutdown()))
    # **никаких дополнительных выходов** – только SIGTERM остановит
    asyncio.run(main())
