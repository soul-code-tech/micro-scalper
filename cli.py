#!/usr/bin/env python3
import os, sys, asyncio
from lstm_micro import MicroLSTM
from exchange import BingXAsync
from settings import CONFIG

async def train_one(sym: str):
    async with BingXAsync(os.getenv("BINGX_API_KEY"), os.getenv("BINGX_SECRET_KEY")) as ex:
        klines = await ex.klines(sym, CONFIG.TIMEFRAME, 400)
    m1, m2 = MicroLSTM(60), MicroLSTM(120)
    m1.build(); m2.build()
    m1.train(klines, epochs=4)
    m2.train(klines, epochs=4)
    os.makedirs("weights", exist_ok=True)
    m1.model.save_weights(f"weights/{sym.replace('-','')}.m1.weights.h5")
    m2.model.save_weights(f"weights/{sym.replace('-','')}.m2.weights.h5")
    print(f"✅ {sym} weights saved")

if __name__ == "__main__":
    asyncio.run(train_one(sys.argv[1] if len(sys.argv) > 1 else "BTC-USDT"))
