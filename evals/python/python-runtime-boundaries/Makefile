.PHONY: sync known-failures cli web-gunicorn web-uvicorn conda-bad clean

sync:
	uv sync

known-failures: sync
	PYTHONPATH=. uv run python diagnostics/known_failures.py

cli: sync
	OTEL_SERVICE_NAME=customer-python-cli uv run python cli.py --task import --task reconcile

web-gunicorn: sync
	OTEL_SERVICE_NAME=customer-python-api uv run gunicorn -c gunicorn_conf.py app:app

web-uvicorn: sync
	OTEL_SERVICE_NAME=customer-python-api uv run uvicorn app:app --workers 2 --port 8060

# Intentionally wrong: the agent executable is resolved before entering the
# Conda environment, so its site-packages may not match the target Python.
conda-bad:
	opentelemetry-instrument conda run -n customer-python python cli.py --task import

clean:
	rm -rf .venv .pytest_cache __pycache__ diagnostics/__pycache__ .observe
