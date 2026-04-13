# Keep the root Makefile as the single source of truth for build logic.
ROOT_DIR := ..

.DEFAULT_GOAL := help

.PHONY: help

help:
	@$(MAKE) -C $(ROOT_DIR) help

%:
	@$(MAKE) -C $(ROOT_DIR) $@
