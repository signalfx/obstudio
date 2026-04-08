package buildutil

import (
	"os"
	"path/filepath"
	"testing"
)

func TestStageEmbeddedSkills(t *testing.T) {
	repoRoot := t.TempDir()
	observerGoRoot := filepath.Join(repoRoot, "observer-go")

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

	staleFile := filepath.Join(observerGoRoot, "cmd", "obstudio", "_skills", "stale.txt")
	if err := os.MkdirAll(filepath.Dir(staleFile), 0o755); err != nil {
		t.Fatalf("mkdir stale dir: %v", err)
	}
	if err := os.WriteFile(staleFile, []byte("stale"), 0o644); err != nil {
		t.Fatalf("write stale file: %v", err)
	}

	if err := StageEmbeddedSkills(repoRoot, observerGoRoot); err != nil {
		t.Fatalf("StageEmbeddedSkills failed: %v", err)
	}

	if _, err := os.Stat(filepath.Join(observerGoRoot, "cmd", "obstudio", "_skills", "observe", "SKILL.md")); err != nil {
		t.Fatalf("staged skill missing: %v", err)
	}
	if _, err := os.Stat(filepath.Join(observerGoRoot, "cmd", "obstudio", "_skills", "examples.md")); err != nil {
		t.Fatalf("staged examples missing: %v", err)
	}
	if _, err := os.Stat(staleFile); !os.IsNotExist(err) {
		t.Fatalf("stale file should have been removed, got err=%v", err)
	}
}
