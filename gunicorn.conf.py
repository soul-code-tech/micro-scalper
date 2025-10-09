# gunicorn.conf.py
import os

bind = f"0.0.0.0:{os.getenv('PORT', '10000')}"
workers = 2
worker_class = "uvicorn.workers.UvicornWorker"
worker_connections = 1000
keepalive = 5
max_requests = 1000
max_requests_jitter = 50
preload_app = True
