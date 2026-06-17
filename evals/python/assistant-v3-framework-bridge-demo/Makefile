.PHONY: sync dev test clean

sync:
	uv sync

dev: sync
	OTEL_SERVICE_NAME=assistant-v3-framework-demo uv run opentelemetry-instrument uvicorn app:app --host 0.0.0.0 --port 8030 --reload

test: sync
	uv run python -m compileall app.py

clean:
	rm -rf .venv __pycache__ .pytest_cache .observe
