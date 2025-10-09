#!/usr/bin/env python3
import logging
import asyncio  # ← ДОБАВЛЕНО!
from typing import Dict
from strategy import micro_score
from exchange import BingXAsync

log = logging.getLogger("tf_selector")

CACHE: Dict[str, tuple] = {}   # symbol -> (tf, expire_ts)

async def best_timeframe(ex: BingXAsync, sym: str) -> str:
    now = asyncio.get_event_loop().time()
    cached = CACHE.get(sym)
    if cached and cached[1] > now:
        log.info("⚡️ CACHE HIT for %s → %s", sym, cached[0])
        return cached[0]

    # ⚠️ НЕ ДЕЛАЕМ НИКАКИХ ЗАПРОСОВ К БИРЖЕ ТУТ!
    # Возвращаем фиксированный fallback — будет выбран в think()
    log.info("⚡️ CACHE MISS for %s — using fallback 5m", sym)
    CACHE[sym] = ("5m", now + 60)  # кэшируем на 60 сек — чтобы не трясти каждый цикл
    return "5m"

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

    best = max(signals, key=signals.get)
    CACHE[sym] = (best, now + 240 * 60)  # кэш на 4 часа
    return best
