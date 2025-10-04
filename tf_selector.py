#!/usr/bin/env python3
import time
import logging
from typing import Dict
from strategy import micro_score
from exchange import BingXAsync

log = logging.getLogger("tf_selector")

CACHE: Dict[str, tuple] = {}   # symbol -> (tf, expire_ts)

async def best_timeframe(ex: BingXAsync, sym: str) -> str:
    now = time.time()
    cached = CACHE.get(sym)
    if cached and cached[1] > now:
        return cached[0]

    signals = {}
    for tf in ("5m", "15m"):
        try:
            klines = await ex.klines(sym, tf, 100)
        except Exception as e:
            log.warning("❌ %s klines fail: %s", sym, e)
            continue

        score = micro_score(klines, sym, tf)  # ✅ правильный вызов
        signals[tf] = (score["long"] > 0) + (score["short"] > 0)

    if not signals:
        log.warning("⚠️  %s no signals", sym)
        return "5m"  # fallback

    best = max(signals, key=signals.get)  # больше сигналов → лучше
    CACHE[sym] = (best, now + 240 * 60)  # кэш на 4 часа
    return best
