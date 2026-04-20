BINARY     := obstudio
GO_DIR     := observer
GO_CMD     := ./cmd/obstudio
GO         := go
GOFLAGS    ?=
VERSION    ?= 0.1.0
LDFLAGS    := -ldflags "-X main.version=$(VERSION)"

BUILD_DIR  := build
SKILLS_SRC := skills

ABS_BUILD  := $(CURDIR)/$(BUILD_DIR)

.PHONY: help build build-client stage-skills dev run test test-extension test-client test-all tidy fmt vet pytest eval-fixture ab-test ab-test-full skill-eval skill-eval-all release-local release list-skills clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | \
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

build: stage-skills build-client ## Build obstudio binary (client + skills embedded)
	@mkdir -p $(BUILD_DIR)
	cd $(GO_DIR) && $(GO) build $(GOFLAGS) $(LDFLAGS) -o $(ABS_BUILD)/$(BINARY) $(GO_CMD)

run: build ## Build and run the collector
	$(BUILD_DIR)/$(BINARY)

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

# --- Tests ---

EVALS_DIR  := tests
APP        ?=

pytest: ## Run deterministic skill tests (CI-safe, no LLM calls)
	cd $(EVALS_DIR) && uv run pytest -v --tb=short --ignore=test_llm.py

eval-fixture: ## Run tests against an instrumented app (e.g. make eval-fixture APP=examples/python/flask-basic)
ifndef APP
	$(error APP is required — e.g. make eval-fixture APP=examples/python/flask-basic)
endif
	cd $(EVALS_DIR) && uv run pytest -v --tb=short --app=../$(APP)

ab-test: ## Run LLM smoke A/B tests via deepeval (requires AWS credentials for Bedrock)
	cd $(EVALS_DIR) && uv run pytest test_llm.py -v --tb=short -m "not release"

ab-test-full: ## Run ALL LLM A/B tests including release-only tests
	cd $(EVALS_DIR) && uv run pytest test_llm.py -v --tb=short

# --- Skill evals (LLM-based, requires claude CLI) ---

SKILL ?=

skill-eval: ## Run skill evals and show report (e.g. make skill-eval SKILL=splunk-audit)
ifndef SKILL
	$(error SKILL is required — e.g. make skill-eval SKILL=splunk-audit)
endif
	cd $(EVALS_DIR) && uv run python run_skill_eval.py --skill $(SKILL)

skill-eval-all: ## Run evals for all skills and show reports
	cd $(EVALS_DIR) && uv run python run_skill_eval.py --all

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
