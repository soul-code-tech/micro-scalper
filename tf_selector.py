async def best_timeframe(ex: BingXAsync, sym: str) -> str:
    now = time.time()
    cached = CACHE.get(sym)
    if cached and cached[1] > now:
        return cached[0]

    signals = {}
    for tf in ("5m", "15m"):  # BingX поддерживает 5m и 15m
        try:
            klines = await ex.klines(sym, tf, 100)  # limit=100
        except Exception as e:
            log.warning("❌ %s klines fail: %s", sym, e)
            continue

        score = micro_score(klines)
        signals[tf] = (score["long"] > 0) + (score["short"] > 0)

    if not signals:
        log.warning("⚠️  %s no signals", sym)
        return "5m"  # если нет сигналов, используем 5m

    best = max(signals, key=signals.get)  # больше сигналов → лучше
    CACHE[sym] = (best, now + 240 * 60)  # кэш на 4 часа
    return best
