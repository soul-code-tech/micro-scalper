#!/usr/bin/env python3
import os, sys, asyncio
from lstm_micro import LSTMEnsemble
from exchange import BingXAsync
from settings import CONFIG

SYMBOLS = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "DOGE-USDT"]

async def train_one(sym: str, epochs: int = 4):
    async with BingXAsync(os.getenv("BINGX_API_KEY"), os.getenv("BINGX_SECRET_KEY")) as ex:
        klines = await ex.klines(sym, CONFIG.TIMEFRAME, 600)   # 600 бар
    model = LSTMEnsemble()
    model.build_models()
    try:
        model.train(klines, epochs=epochs, symbol=sym)
        os.makedirs("weights", exist_ok=True)
        model.save(f"weights/{sym.replace('-','')}.pkl")
        print(f"✅ {sym} updated")
    except ValueError as e:
        print(f"⏭️  {sym} skipped – {e}")

async def main():
    for s in SYMBOLS:
        await train_one(s, epochs=4)

if __name__ == "__main__":
    asyncio.run(main())
