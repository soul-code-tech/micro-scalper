from flask import Flask, jsonify
import os, time, asyncio
from exchange import BingXAsync
from store import Cache
from settings import CONFIG   # ← добавьте эту строку

app = Flask(__name__)
START = time.time()

@app.route("/health")
def health():
    try:
        async def bal():
            async with BingXAsync(os.getenv("BINGX_API_KEY"), os.getenv("BINGX_SECRET_KEY")) as ex:
                return float((await ex.balance())["data"]["balance"])
        equity = asyncio.run(bal())
        return jsonify(
            status="ok",
            balance=round(equity, 2),
            positions=len(cache.get("pos", {})),
            uptime=int(time.time() - START)
        )
    except Exception as e:
        return jsonify(status="error", msg=str(e)), 503

def run_web():
    app.run(host="0.0.0.0", port=CONFIG.HEALTH_PORT, debug=False)
