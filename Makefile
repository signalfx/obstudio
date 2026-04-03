BUILD_DIR   := build
SKILLS_SRC  := skills
SKILLS_DIST := $(BUILD_DIR)/skills

.PHONY: help package-skills clean list-skills

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  %-20s %s\n", $$1, $$2}'

package-skills: ## Package skills into build/skills/ for distribution
	@rm -rf "$(SKILLS_DIST)"
	@mkdir -p "$(SKILLS_DIST)"
	@find "$(SKILLS_SRC)" -name SKILL.md | while read skillfile; do \
		skill_dir=$$(dirname "$$skillfile"); \
		rel=$${skill_dir#$(SKILLS_SRC)/}; \
		dest="$(SKILLS_DIST)/$$rel"; \
		mkdir -p "$$dest"; \
		cp -R "$$skill_dir/" "$$dest/"; \
		name=$$(head -5 "$$skillfile" | grep '^name:' | sed 's/^name:[[:space:]]*//'); \
		echo "OK    $$name -> $$dest"; \
	done
	@echo ""
	@echo "Packaged skills to $(SKILLS_DIST)/"
	@echo "Install via: obstudio register --agent <cursor|claude-code|codex>"

clean: ## Remove build artifacts
	rm -rf "$(BUILD_DIR)"

list-skills: ## List available skills in this repo
	@echo "Available skills:"
	@find "$(SKILLS_SRC)" -name SKILL.md | sort | while read skillfile; do \
		name=$$(head -5 "$$skillfile" | grep '^name:' | sed 's/^name:[[:space:]]*//'); \
		desc=$$(awk '/^description:/{found=1; sub(/^description:[[:space:]]*>*-*[[:space:]]*/,""); if(length>0) print; next} found && /^[[:space:]]/{sub(/^[[:space:]]*/,""); print; next} found{exit}' "$$skillfile" | tr '\n' ' '); \
		printf "  %-20s %s\n" "$$name" "$$desc"; \
	done
