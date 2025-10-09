#!/usr/bin/env python3
import os
import time
import logging
from typing import Optional
from aiohttp import web, ClientSession, ClientTimeout
from exchange import BingXAsync
from store import cache
from settings import CONFIG

log = logging.getLogger("health")
START = time.time()
TIMEOUT = ClientTimeout(total=8)
_SESSION: Optional[ClientSession] = None

routes = web.RouteTableDef()

async def _get_session() -> ClientSession:
    global _SESSION
    if _SESSION is None or _SESSION.closed:
        _SESSION = ClientSession(timeout=TIMEOUT)
    return _SESSION

@routes.get("/health")
async def health(request: web.Request) -> web.Response:
    try:
        async with BingXAsync(
            os.getenv("BINGX_API_KEY"),
            os.getenv("BINGX_SECRET_KEY"),
            session=await _get_session()   # переиспользуем
        ) as ex:
            bal = await ex.balance()
    except Exception as e:
        log.warning("Health fail: %s", e)
        bal = 0.0   # главное – не упасть

    return web.json_response({
        "status": "ok",
        "balance": round(bal, 2),
        "positions": len(cache.get("pos", {})),
        "uptime": int(time.time() - START)
    })

async def start_health():
    app = web.Application()
    app.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", CONFIG.HEALTH_PORT)
    await site.start()
    log.info("Health endpoint started on port %s", CONFIG.HEALTH_PORT)
