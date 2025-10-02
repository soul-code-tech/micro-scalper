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
            info = await ex.balance()
            data = info.get("data", "0")
            if isinstance(data, dict):
                bal = float(data.get("balance", "0"))
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

def run_web():
    app = web.Application()
    app.add_routes(routes)
    web.run_app(app, host="0.0.0.0", port=CONFIG.HEALTH_PORT)
