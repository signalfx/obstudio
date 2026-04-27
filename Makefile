BINARY     := obstudio
GO_DIR     := observer
GO_CMD     := ./cmd/obstudio
GO         := go
GOFLAGS    ?=
VERSION    ?= 0.1.0
LDFLAGS    := -ldflags "-X main.version=$(VERSION)"

BUILD_DIR  := build
SKILLS_SRC := skills
EVALS_DIR  := evals
PYTEST_PLUGIN_DIR := pytest-codex-evals

ABS_BUILD  := $(CURDIR)/$(BUILD_DIR)

.PHONY: help build build-client build-vsix stage-skills bundle-weaver dev run load-severity-demo test test-extension test-client test-all tidy fmt vet skill-eval skill-eval-all skill-eval-list skill-eval-ab skill-eval-ab-all test-eval-harness test-pytest-plugin build-pytest-plugin publish-pytest-plugin release-local release list-skills clean

help: ## Show available targets
	@grep -hE '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  %-20s %s\n", $$1, $$2}'

# --- Client build ---

build-client: ## Build React client into Go static assets
	cd $(GO_DIR)/client && npm ci
	cd $(GO_DIR) && $(GO) run ./cmd/build-client

stage-skills: ## Stage skills into observer for embedding
	cd $(GO_DIR) && $(GO) run ./cmd/stage-skills

dev: ## Watch client files and rebuild on changes (hot reload)
	cd $(GO_DIR)/client && npm run dev

# --- Go build ---

bundle-weaver: ## Fetch the local Weaver validator runtime into build output
	@mkdir -p $(BUILD_DIR)
	cd $(GO_DIR) && $(GO) run ./cmd/fetch-weaver -output $(ABS_BUILD)

build: stage-skills build-client bundle-weaver ## Build obstudio binary (client + skills embedded)
	@mkdir -p $(BUILD_DIR)
	cd $(GO_DIR) && $(GO) build $(GOFLAGS) $(LDFLAGS) -o $(ABS_BUILD)/$(BINARY) $(GO_CMD)

build-vsix: ## Build the VS Code extension package (.vsix)
	cd extension && npm ci
	cd extension && npm run build:vsix

run: build ## Build and run the collector
	$(BUILD_DIR)/$(BINARY)

load-severity-demo: ## Load sample logs covering severityNumber/text combinations and keep the emitter alive for manual UI testing
	@python3 observer/load_severity_demo.py

test: stage-skills ## Run all Go tests
	cd $(GO_DIR) && $(GO) test ./...

test-extension: ## Run extension unit + integration tests
	cd extension && npm ci && npm run test:all

test-client: ## Run client unit tests
	cd $(GO_DIR)/client && npm ci && npx vitest run

test-all: ## Run all tests (Go + client + extension)
	$(MAKE) test
	$(MAKE) test-client
	$(MAKE) test-extension

tidy: ## Tidy Go modules
	cd $(GO_DIR) && $(GO) mod tidy

fmt: ## Format Go source
	cd $(GO_DIR) && $(GO) fmt ./...

vet: stage-skills ## Vet Go source
	cd $(GO_DIR) && $(GO) vet ./...

# --- Release ---

release-prep: stage-skills build-client ## Prepare assets for GoReleaser (skills + client)

release-local: release-prep ## Build release archives locally via GoReleaser (snapshot, no publish)
	goreleaser release --snapshot --clean

release: release-prep ## Build and publish a release via GoReleaser (requires GITHUB_TOKEN)
	goreleaser release --clean

# --- Skill evals ---

skill-eval: ## Validate skill eval JSONs (e.g. make skill-eval SKILL=skills/otel-instrument)
	$(MAKE) -C $(EVALS_DIR) $@

skill-eval-all: ## Validate all Codex skill eval JSONs
	$(MAKE) -C $(EVALS_DIR) $@

skill-eval-list: ## List discovered Codex skill evals
	$(MAKE) -C $(EVALS_DIR) $@

skill-eval-ab: ## Run live Codex A/B evals (e.g. make skill-eval-ab SKILL=skills/otel-instrument)
	$(MAKE) -C $(EVALS_DIR) $@

skill-eval-ab-all: ## Run all live Codex A/B evals
	$(MAKE) -C $(EVALS_DIR) $@

test-eval-harness: ## Run fast unit tests for the Codex eval harness
	$(MAKE) -C $(EVALS_DIR) $@

test-pytest-plugin: ## Run pytest plugin unit tests
	$(MAKE) -C $(PYTEST_PLUGIN_DIR) test

build-pytest-plugin: ## Build pytest plugin distribution artifacts
	$(MAKE) -C $(PYTEST_PLUGIN_DIR) build

publish-pytest-plugin: ## Publish pytest plugin distribution artifacts (requires uv publish credentials)
	$(MAKE) -C $(PYTEST_PLUGIN_DIR) publish

# --- Skills ---

list-skills: ## List available skills in this repo
	@echo "Available skills:"
	@find "$(SKILLS_SRC)" -name SKILL.md | sort | while read skillfile; do \
		name=$$(head -5 "$$skillfile" | grep '^name:' | sed 's/^name:[[:space:]]*//'); \
		desc=$$(awk '/^description:/{found=1; sub(/^description:[[:space:]]*>*-*[[:space:]]*/,""); if(length>0) print; next} found && /^[[:space:]]/{sub(/^[[:space:]]*/,""); print; next} found{exit}' "$$skillfile" | tr '\n' ' '); \
		printf "  %-20s %s\n" "$$name" "$$desc"; \
	done

# --- Clean ---

clean: ## Remove build artifacts
	rm -rf "$(BUILD_DIR)" dist $(GO_DIR)/cmd/obstudio/_skills $(GO_DIR)/internal/web/static/assets $(GO_DIR)/client/public/assets
