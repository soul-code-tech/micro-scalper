import os
import sys
import asyncio
import logging
from datetime import datetime, timezone
from exchange import BingXAsync
from settings import CONFIG, validate_env
from orders import load_min_lot_cache, limit_entry, await_fill_or_cancel, limit_sl_tp
from strategy import micro_score
from risk import calc, get_min_lot
from health import start_health_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger("scalper")

POS = {}
OPEN_ORDERS = {}
PEAK_BALANCE = 0.0
CYCLE = 0

async def main():
    global PEAK_BALANCE, CYCLE
    validate_env()
    await start_health_server()

    async with BingXAsync(os.getenv("BINGX_API_KEY"), os.getenv("BINGX_SECRET_KEY")) as ex:
        await load_min_lot_cache(ex)
        positions = await ex.fetch_positions()
        api_pos = {p["symbol"]: p for p in positions.get("data", [])}
        for sym, api in api_pos.items():
            if float(api.get("positionAmt", 0)) != 0:
                POS[sym] = dict(
                    side="LONG" if float(api.get("positionAmt", 0)) > 0 else "SHORT",
                    qty=abs(float(api.get("positionAmt", 0))),
                    entry=float(api.get("entryPrice", 0)),
                    sl_orig=float(api.get("stopLoss", 0)),
                    tp=float(api.get("takeProfit", 0)),
                    ts_open=asyncio.get_event_loop().time(),
                )

        while True:
            CYCLE += 1
            try:
                free_margin = await ex.get_free_margin()
                equity = free_margin
                if equity > PEAK_BALANCE or PEAK_BALANCE == 0:
                    PEAK_BALANCE = equity

                for symbol in CONFIG.SYMBOLS:
                    if symbol in POS:
                        continue
                    if symbol in OPEN_ORDERS:
                        continue
                    if free_margin < 1.0:
                        continue

                    klines = await ex.klines(symbol, "5m", 150)
                    if not klines:
                        continue
                    score = micro_score(klines, symbol, "5m")
                    if score["long"] == 0 and score["short"] == 0:
                        continue

                    side = "LONG" if score["long"] > score["short"] else "SHORT"
                    px = float(klines[-1][4])
                    sizing = calc(px, score["atr_pc"] * px, side, equity, symbol)
                    if sizing.size <= 0:
                        continue

                    order_data = await limit_entry(ex, symbol, "BUY" if side == "LONG" else "SELL",
                        sizing.size, px, sizing.sl_px, sizing.tp_px, equity)
                    if not order_data:
                        continue

                    order_id, entry_px, qty_coin = order_data
                    OPEN_ORDERS[symbol] = order_id
                    avg_px = await await_fill_or_cancel(ex, order_id, symbol)
                    if avg_px is None:
                        OPEN_ORDERS.pop(symbol, None)
                        continue

                    await limit_sl_tp(ex, symbol, "BUY" if side == "LONG" else "SELL", qty_coin, sizing.sl_px, sizing.tp_px)
                    POS[symbol] = {
                        "side": side,
                        "qty": qty_coin,
                        "entry": avg_px,
                        "sl": sizing.sl_px,
                        "sl_orig": sizing.sl_px,
                        "tp": sizing.tp_px,
                    }
                    log.info("✅ %s %s %.6f @ %.5f", symbol, side, qty_coin, avg_px)

                if CYCLE % 10 == 0:
                    log.info(f"📊 Cycle={CYCLE} POS={len(POS)} EQ=${equity:.2f}")

                await asyncio.sleep(10)

            except Exception as e:
                log.error("💥 Main loop error: %s", e)
                await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())
