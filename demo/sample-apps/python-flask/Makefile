.PHONY: run dev init-db clean

DEPS := --with flask --with psycopg2-binary --with redis --with celery --with requests --with gunicorn

run: ## Run the app
	uv run $(DEPS) python app.py

dev: ## Run with Flask debug mode
	uv run $(DEPS) flask --app app run --host 0.0.0.0 --port 8080 --reload

init-db: ## Initialize the database
	uv run $(DEPS) flask --app app init-db

worker: ## Start Celery worker
	uv run $(DEPS) celery -A tasks.celery_app worker --loglevel=info

clean: ## Remove generated artifacts
	rm -rf .observe/ .venv/ __pycache__/ uv.lock otel_setup.py pyproject.toml
