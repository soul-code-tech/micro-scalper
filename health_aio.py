#!/usr/bin/env python3
import os
import time
import asyncio
import logging
from aiohttp import web
from exchange import BingXAsync
from store import cache
from settings import CONFIG

log = logging.getLogger("health")
START = time.time()

routes = web.RouteTableDef()

@routes.get("/health")
async def health(request: web.Request) -> web.Response:
    try:
        async with BingXAsync(os.getenv("BINGX_API_KEY"),
                              os.getenv("BINGX_SECRET_KEY")) as ex:
            equity = await ex.balance()  # это уже float
            bal = equity

        # ⬅️ теперь ВНУТРИ try
        if isinstance(data, dict) and "balance" in data:
            if isinstance(data["balance"], dict):
                bal = float(data["balance"]["equity"])
            else:
                bal = float(data["balance"])
        else:
            bal = float(data)

    except Exception as e:
        log.error("Health error: %s", e)
        return web.json_response({"status": "error", "msg": str(e)}, status=503)

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
