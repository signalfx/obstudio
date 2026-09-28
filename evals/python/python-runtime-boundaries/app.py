from __future__ import annotations

import os

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

# Importing this module configures providers before Gunicorn forks when
# preload_app is enabled in gunicorn_conf.py.
from telemetry import PROVIDER_PID


app = FastAPI(title="Python Runtime Boundary Demo")
FastAPIInstrumentor.instrument_app(app)


@app.get("/health")
async def health() -> dict[str, int | str]:
    return {
        "status": "ok",
        "worker_pid": os.getpid(),
        "provider_pid": PROVIDER_PID,
    }


@app.get("/work/{work_type}")
async def run_work(work_type: str) -> dict[str, str]:
    return {"work_type": work_type, "status": "complete"}
