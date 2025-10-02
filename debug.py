#!/usr/bin/env python3
import os, sys, traceback, time
from flask import Flask
app = Flask(__name__)

@app.route("/health")
def health():
    return {"status": "debug", "BINGX_API_KEY": bool(os.getenv("BINGX_API_KEY"))}

print("=== DEBUG: Flask starts ===")
for k in ("BINGX_API_KEY", "BINGX_SECRET_KEY", "PORT"):
    print(f"  {k}: {'✅' if os.getenv(k) else '❌'}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)), debug=False)
