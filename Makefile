BINARY     := obstudio
GO_DIR     := observer-go
GO_CMD     := ./cmd/obstudio
GO         := go
GOFLAGS    ?=
VERSION    ?= 0.1.0
LDFLAGS    := -ldflags "-X main.version=$(VERSION)"

BUILD_DIR  := build
SKILLS_SRC := skills

ABS_BUILD  := $(CURDIR)/$(BUILD_DIR)

.PHONY: help build run test tidy fmt vet release-local release list-skills clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  %-20s %s\n", $$1, $$2}'

# --- Go build ---

build: ## Build obstudio binary (skills embedded in the binary)
	@rm -rf $(GO_DIR)/cmd/obstudio/_skills
	@cp -R skills $(GO_DIR)/cmd/obstudio/_skills
	@cp docs/examples.md $(GO_DIR)/cmd/obstudio/_skills/examples.md
	@mkdir -p $(BUILD_DIR)
	cd $(GO_DIR) && $(GO) build $(GOFLAGS) $(LDFLAGS) -o $(ABS_BUILD)/$(BINARY) $(GO_CMD)

run: build ## Build and run the collector
	$(BUILD_DIR)/$(BINARY)

test: ## Run all Go tests
	cd $(GO_DIR) && $(GO) test ./...

tidy: ## Tidy Go modules
	cd $(GO_DIR) && $(GO) mod tidy

fmt: ## Format Go source
	cd $(GO_DIR) && $(GO) fmt ./...

vet: ## Vet Go source
	cd $(GO_DIR) && $(GO) vet ./...

# --- Release ---

release-local: ## Build release archives locally via GoReleaser (snapshot, no publish)
	goreleaser release --snapshot --clean

release: ## Build and publish a release via GoReleaser (requires GITHUB_TOKEN)
	goreleaser release --clean

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
	rm -rf "$(BUILD_DIR)" dist $(GO_DIR)/cmd/obstudio/_skills
