.PHONY: sync dev run clean

sync:
	uv sync

dev: sync
	uv run flask run --port 8000 --reload

run: sync
	OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
	OTEL_SERVICE_NAME=python-flask-basic \
	OTEL_BSP_SCHEDULE_DELAY=100 \
	OTEL_METRIC_EXPORT_INTERVAL=1000 \
	uv run flask run --port 8000

clean:
	rm -rf .venv __pycache__ *.db .observe
