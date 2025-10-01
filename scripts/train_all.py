#!/usr/bin/env python3
import os
import sys
import asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cli import train_one   # используем вашу asyncio-функцию

SYMBOLS = [
    "BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "DOGE-USDT"
]

async def main():
    print("🚀 Запуск дообучения моделей (каждые 2 часа)")
    os.makedirs("weights", exist_ok=True)

    for symbol in SYMBOLS:
        print(f"\n🔄 Обработка {symbol}...")
        try:
            await train_one(symbol, epochs=2)   # дообучение 2 эпохи
            print(f"  ✅ {symbol} успешно обновлён")
        except ValueError as e:
            if "single class" in str(e) or "low volatility" in str(e):
                print(f"  ⏭️  {symbol} пропущен – {e}")
            else:
                print(f"  ❌ {symbol} пропущен – {e}")
        except Exception as e:
            print(f"  ❌ {symbol} пропущен – {e}")

    print("\n🏁 Цикл дообучения завершён")

if __name__ == "__main__":
    asyncio.run(main())
