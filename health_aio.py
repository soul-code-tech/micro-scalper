import os
import asyncio
from aiohttp import web

async def health_handler(request):
    return web.json_response({"status": "ok"})

async def start_health_server():
    port = int(os.getenv("PORT", "10000"))
    app = web.Application()
    app.router.add_get('/health', health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"✅ Health server running on port {port}")
