.PHONY: dev test logging-workflow-check

dev:
	go run .

test:
	go test ./...
	@if [ -n "$$LOGGING_WORKFLOW_VERIFIER" ]; then $(MAKE) logging-workflow-check; else echo "Host logging workflow check not configured"; fi

logging-workflow-check:
	"$$LOGGING_WORKFLOW_PYTHON" "$$LOGGING_WORKFLOW_VERIFIER" --start-command-json '["make","dev"]'
