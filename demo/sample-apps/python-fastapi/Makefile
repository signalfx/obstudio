.PHONY: run dev clean

DEPS := --with-requirements requirements.txt

run: ## Run the app
	uv run $(DEPS) python app.py

dev: ## Run with auto-reload
	uv run $(DEPS) uvicorn app:app --host 0.0.0.0 --port 8080 --reload

clean: ## Remove generated artifacts
	rm -rf .observe/ .venv/ __pycache__/ *.db uv.lock otel_setup.py pyproject.toml
