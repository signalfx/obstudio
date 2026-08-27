package audit

import (
	"os"
	"path/filepath"
	"strings"
)

// workspaceCommit returns the workspace's current HEAD commit, or "" when the
// workspace is not a git checkout or HEAD cannot be resolved.
//
// This is read directly from the .git directory rather than shelling out, so it
// works with no git binary present and cannot execute anything from the
// workspace. Every failure is treated as "unknown", never as an error: the
// commit is only used to decide whether to show a staleness hint.
func workspaceCommit(root string) string {
	if root == "" {
		return ""
	}

	gitDir, ok := resolveGitDir(root)
	if !ok {
		return ""
	}

	head, err := os.ReadFile(filepath.Join(gitDir, "HEAD"))
	if err != nil {
		return ""
	}
	line := strings.TrimSpace(string(head))

	// Detached HEAD stores the object id directly.
	if !strings.HasPrefix(line, "ref:") {
		return sanitizeCommit(line)
	}

	ref := strings.TrimSpace(strings.TrimPrefix(line, "ref:"))
	if ref == "" || strings.Contains(ref, "..") {
		return ""
	}

	if raw, err := os.ReadFile(filepath.Join(gitDir, filepath.FromSlash(ref))); err == nil {
		return sanitizeCommit(strings.TrimSpace(string(raw)))
	}

	return sanitizeCommit(lookupPackedRef(gitDir, ref))
}

// resolveGitDir handles both a normal .git directory and the "gitdir: <path>"
// file form used by worktrees and submodules.
func resolveGitDir(root string) (string, bool) {
	path := filepath.Join(root, ".git")

	info, err := os.Stat(path)
	if err != nil {
		return "", false
	}
	if info.IsDir() {
		return path, true
	}

	raw, err := os.ReadFile(path)
	if err != nil {
		return "", false
	}
	target := strings.TrimSpace(strings.TrimPrefix(strings.TrimSpace(string(raw)), "gitdir:"))
	if target == "" {
		return "", false
	}
	if !filepath.IsAbs(target) {
		target = filepath.Join(root, target)
	}

	return target, true
}

// lookupPackedRef finds a ref in packed-refs, used when the loose ref file has
// been packed away.
func lookupPackedRef(gitDir, ref string) string {
	raw, err := os.ReadFile(filepath.Join(gitDir, "packed-refs"))
	if err != nil {
		return ""
	}
	for _, line := range strings.Split(string(raw), "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") || strings.HasPrefix(line, "^") {
			continue
		}
		sha, name, found := strings.Cut(line, " ")
		if found && strings.TrimSpace(name) == ref {
			return sha
		}
	}

	return ""
}

// sanitizeCommit keeps only a plausible hex object id, so nothing unexpected
// from the filesystem reaches the API response.
func sanitizeCommit(value string) string {
	value = strings.TrimSpace(value)
	if len(value) < 7 || len(value) > 64 {
		return ""
	}
	for _, r := range value {
		if (r < '0' || r > '9') && (r < 'a' || r > 'f') && (r < 'A' || r > 'F') {
			return ""
		}
	}

	return strings.ToLower(value)
}

// commitsDiffer reports whether two commit ids are known to be different.
//
// Audits record a short id ("abc1234") while HEAD is full length, so a prefix
// match on either side counts as the same commit. When either side is unknown
// the answer is false: an unknown commit must never be reported as stale.
func commitsDiffer(auditCommit, workspaceCommit string) bool {
	a := sanitizeCommit(auditCommit)
	b := sanitizeCommit(workspaceCommit)
	if a == "" || b == "" {
		return false
	}

	return !strings.HasPrefix(a, b) && !strings.HasPrefix(b, a)
}
