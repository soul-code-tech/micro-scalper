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

# ---------- фильтр боковика ----------
async def is_sideways(symbol: str, ex: BingXAsync) -> bool:
    k = await ex.klines(symbol, "1h", 50)
    if len(k) < 50: 
        return False
    df = pd.DataFrame(k, columns=["t","o","h","l","c","v"]).astype(float)
    adx_val = adx(df["h"], df["l"], df["c"])
    atr_pct = atr_percent(df["h"], df["l"], df["c"])
    return adx_val < CONFIG.ADX_THRESHOLD and atr_pct < CONFIG.ATR_PCT_THRESHOLD

# ---------- graceful shutdown ----------
async def shutdown():
    global SHUTDOWN
    SHUTDOWN = True
    await log("🛑 Graceful shutdown …")
    for sym in list(ACTIVE_GRIDS):
        await ACTIVE_GRIDS[sym].emergency_close_now()
    save_state({})

# ---------- основной цикл ----------
async def main():
    validate_env()
    await start_health()
    print("🚀 BingX-VST-Grid started", flush=True)

    async with BingXAsync(CONFIG.API_KEY, CONFIG.SECRET_KEY) as ex:
        # 1. Устанавливаем плечо 1 раз на каждый символ/сторону
        for symbol in CONFIG.SYMBOLS:
            for side in ("LONG", "SHORT"):
                try:
                    await ex.set_leverage(symbol, CONFIG.LEVERAGE, side)
                except RuntimeError as e:
                    if "already set" in str(e) or "429" in str(e):
                        continue
                    raise

        # 2. Чистим ордера при старте
        for symbol in CONFIG.SYMBOLS:
            await ex.cancel_all(symbol)

        # 3. Основной цикл
        while not SHUTDOWN:
            try:
                equity   = await ex.get_balance()
                positions = await ex.fetch_positions()

                # --- лог каждого символа ---
                for symbol in CONFIG.SYMBOLS:
                    print(f"🔍 CHECK {symbol}", flush=True)
                    if symbol in ACTIVE_GRIDS:
                        await ACTIVE_GRIDS[symbol].update(ex)
                        continue
                    if not await is_sideways(symbol, ex):
                        print(f"⏭️  SKIP {symbol} (not sideways)", flush=True)
                        continue

                    # --- новая сетка ---
                    now = asyncio.get_event_loop().time()
                    if symbol in LAST_DEPLOY and now - LAST_DEPLOY[symbol] < 4 * 3600:
                        continue

                    center = float((await ex.klines(symbol, "15m", 1))[0][4])
                    grid   = GridManager(symbol, center, equity)
                    if await grid.deploy(ex):
                        ACTIVE_GRIDS[symbol] = grid
                        LAST_DEPLOY[symbol]  = now
                        await log(f"✅ Grid deployed for {symbol} @ {center:.6f}")

                    await asyncio.sleep(1)          # не спамим биржу

                await asyncio.sleep(60)             # 1 цикл в минуту

            except Exception as e:
                import traceback
                traceback.print_exc(file=sys.stderr)
                await log(f"💥 Loop error: {e}")
                await asyncio.sleep(30)

        await log("👋 Bot stopped")

if __name__ == "__main__":
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: asyncio.create_task(shutdown()))
    asyncio.run(main())

if __name__ == "__main__":
    asyncio.run(main())
