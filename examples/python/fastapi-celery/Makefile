.PHONY: sync dev worker up down clean

sync:
	uv sync

dev: sync
	uv run uvicorn app:app --port 8000 --reload

worker: sync
	uv run celery -A worker worker --loglevel=info

up:
	docker compose up --build -d

down:
	docker compose down -v

clean:
	rm -rf .venv __pycache__ *.db .observe
	docker compose down -v 2>/dev/null || true
