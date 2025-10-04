#!/usr/bin/env python3
import os
from flask import Flask, jsonify

app = Flask(__name__)

@app.route("/health")
def health():
    # 200 OK только если ключ вообще объявлен
    return jsonify(
        status="ok" if os.getenv("BINGX_API_KEY") else "fail",
        key_present=bool(os.getenv("BINGX_API_KEY"))
    ), 200 if os.getenv("BINGX_API_KEY") else 503

if __name__ == "__main__":
    app.run(host="0.0.0.0",
            port=int(os.getenv("PORT", 10000)),
            debug=False)
