.PHONY: sync dev clean

sync:
	uv sync

dev: sync
	uv run flask run --port $(or $(PORT),8000) --reload

clean:
	rm -rf .venv __pycache__ *.db .observe

.PHONY: test logging-workflow-check
test:
	uv run python -m py_compile app.py
	@if [ -n "$$LOGGING_WORKFLOW_VERIFIER" ]; then $(MAKE) logging-workflow-check; else echo "Host logging workflow check not configured"; fi

logging-workflow-check:
	"$$LOGGING_WORKFLOW_PYTHON" "$$LOGGING_WORKFLOW_VERIFIER" --start-command-json '["make","dev"]'
