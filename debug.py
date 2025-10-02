#!/usr/bin/env python3
import os, sys, traceback
try:
    print("=== DEBUG: Python starts ===")
    print("ENV check:")
    for k in ("BINGX_API_KEY", "BINGX_SECRET_KEY", "PORT"):
        print(f"  {k}: {'✅' if os.getenv(k) else '❌'}")
    print("=== DEBUG: finished ===")
    # держим процесс живым, чтобы Render не убил
    import time
    time.sleep(300)
except Exception as e:
    print("CRASH:", e, file=sys.stderr)
    traceback.print_exc()
