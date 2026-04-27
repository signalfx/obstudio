SUBDIRS := $(sort $(dir $(wildcard */*/Makefile */*/makefile)))
ROOT_DIR := $(abspath ..)

SKILL ?=
CASE ?=
PROMPT ?=
MODEL ?=
NO_QUALITATIVE ?=
EVAL_WORKERS ?= 1
EVAL_PROGRESS ?= 1
EVAL_CONFIG ?= codex-evals.toml
EVAL_VALIDATION_CONFIG ?= codex-evals.validation.toml
EVAL_BASELINE_CONFIG ?= codex-evals.baseline.toml
EVAL_AB_CONFIG ?= codex-evals.ab.toml

EVAL_TARGET = $(if $(CASE),$(CASE),.)
EVAL_PROMPT_FILTER = $(if $(PROMPT),-k "$(PROMPT)",)
EVAL_QUIET ?=
EVAL_PYTEST_QUIET = $(if $(EVAL_QUIET),-qq,)
EVAL_SKILL_PATH = $(if $(SKILL),$(if $(filter /%,$(SKILL)),$(SKILL),$(if $(wildcard $(SKILL)/SKILL.md),$(abspath $(SKILL)),$(abspath $(ROOT_DIR)/$(SKILL)))))
EVAL_SKILL_FLAG = $(if $(SKILL),--skill "$(EVAL_SKILL_PATH)",)
EVAL_WORKER_FLAGS = $(if $(filter 1,$(strip $(EVAL_WORKERS))),,-n $(EVAL_WORKERS))
EVAL_PROGRESS_FLAG = $(if $(filter 1 true yes,$(strip $(EVAL_PROGRESS))),--codex-eval-progress,)
EVAL_CAPTURE_FLAGS = $(if $(filter 1 true yes,$(strip $(EVAL_PROGRESS))),-s,)
EVAL_FLAGS = $(EVAL_SKILL_FLAG) --codex-eval-config "$(EVAL_CONFIG)"
EVAL_VALIDATION_FLAGS = $(EVAL_SKILL_FLAG) --codex-eval-config "$(EVAL_VALIDATION_CONFIG)"
EVAL_BASELINE_FLAGS = $(EVAL_SKILL_FLAG) --codex-eval-config "$(EVAL_BASELINE_CONFIG)" $(if $(MODEL),--model "$(MODEL)",) $(if $(NO_QUALITATIVE),--no-qualitative,)
EVAL_AB_FLAGS = $(EVAL_SKILL_FLAG) --codex-eval-config "$(EVAL_AB_CONFIG)" $(if $(MODEL),--model "$(MODEL)",) $(if $(NO_QUALITATIVE),--no-qualitative,)
EVAL_LIST_FLAGS = $(EVAL_FLAGS)

.PHONY: build test eval-validation eval-with-skill eval-with-baseline eval-ab eval-all skill-eval skill-eval-all skill-eval-list skill-eval-ab skill-eval-ab-all test-eval-harness test-all

build test:
	@for dir in $(SUBDIRS); do \
		$(MAKE) -C $$dir $@ || exit $$?; \
	done

eval-validation: ## Validate eval JSONs, eval directories, and skill sources
	@uv run pytest $(EVAL_PYTEST_QUIET) $(EVAL_CAPTURE_FLAGS) $(EVAL_WORKER_FLAGS) $(EVAL_TARGET) $(EVAL_PROMPT_FILTER) $(EVAL_VALIDATION_FLAGS) $(EVAL_PROGRESS_FLAG)

eval-with-skill: ## Run Codex with the skill loaded, then grade deterministic and qualitative checks
	@uv run pytest $(EVAL_CAPTURE_FLAGS) $(EVAL_WORKER_FLAGS) $(EVAL_TARGET) $(EVAL_PROMPT_FILTER) $(EVAL_FLAGS) $(EVAL_PROGRESS_FLAG)

eval-with-baseline: ## Run Codex baseline with no skill loaded, then grade baseline checks
	@uv run pytest $(EVAL_CAPTURE_FLAGS) $(EVAL_WORKER_FLAGS) $(EVAL_TARGET) $(EVAL_PROMPT_FILTER) $(EVAL_BASELINE_FLAGS) $(EVAL_PROGRESS_FLAG)

eval-ab: ## Run Codex with_skill and with_baseline sides in one A/B comparison
	@uv run pytest $(EVAL_CAPTURE_FLAGS) $(EVAL_WORKER_FLAGS) $(EVAL_TARGET) $(EVAL_PROMPT_FILTER) $(EVAL_AB_FLAGS) $(EVAL_PROGRESS_FLAG)

skill-eval: eval-with-skill ## Alias for eval-with-skill

skill-eval-all: eval-with-skill ## Alias for eval-with-skill

skill-eval-list: ## List discovered Codex skill evals
	@uv run pytest $(EVAL_TARGET) $(EVAL_PROMPT_FILTER) --collect-only -q $(EVAL_LIST_FLAGS)

skill-eval-ab: eval-ab ## Alias for eval-ab

skill-eval-ab-all: eval-ab ## Alias for eval-ab

test-eval-harness: ## Run fast unit tests for the Codex eval harness
	@uv run pytest . --codex-eval-config "$(EVAL_VALIDATION_CONFIG)"

eval-all: ## Run validation and A/B modes
	@printf "== Eval validation ==\n"
	@$(MAKE) eval-validation EVAL_QUIET=1
	@printf "validation passed\n"
	@printf "\n== Live Codex A/B ==\n"
	@$(MAKE) eval-ab

test-all: eval-all ## Alias for eval-all
