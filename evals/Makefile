SUBDIRS := $(sort $(dir $(wildcard */*/Makefile */*/makefile)))
ROOT_DIR := $(abspath ..)

SKILL ?=
CASE ?=
PROMPT ?=
MODEL ?=
NO_QUALITATIVE ?=
EVAL_CONFIG ?= codex-evals.toml
EVAL_AB_CONFIG ?= codex-evals.ab.toml

EVAL_TARGET = $(if $(CASE),$(CASE),.)
EVAL_PROMPT_FILTER = $(if $(PROMPT),-k "$(PROMPT)",)
EVAL_SKILL_PATH = $(if $(SKILL),$(if $(filter /%,$(SKILL)),$(SKILL),$(if $(wildcard $(SKILL)/SKILL.md),$(abspath $(SKILL)),$(abspath $(ROOT_DIR)/$(SKILL)))))
EVAL_SKILL_FLAG = $(if $(SKILL),--skill "$(EVAL_SKILL_PATH)",)
EVAL_FLAGS = $(EVAL_SKILL_FLAG) --codex-eval-config "$(EVAL_CONFIG)"
EVAL_AB_FLAGS = $(EVAL_SKILL_FLAG) --codex-eval-config "$(EVAL_AB_CONFIG)" $(if $(MODEL),--model "$(MODEL)",) $(if $(NO_QUALITATIVE),--no-qualitative,)
EVAL_LIST_FLAGS = $(EVAL_FLAGS)

.PHONY: build test skill-eval skill-eval-all skill-eval-list skill-eval-ab skill-eval-ab-all test-eval-harness

build test:
	@for dir in $(SUBDIRS); do \
		$(MAKE) -C $$dir $@ || exit $$?; \
	done

skill-eval: ## Validate skill eval JSONs
	uv run pytest $(EVAL_TARGET) $(EVAL_PROMPT_FILTER) $(EVAL_FLAGS)

skill-eval-all: ## Validate all Codex skill eval JSONs
	uv run pytest .

skill-eval-list: ## List discovered Codex skill evals
	uv run pytest $(EVAL_TARGET) $(EVAL_PROMPT_FILTER) --collect-only -q $(EVAL_LIST_FLAGS)

skill-eval-ab: ## Run live Codex A/B evals
ifndef SKILL
	$(error SKILL is required - e.g. make skill-eval-ab SKILL=skills/otel-instrument)
endif
	uv run pytest $(EVAL_TARGET) $(EVAL_PROMPT_FILTER) $(EVAL_AB_FLAGS)

skill-eval-ab-all: ## Run all live Codex A/B evals
	uv run pytest . --codex-eval-config "$(EVAL_AB_CONFIG)" $(if $(MODEL),--model "$(MODEL)",) $(if $(NO_QUALITATIVE),--no-qualitative,)

test-eval-harness: ## Run fast unit tests for the Codex eval harness
	uv run pytest .
