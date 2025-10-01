#!/usr/bin/env python3
import os, sys, asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from cli import train_one

SYMBOLS = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "DOGE-USDT"]

async def main():
    print("🚀 Start train/retrain")
    for s in SYMBOLS:
        try:
            await train_one(s)
            print(f"✅ {s} done")
        except Exception as e:
            print(f"❌ {s} – {e}")
    print("🏁 Finished")

if __name__ == "__main__":
    asyncio.run(main())
