#!/usr/bin/env python3
import os
import time
import asyncio
import logging
from flask import Flask, jsonify
from exchange import BingXAsync
from store import cache
from settings import CONFIG

app = Flask(__name__)
START = time.time()
log = logging.getLogger("health")


@app.route("/health")
def health():
    try:
        async def bal():
            async with BingXAsync(os.getenv("BINGX_API_KEY"), os.getenv("BINGX_SECRET_KEY")) as ex:
                info = await ex.balance()
                # надёжный парсинг: может быть {"data": "123.45"} или {"data": {"balance": "123.45"}}
                data = info.get("data", "0")
                if isinstance(data, dict):
                    balance_str = str(data.get("balance", "0"))
                else:
                    balance_str = str(data)
                return float(balance_str) if balance_str.replace(".", "").isdigit() else 0.0

        equity = asyncio.run(bal())
        return jsonify(
            status="ok",
            balance=round(equity, 2),
            positions=len(cache.get("pos", {})),
            uptime=int(time.time() - START)
        )
    except Exception as e:
        log.error("Health error: %s", e)
        return jsonify(status="error", msg=str(e)), 503


def run_web():
    app.run(host="0.0.0.0", port=CONFIG.HEALTH_PORT, debug=False)
