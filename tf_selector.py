#!/usr/bin/env python3
import time
from typing import Dict
from strategy import micro_score
from exchange import BingXAsync

CACHE: Dict[str, tuple] = {}   # symbol -> (tf, expire_ts)

async def best_timeframe(ex: BingXAsync, sym: str) -> str:
    now = time.time()
    cached = CACHE.get(sym)
    if cached and cached[1] > now:
        return cached[0]

    signals = {}
    for tf in ("5m", "15m"):
        klines = await ex.klines(sym, tf, 100)
        score = micro_score(klines)
        # кол-во «прошедших» сигналов
        signals[tf] = (score["long"] > 0) + (score["short"] > 0)

    best = max(signals, key=signals.get)   # больше сигналов → лучше
    CACHE[sym] = (best, now + 240 * 60)    # кэш на 4 ч
    return best
