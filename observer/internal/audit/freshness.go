package audit

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"time"
)

// generatedDirs are directories whose contents are produced by tooling rather
// than authored, so a write inside them says nothing about whether the audited
// source has changed. ".observe" is the important one: the audit writes its own
// artifacts there, which would otherwise make every audit instantly stale.
var generatedDirs = map[string]bool{
	".git":          true,
	".mypy_cache":   true,
	".observe":      true,
	".pytest_cache": true,
	".ruff_cache":   true,
	".tox":          true,
	".venv":         true,
	".vscode-test":  true,
	"__pycache__":   true,
	"build":         true,
	"coverage":      true,
	"dist":          true,
	"node_modules":  true,
	"target":        true,
	"vendor":        true,
	"venv":          true,
}

// maxFreshnessEntries bounds the walk so a very large workspace cannot make a
// score request expensive. Hitting the cap answers "not changed": an
// indeterminate result must never be presented as staleness.
const maxFreshnessEntries = 50000

// errWalkBudget ends the walk when the entry budget is exhausted.
var errWalkBudget = errors.New("audit: freshness walk budget exhausted")

// sourceChangedAfter reports whether any authored file in the workspace was
// modified after the given time.
//
// This is what catches the audit-then-instrument flow: `$otel-instrument` edits
// source files without committing, so HEAD does not move and a commit
// comparison alone still calls the stale pre-instrumentation score current.
// Comparing against the audit artifact's own modification time needs nothing
// recorded in the artifact, so it works with audits written by any version of
// the skill.
//
// Every failure answers false. A missing or unreadable workspace is unknown,
// and unknown must not be reported as stale.
func sourceChangedAfter(root string, auditModTime time.Time) bool {
	if root == "" || auditModTime.IsZero() {
		return false
	}

	if info, err := os.Stat(root); err != nil || !info.IsDir() {
		return false
	}

	entries := 0
	changed := false

	// WalkDir reports symlinks without following them, so the walk cannot leave
	// the workspace and no planted link can inject a foreign mtime. It is used
	// in preference to a root-scoped fs.FS because that re-resolves every path
	// component per entry, which costs more than the whole walk is worth. No
	// file content is read here — only directory entries and their mtimes.
	err := filepath.WalkDir(root, func(name string, entry fs.DirEntry, err error) error {
		if err != nil {
			// An unreadable subtree is skipped rather than failing the walk: a
			// permission error in one directory should not suppress a
			// modification found elsewhere.
			if entry != nil && entry.IsDir() {
				return fs.SkipDir
			}

			return nil
		}

		entries++
		if entries > maxFreshnessEntries {
			return errWalkBudget
		}

		if entry.IsDir() {
			if name != root && generatedDirs[filepath.Base(name)] {
				return fs.SkipDir
			}

			return nil
		}
		// Symlinks and devices are not authored content whose mtime we can
		// trust, and following them could leave the workspace.
		if !entry.Type().IsRegular() {
			return nil
		}

		info, err := entry.Info()
		if err != nil {
			return nil
		}
		if info.ModTime().After(auditModTime) {
			changed = true

			// Stop at the first hit: the answer cannot change after this.
			return fs.SkipAll
		}

		return nil
	})
	if err != nil {
		// Budget exhausted or the walk failed outright: unknown, not stale.
		return false
	}

	return changed
}
