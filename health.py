from asyncio import run
from flask import Flask
from exchange import BingXAsync
import os, time

app = Flask(__name__)
_START = time.time()

@app.route("/health")
def health():
    try:
        async def bal():
            async with BingXAsync(os.getenv("BINGX_API_KEY"), os.getenv("BINGX_SECRET")) as ex:
                return float((await ex.balance())["data"]["balance"])
        equity = run(bal())
        return {"status": "ok", "positions": len(POS), "balance": equity, "uptime": int(time.time()-_START)}
    except:
        return {"status": "error"}, 503

async def web_server():
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
