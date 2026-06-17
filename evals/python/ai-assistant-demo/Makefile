.PHONY: sync dev load build test clean

sync:
	uv sync

dev: sync
	OTEL_SERVICE_NAME=ai-assistant-demo uv run uvicorn app:app --host 0.0.0.0 --port 8010 --reload

load: sync
	uv run python load_demo.py --base-url http://localhost:8010 --duration 60

build: test

test: sync
	uv run python -m compileall app.py load_demo.py

clean:
	rm -rf .venv __pycache__ .pytest_cache .observe
