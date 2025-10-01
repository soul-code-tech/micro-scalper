import asyncio, signal, sys, os, time, logging
from exchange import BingXAsync
from strategy import micro_score
from risk import calc
from lstm_micro import predict_ensemble
from store import Cache
from health import web_server
from settings import CONFIG

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger("scalper")

cache = Cache()
POS: dict[str, dict] = {}

async def guard(entry: float, side: str, book: dict) -> bool:
    bid, ask = float(book["bids"][0][0]), float(book["asks"][0][0])
    spread = (ask - bid) / bid
    if spread > CONFIG.MAX_SPREAD:
        log.warning("%s skip – wide spread %.3f", sym, spread)
        return False
    slippage = (entry - ask) / ask if side == "LONG" else (bid - entry) / bid
    if slippage > CONFIG.MAX_SLIPPAGE:
        log.warning("%s skip – bad slippage %.3f", sym, slippage)
        return False
    return True

async def trade_loop(ex: BingXAsync):
    while True:
        equity = float((await ex.balance())["data"]["balance"])
        positions = {p["symbol"]: p for p in (await ex.fetch_positions())["data"]}
        for sym in CONFIG.SYMBOLS:
            pos = positions.get(sym)
            if pos and float(pos["positionAmt"]) != 0:
                await manage(ex, sym, pos)
                continue
            if len(POS) >= CONFIG.MAX_POS:
                continue
            klines = await ex.klines(sym, CONFIG.TIMEFRAME, 150)
            book   = await ex.order_book(sym, 5)
            score  = micro_score(klines)
            atr_pc = score["atr_pc"]
            if atr_pc < CONFIG.MIN_ATR_PC:
                continue
            px = float(book["asks"][0][0]) if score["long"] > score["short"] else float(book["bids"][0][0])
            vol_usd = float(klines[-1][5]) * px
            if vol_usd < CONFIG.MIN_VOL_USD_1m:
                continue
            lstm_prob = predict_ensemble(klines)
            side = ("LONG" if lstm_prob > CONFIG.PROBA_LONG else
                    "SHORT" if lstm_prob < CONFIG.PROBA_SHORT else None)
            if not side or not await guard(px, side, book):
                continue
            sizing = calc(px, atr_pc * px, side, equity)
            order = await ex.place_order(sym, side, "LIMIT", sizing.size, px, CONFIG.POST_ONLY)
            if order and order["code"] == 0:
                POS[sym] = dict(side=side, qty=sizing.size, entry=px, sl=sizing.sl_px,
                                tp=sizing.tp_px, part=sizing.partial_qty, oid=order["data"]["orderId"])
                log.info("%s %s limit %.4f @ %.5f sl=%.5f tp=%.5f", sym, side, sizing.size, px,
                         sizing.sl_px, sizing.tp_px)
        await asyncio.sleep(1)

async def manage(ex: BingXAsync, sym: str, api_pos: dict):
    pos = POS.get(sym)
    if not pos:
        return
    mark = float(api_pos["markPrice"])
    if (pos["side"] == "LONG" and mark <= pos["sl"]) or (pos["side"] == "SHORT" and mark >= pos["sl"]):
        await ex.close_position(sym, ("SELL" if pos["side"] == "LONG" else "BUY"), pos["qty"])
        POS.pop(sym); log.info("%s stopped", sym); return
    if (pos["side"] == "LONG" and mark >= (pos["entry"] + abs(pos["entry"] - pos["sl"]))) or \
       (pos["side"] == "SHORT" and mark <= (pos["entry"] - abs(pos["entry"] - pos["sl"]))):
        await ex.close_position(sym, ("SELL" if pos["side"] == "LONG" else "BUY"), pos["part"])
        log.info("%s partial %.4f", sym, pos["part"])
        pos["sl"] = pos["entry"]   # breakeven

async def main():
    async with BingXAsync(os.getenv("BINGX_API_KEY"), os.getenv("BINGX_SECRET")) as ex:
        await asyncio.gather(trade_loop(ex), web_server())

if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    asyncio.run(main())
