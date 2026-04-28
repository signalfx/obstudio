SUBDIRS := $(sort $(dir $(wildcard */*/Makefile */*/makefile)))
ROOT_DIR := $(abspath ..)

SKILL ?=
CASE ?=
PROMPT ?=
MODEL ?=
NO_QUALITATIVE ?=
EVAL_RUNTIME ?=
EVAL_WORKERS ?= 1
EVAL_PROGRESS ?= 1
EVAL_PATTERN ?=
AB ?=
WITH ?=
EVAL_CONFIG ?= codex-evals.toml
EVAL_VALIDATION_CONFIG ?= codex-evals.validation.toml
EVAL_BASELINE_CONFIG ?= codex-evals.baseline.toml
EVAL_AB_CONFIG ?= codex-evals.ab.toml
SANITY_PATTERN ?= */*/eval/sanity
QUALITATIVE_PATTERN ?= */*/eval/qual
RUNTIME_PATTERN ?= */*/eval/runtime

kind_target = $(if $(EVAL_PATTERN),$(EVAL_PATTERN),$(if $(CASE),$(if $(findstring /eval/,$(CASE)),$(CASE),$(CASE)/eval/$(1)),$(2)))

EVAL_TARGET = $(if $(CASE),$(CASE),$(if $(EVAL_PATTERN),$(EVAL_PATTERN),.))
EVAL_PROMPT_FILTER = $(if $(PROMPT),-k "$(PROMPT)",)
EVAL_SANITY_TARGET = $(call kind_target,sanity,$(SANITY_PATTERN))
EVAL_QUALITATIVE_TARGET = $(call kind_target,qual,$(QUALITATIVE_PATTERN))
EVAL_RUNTIME_TARGET = $(call kind_target,runtime,$(RUNTIME_PATTERN))
EVAL_SANITY_FILTER = $(if $(PROMPT),-k "$(PROMPT)",)
EVAL_QUALITATIVE_FILTER = $(if $(PROMPT),-k "$(PROMPT)",)
EVAL_RUNTIME_FILTER = $(if $(PROMPT),-k "$(PROMPT)",)
EVAL_QUIET ?=
EVAL_PYTEST_QUIET = $(if $(EVAL_QUIET),-qq,)
EVAL_SKILL_PATH = $(if $(SKILL),$(if $(filter /%,$(SKILL)),$(SKILL),$(if $(wildcard $(SKILL)/SKILL.md),$(abspath $(SKILL)),$(abspath $(ROOT_DIR)/$(SKILL)))))
EVAL_SKILL_FLAG = $(if $(SKILL),--skill "$(EVAL_SKILL_PATH)",)
EVAL_WORKER_FLAGS = $(if $(filter 1,$(strip $(EVAL_WORKERS))),,-n $(EVAL_WORKERS))
EVAL_PROGRESS_FLAG = $(if $(filter 1 true yes,$(strip $(EVAL_PROGRESS))),--codex-eval-progress,)
EVAL_CAPTURE_FLAGS = $(if $(filter 1 true yes,$(strip $(EVAL_PROGRESS))),-s,)
EVAL_RUNTIME_FLAG = $(if $(filter 1 true yes,$(strip $(EVAL_RUNTIME))),--codex-runtime,)
EVAL_AB_FLAG = $(if $(filter 1 true yes ab,$(strip $(AB) $(WITH))),--ab,)
EVAL_FLAGS = $(EVAL_SKILL_FLAG) --codex-eval-config "$(EVAL_CONFIG)" $(if $(MODEL),--model "$(MODEL)",) $(if $(NO_QUALITATIVE),--no-qualitative,) $(EVAL_RUNTIME_FLAG)
EVAL_KIND_FLAGS = $(EVAL_SKILL_FLAG) --codex-eval-config "$(EVAL_CONFIG)" $(if $(MODEL),--model "$(MODEL)",) $(if $(NO_QUALITATIVE),--no-qualitative,) $(EVAL_RUNTIME_FLAG) $(EVAL_AB_FLAG)
EVAL_VALIDATION_FLAGS = $(EVAL_SKILL_FLAG) --codex-eval-config "$(EVAL_VALIDATION_CONFIG)"
EVAL_BASELINE_FLAGS = $(EVAL_SKILL_FLAG) --codex-eval-config "$(EVAL_BASELINE_CONFIG)" $(if $(MODEL),--model "$(MODEL)",) $(if $(NO_QUALITATIVE),--no-qualitative,) $(EVAL_RUNTIME_FLAG)
EVAL_AB_FLAGS = $(EVAL_SKILL_FLAG) --codex-eval-config "$(EVAL_AB_CONFIG)" $(if $(MODEL),--model "$(MODEL)",) $(if $(NO_QUALITATIVE),--no-qualitative,) $(EVAL_RUNTIME_FLAG)
EVAL_LIST_FLAGS = $(EVAL_FLAGS)

.PHONY: build test eval-validation eval-sanity eval-sanity-ab eval-qualitative eval-qualitative-ab eval-runtime eval-runtime-ab eval-with-skill eval-with-baseline eval-ab eval-all eval-all-ab skill-eval skill-eval-all skill-eval-list skill-eval-ab skill-eval-ab-all test-eval-harness test-all

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

eval-sanity: ## Run quick loaded-skill sanity checks; pass AB=1 or WITH=ab to include baseline
	@uv run pytest $(EVAL_CAPTURE_FLAGS) $(EVAL_WORKER_FLAGS) $(EVAL_SANITY_TARGET) $(EVAL_SANITY_FILTER) $(EVAL_KIND_FLAGS) --codex-eval-kind sanity $(EVAL_PROGRESS_FLAG)

eval-sanity-ab: AB=1
eval-sanity-ab: eval-sanity ## Run sanity checks with baseline

eval-qualitative: ## Run schema-constrained qualitative grading; pass AB=1 or WITH=ab to include baseline
	@uv run pytest $(EVAL_CAPTURE_FLAGS) $(EVAL_WORKER_FLAGS) $(EVAL_QUALITATIVE_TARGET) $(EVAL_QUALITATIVE_FILTER) $(EVAL_KIND_FLAGS) --codex-eval-kind qualitative $(EVAL_PROGRESS_FLAG)

eval-qualitative-ab: AB=1
eval-qualitative-ab: eval-qualitative ## Run qualitative grading with baseline

eval-runtime: ## Run Docker/Observer runtime checks; pass AB=1 or WITH=ab to include baseline
	@uv run pytest $(EVAL_CAPTURE_FLAGS) $(EVAL_WORKER_FLAGS) $(EVAL_RUNTIME_TARGET) $(EVAL_RUNTIME_FILTER) $(EVAL_KIND_FLAGS) --codex-eval-kind runtime $(EVAL_PROGRESS_FLAG)

eval-runtime-ab: AB=1
eval-runtime-ab: eval-runtime ## Run runtime checks with baseline

skill-eval: eval-with-skill ## Alias for eval-with-skill

skill-eval-all: eval-with-skill ## Alias for eval-with-skill

skill-eval-list: ## List discovered Codex skill evals
	@uv run pytest $(EVAL_TARGET) $(EVAL_PROMPT_FILTER) --collect-only -q $(EVAL_LIST_FLAGS)

skill-eval-ab: eval-ab ## Alias for eval-ab

skill-eval-ab-all: eval-ab ## Alias for eval-ab

test-eval-harness: ## Run fast unit tests for the Codex eval harness
	@uv run pytest . --codex-eval-config "$(EVAL_VALIDATION_CONFIG)"

eval-all: eval-validation eval-sanity eval-qualitative eval-runtime ## Run validation, sanity, qualitative, and runtime evals

eval-all-ab: AB=1
eval-all-ab: eval-all ## Run validation plus A/B sanity, qualitative, and runtime evals

test-all: eval-all ## Alias for eval-all
