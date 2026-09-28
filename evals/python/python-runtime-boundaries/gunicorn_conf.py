bind = "127.0.0.1:8060"
workers = 2
worker_class = "uvicorn_worker.UvicornWorker"

# Intentionally wrong with telemetry.py's import-time provider setup.
preload_app = True
