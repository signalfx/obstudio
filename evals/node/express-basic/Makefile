.PHONY: dev test logging-workflow-check

dev:
	npm run dev

test:
	node --check app.js
	@if [ -n "$$LOGGING_WORKFLOW_VERIFIER" ]; then $(MAKE) logging-workflow-check; else echo "Host logging workflow check not configured"; fi

logging-workflow-check:
	"$$LOGGING_WORKFLOW_PYTHON" "$$LOGGING_WORKFLOW_VERIFIER" --start-command-json '["make","dev"]'
