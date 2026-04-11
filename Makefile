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

.PHONY: help build build-client stage-skills dev run test test-extension test-client test-all tidy fmt vet eval eval-structural eval-semconv eval-golden eval-fixture release-local release list-skills clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  %-20s %s\n", $$1, $$2}'

# --- Client build ---

build-client: ## Build React client into Go static assets
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

release-local: ## Build release archives locally via GoReleaser (snapshot, no publish)
	goreleaser release --snapshot --clean

release: ## Build and publish a release via GoReleaser (requires GITHUB_TOKEN)
	goreleaser release --clean

# --- Evals ---

EVALS_DIR  := evals
GOLDEN_DIRS := golden/python/flask-basic golden/node/express-basic golden/go/chi-basic

eval-structural: ## Validate golden structural properties
	@cd $(EVALS_DIR) && for d in $(GOLDEN_DIRS); do \
		echo "=== structural: $$d ==="; \
		uv run scripts/check_structural.py --golden-only $$d || exit 1; \
	done

eval-semconv: ## Validate golden inventories for semconv compliance
	@cd $(EVALS_DIR) && for d in $(GOLDEN_DIRS); do \
		echo "=== semconv: $$d ==="; \
		uv run scripts/check_semconv.py --inventory $$d/inventory.md || exit 1; \
	done

eval-golden: ## Validate golden inventories for internal consistency
	@cd $(EVALS_DIR) && for d in $(GOLDEN_DIRS); do \
		echo "=== golden self-check: $$d ==="; \
		uv run scripts/run_golden_compare.py --self-check $$d || exit 1; \
	done

eval: eval-structural eval-semconv eval-golden ## Run all golden validation evals (CI-safe)

eval-fixture: ## Run post-skill evals against an instrumented fixture (local only)
	cd $(EVALS_DIR) && uv run scripts/check_structural.py ../examples/python/flask-basic golden/python/flask-basic
	cd $(EVALS_DIR) && uv run scripts/check_semconv.py ../examples/python/flask-basic
	cd $(EVALS_DIR) && uv run scripts/run_golden_compare.py ../examples/python/flask-basic golden/python/flask-basic --threshold 0.80

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
