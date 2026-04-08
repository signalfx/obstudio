.PHONY: build test lint run

GOLANGCI_LINT_VERSION := v2.11.4

build: test lint
	go build ./...

test:
	go test ./...

lint:
	go run github.com/golangci/golangci-lint/v2/cmd/golangci-lint@$(GOLANGCI_LINT_VERSION) run

run:
	go run ./cmd/kvstore
