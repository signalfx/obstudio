.PHONY: sync dev test clean

sync:
	uv sync

dev: sync
	GALILEO_PROJECT=galileo-agent-demo GALILEO_LOG_STREAM=production OTEL_SERVICE_NAME=galileo-agent-demo uv run uvicorn app:app --host 0.0.0.0 --port 8040

test: sync
	uv run python -m compileall app.py galileo_compat.py
	uv run python -m unittest discover -s tests -p 'test_*.py'

clean:
	rm -rf .venv __pycache__ .pytest_cache .observe
