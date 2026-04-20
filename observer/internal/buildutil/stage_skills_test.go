package buildutil

import (
	"os"
	"path/filepath"
	"testing"
)

func TestStageEmbeddedSkills(t *testing.T) {
	repoRoot := t.TempDir()
	observerRoot := filepath.Join(repoRoot, "observer")

	skillFile := filepath.Join(repoRoot, "skills", "observe", "SKILL.md")
	if err := os.MkdirAll(filepath.Dir(skillFile), 0o755); err != nil {
		t.Fatalf("mkdir skills: %v", err)
	}
	if err := os.WriteFile(skillFile, []byte("observe skill"), 0o644); err != nil {
		t.Fatalf("write skill: %v", err)
	}

	examplesFile := filepath.Join(repoRoot, "docs", "examples.md")
	if err := os.MkdirAll(filepath.Dir(examplesFile), 0o755); err != nil {
		t.Fatalf("mkdir docs: %v", err)
	}
	if err := os.WriteFile(examplesFile, []byte("examples"), 0o644); err != nil {
		t.Fatalf("write examples: %v", err)
	}

	staleFile := filepath.Join(observerRoot, "cmd", "obstudio", "_skills", "stale.txt")
	if err := os.MkdirAll(filepath.Dir(staleFile), 0o755); err != nil {
		t.Fatalf("mkdir stale dir: %v", err)
	}
	if err := os.WriteFile(staleFile, []byte("stale"), 0o644); err != nil {
		t.Fatalf("write stale file: %v", err)
	}

	if err := StageEmbeddedSkills(repoRoot, observerRoot); err != nil {
		t.Fatalf("StageEmbeddedSkills failed: %v", err)
	}

	if _, err := os.Stat(filepath.Join(observerRoot, "cmd", "obstudio", "_skills", "observe", "SKILL.md")); err != nil {
		t.Fatalf("staged skill missing: %v", err)
	}
	if _, err := os.Stat(filepath.Join(observerRoot, "cmd", "obstudio", "_skills", "examples.md")); err != nil {
		t.Fatalf("staged examples missing: %v", err)
	}
	if _, err := os.Stat(staleFile); !os.IsNotExist(err) {
		t.Fatalf("stale file should have been removed, got err=%v", err)
	}
}

func TestStageEmbeddedSkills_ExcludesEvals(t *testing.T) {
	repoRoot := t.TempDir()
	observerRoot := filepath.Join(repoRoot, "observer")

	// Create a skill with an evals subdirectory.
	skillFile := filepath.Join(repoRoot, "skills", "audit", "SKILL.md")
	if err := os.MkdirAll(filepath.Dir(skillFile), 0o755); err != nil {
		t.Fatalf("mkdir skills: %v", err)
	}
	if err := os.WriteFile(skillFile, []byte("audit skill"), 0o644); err != nil {
		t.Fatalf("write skill: %v", err)
	}

	evalsFile := filepath.Join(repoRoot, "skills", "audit", "evals", "evals.json")
	if err := os.MkdirAll(filepath.Dir(evalsFile), 0o755); err != nil {
		t.Fatalf("mkdir evals: %v", err)
	}
	if err := os.WriteFile(evalsFile, []byte(`{"skill_name":"audit"}`), 0o644); err != nil {
		t.Fatalf("write evals: %v", err)
	}

	if err := StageEmbeddedSkills(repoRoot, observerRoot); err != nil {
		t.Fatalf("StageEmbeddedSkills failed: %v", err)
	}

	staged := filepath.Join(observerRoot, "cmd", "obstudio", "_skills")

	// SKILL.md should be staged.
	if _, err := os.Stat(filepath.Join(staged, "audit", "SKILL.md")); err != nil {
		t.Fatalf("staged skill missing: %v", err)
	}

	// evals/ directory should NOT be staged.
	evalsStaged := filepath.Join(staged, "audit", "evals")
	if _, err := os.Stat(evalsStaged); !os.IsNotExist(err) {
		t.Fatalf("evals directory should not be staged, got err=%v", err)
	}
}
