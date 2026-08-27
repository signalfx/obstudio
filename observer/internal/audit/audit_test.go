package audit

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// writeAudit writes a canonical audit artifact into a temp workspace and
// returns the workspace root.
func writeAudit(t *testing.T, body string) string {
	t.Helper()

	root := t.TempDir()
	if err := os.MkdirAll(filepath.Join(root, ".observe"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, ".observe", "otel-audit.json"), []byte(body), 0o600); err != nil {
		t.Fatal(err)
	}

	return root
}

// coveredAudit is a service with all three signals and every readiness area
// covered, and no outstanding work.
const coveredAudit = `{
  "schema_version": 2,
  "kind": "otel-audit",
  "meta": {
    "service_name": "checkout",
    "language": "go",
    "framework": "chi",
    "date": "2026-08-27",
    "status": "Pass"
  },
  "current_instrumentation": {
    "spans": [{"name": "GET /health", "source": "otelhttp", "type": "auto"}],
    "metrics": [{"name": "http.server.request.duration", "source": "otelhttp", "type": "auto"}],
    "logs": [{"integration": "slog bridge", "source": "otel_setup.go"}],
    "incident_readiness": [
      {"area": "HTTP latency", "status": "covered"},
      {"area": "Error rate", "status": "covered"}
    ]
  },
  "findings": [],
  "anti_patterns": [],
  "recommendation": ["Instrumentation looks complete."]
}`

// uninstrumentedAudit is a service with no signals and unresolved findings.
const uninstrumentedAudit = `{
  "schema_version": 2,
  "kind": "otel-audit",
  "meta": {"service_name": "checkout", "language": "python", "framework": "fastapi", "status": "Partial"},
  "current_instrumentation": {
    "spans": [],
    "metrics": [],
    "logs": [],
    "incident_readiness": [
      {"area": "HTTP latency", "status": "missing"},
      {"area": "Error rate", "status": "missing"}
    ]
  },
  "findings": [
    {"id": "OTEL-001", "title": "HTTP latency lacks route-level proof", "severity": "high", "status": "proposed"},
    {"id": "OTEL-002", "title": "No error signal", "severity": "critical", "status": "proposed"}
  ],
  "anti_patterns": ["OTEL_SERVICE_NAME set with no SDK"],
  "recommendation": ["Run $otel-instrument."]
}`

func TestScoreCoveredAudit(t *testing.T) {
	got := NewResolver(Config{WorkspaceRoot: writeAudit(t, coveredAudit)}).Build()

	if !got.Available {
		t.Fatalf("Available = false: %s", got.Message)
	}
	if got.ServiceName != "checkout" || got.Language != "go" || got.Framework != "chi" {
		t.Errorf("meta = %q/%q/%q", got.ServiceName, got.Language, got.Framework)
	}
	if got.Status != "Pass" {
		t.Errorf("Status = %q, want Pass", got.Status)
	}
	if !got.HasSpans || !got.HasMetrics || !got.HasLogs {
		t.Errorf("signals = %v/%v/%v, want all true", got.HasSpans, got.HasMetrics, got.HasLogs)
	}
	// Everything earned: 15+15+15 signals, 25 readiness, 20 findings, 10 anti-patterns.
	if got.Score != 100 {
		t.Errorf("Score = %d, want 100", got.Score)
	}
}

func TestScoreUninstrumentedAudit(t *testing.T) {
	got := NewResolver(Config{WorkspaceRoot: writeAudit(t, uninstrumentedAudit)}).Build()

	if got.GapCount != 2 {
		t.Errorf("GapCount = %d, want 2", got.GapCount)
	}
	if got.AntiPatternCount != 1 {
		t.Errorf("AntiPatternCount = %d, want 1", got.AntiPatternCount)
	}
	// Signals 0, readiness 0, findings max(0, 20-(5+8))=7, anti-patterns 10-5=5.
	// 12 of 100 possible => 12.
	if got.Score != 12 {
		t.Errorf("Score = %d, want 12", got.Score)
	}
	if len(got.Gaps) != 2 || !strings.HasPrefix(got.Gaps[0], "OTEL-001 — ") {
		t.Errorf("Gaps = %q, want id-prefixed titles", got.Gaps)
	}
}

// Findings that are done, rejected, or deferred are not outstanding work and
// must not be counted or penalized.
func TestResolvedFindingsAreNotCounted(t *testing.T) {
	body := strings.Replace(uninstrumentedAudit, `"status": "proposed"}`, `"status": "done"}`, 1)
	got := NewResolver(Config{WorkspaceRoot: writeAudit(t, body)}).Build()

	if got.GapCount != 1 {
		t.Errorf("GapCount = %d, want 1 (the done finding is not outstanding)", got.GapCount)
	}
}

// A report with no readiness section must not be capped below 100; the
// component is dropped from the maximum instead.
func TestReadinessSectionIsOptional(t *testing.T) {
	body := strings.Replace(coveredAudit, `"incident_readiness": [
      {"area": "HTTP latency", "status": "covered"},
      {"area": "Error rate", "status": "covered"}
    ]`, `"incident_readiness": []`, 1)

	got := NewResolver(Config{WorkspaceRoot: writeAudit(t, body)}).Build()

	if got.Score != 100 {
		t.Errorf("Score = %d, want 100 when no readiness areas are claimed", got.Score)
	}
	for _, c := range got.Breakdown.Components {
		if c.Label == "Incident readiness" {
			t.Error("readiness component should be omitted when the audit lists no areas")
		}
	}
}

func TestPartialReadinessScoresHalf(t *testing.T) {
	body := strings.Replace(coveredAudit, `{"area": "Error rate", "status": "covered"}`,
		`{"area": "Error rate", "status": "partial"}`, 1)

	got := NewResolver(Config{WorkspaceRoot: writeAudit(t, body)}).Build()

	// Readiness earns 25 * 0.75 = 18.75; total 93.75 of 100 => 94.
	if got.Score != 94 {
		t.Errorf("Score = %d, want 94", got.Score)
	}
}

func TestScoreIsBounded(t *testing.T) {
	body := strings.Replace(uninstrumentedAudit, `"anti_patterns": ["OTEL_SERVICE_NAME set with no SDK"]`,
		`"anti_patterns": ["a","b","c","d","e","f","g","h"]`, 1)

	got := NewResolver(Config{WorkspaceRoot: writeAudit(t, body)}).Build()

	if got.Score < 0 || got.Score > 100 {
		t.Errorf("Score = %d, want within [0,100]", got.Score)
	}
}

func TestMissingReport(t *testing.T) {
	got := NewResolver(Config{WorkspaceRoot: t.TempDir()}).Build()

	if got.Available {
		t.Error("Available = true, want false")
	}
	if !strings.Contains(got.Message, "$otel-audit") {
		t.Errorf("Message = %q, want it to name $otel-audit", got.Message)
	}
	if !strings.Contains(got.Message, "otel-audit.json") {
		t.Errorf("Message = %q, want it to name the canonical artifact", got.Message)
	}
	if filepath.IsAbs(got.Source) || strings.Contains(got.Message, os.TempDir()) {
		t.Errorf("leaked a filesystem path: %q / %q", got.Source, got.Message)
	}
}

func TestRejectsNonAuditJSON(t *testing.T) {
	got := NewResolver(Config{WorkspaceRoot: writeAudit(t, `{"kind":"something-else"}`)}).Build()

	if got.Available {
		t.Error("Available = true for a non-audit document")
	}
}

func TestRejectsNewerSchema(t *testing.T) {
	got := NewResolver(Config{WorkspaceRoot: writeAudit(t, `{"schema_version": 99, "kind": "otel-audit"}`)}).Build()

	if got.Available {
		t.Error("Available = true for an unsupported schema version")
	}
	if !strings.Contains(got.Message, "schema_version") {
		t.Errorf("Message = %q, want it to name the schema mismatch", got.Message)
	}
}

func TestAcceptsSchemaVersionOne(t *testing.T) {
	body := strings.Replace(coveredAudit, `"schema_version": 2`, `"schema_version": 1`, 1)

	if got := NewResolver(Config{WorkspaceRoot: writeAudit(t, body)}).Build(); !got.Available {
		t.Errorf("schema v1 rejected: %s", got.Message)
	}
}

func TestMalformedJSON(t *testing.T) {
	got := NewResolver(Config{WorkspaceRoot: writeAudit(t, "{not json")}).Build()

	if got.Available {
		t.Error("Available = true for malformed JSON")
	}
}

// Regression: a symlinked artifact must not be read, even when the path string
// itself looks contained. os.ReadFile follows symlinks, so the resolved target
// has to be re-checked against the workspace.
func TestSymlinkedReportIsRefused(t *testing.T) {
	root := t.TempDir()
	outside := filepath.Join(t.TempDir(), "outside.json")
	if err := os.WriteFile(outside, []byte(coveredAudit), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(root, ".observe"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(outside, filepath.Join(root, ".observe", "otel-audit.json")); err != nil {
		t.Skipf("symlinks unavailable: %v", err)
	}

	r := NewResolver(Config{WorkspaceRoot: root})

	if _, err := r.readContained(r.reportPath); !errors.Is(err, ErrNoReport) {
		t.Errorf("readContained err = %v, want ErrNoReport for a symlink escaping the workspace", err)
	}
	if got := r.Build(); got.Available {
		t.Error("Build served a symlinked file from outside the workspace")
	}
}

// A relative symlink that stays inside the workspace is legitimate and resolves.
func TestRelativeSymlinkInsideWorkspaceIsAllowed(t *testing.T) {
	root := t.TempDir()
	if err := os.MkdirAll(filepath.Join(root, ".observe"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "real-audit.json"), []byte(coveredAudit), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(filepath.Join("..", "real-audit.json"), filepath.Join(root, ".observe", "otel-audit.json")); err != nil {
		t.Skipf("symlinks unavailable: %v", err)
	}

	if got := NewResolver(Config{WorkspaceRoot: root}).Build(); !got.Available {
		t.Errorf("relative in-workspace symlink refused: %s", got.Message)
	}
}

// Root-scoped opens refuse an absolute symlink target even when it points back
// inside the workspace: the kernel cannot honour it within the root scope. This
// fails closed, which is the intended trade-off for the containment guarantee.
func TestAbsoluteSymlinkIsRefused(t *testing.T) {
	root := t.TempDir()
	if err := os.MkdirAll(filepath.Join(root, ".observe"), 0o755); err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(root, "real-audit.json")
	if err := os.WriteFile(target, []byte(coveredAudit), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(target, filepath.Join(root, ".observe", "otel-audit.json")); err != nil {
		t.Skipf("symlinks unavailable: %v", err)
	}

	if got := NewResolver(Config{WorkspaceRoot: root}).Build(); got.Available {
		t.Error("an absolute symlink target was followed; expected it to fail closed")
	}
}

// A directory in place of the artifact must be refused rather than read.
func TestNonRegularFileIsRefused(t *testing.T) {
	root := t.TempDir()
	if err := os.MkdirAll(filepath.Join(root, ".observe", "otel-audit.json"), 0o755); err != nil {
		t.Fatal(err)
	}

	if got := NewResolver(Config{WorkspaceRoot: root}).Build(); got.Available {
		t.Error("Available = true for a directory in place of the report")
	}
}

func TestResolverRejectsPathTraversal(t *testing.T) {
	root := t.TempDir()
	r := NewResolver(Config{WorkspaceRoot: root, ReportPath: "../../etc/passwd"})

	if want := filepath.Join(root, DefaultReportRelPath); r.reportPath != want {
		t.Errorf("reportPath = %q, want fallback %q", r.reportPath, want)
	}
}

func TestResolverRejectsAbsolutePathOutsideWorkspace(t *testing.T) {
	root := t.TempDir()
	r := NewResolver(Config{WorkspaceRoot: root, ReportPath: filepath.Join(t.TempDir(), "elsewhere.json")})

	if want := filepath.Join(root, DefaultReportRelPath); r.reportPath != want {
		t.Errorf("reportPath = %q, want fallback %q", r.reportPath, want)
	}
}

// The HTML report is the skill's own artifact; the score reports whether it is
// there so the UI only links to it when it exists.
func TestHTMLReportDetection(t *testing.T) {
	root := writeAudit(t, coveredAudit)

	if got := NewResolver(Config{WorkspaceRoot: root}).Build(); got.HasHTMLReport {
		t.Error("HasHTMLReport = true before otel.html exists")
	}

	if err := os.WriteFile(filepath.Join(root, ".observe", "otel.html"), []byte("<h1>report</h1>"), 0o600); err != nil {
		t.Fatal(err)
	}

	r := NewResolver(Config{WorkspaceRoot: root})
	if got := r.Build(); !got.HasHTMLReport {
		t.Error("HasHTMLReport = false after otel.html exists")
	}
	raw, err := r.ReadHTML()
	if err != nil || string(raw) != "<h1>report</h1>" {
		t.Errorf("ReadHTML = %q, %v", raw, err)
	}
}

// A nil slice would marshal to null and break clients that iterate the field.
func TestFindingSlicesMarshalAsArrays(t *testing.T) {
	got := NewResolver(Config{WorkspaceRoot: writeAudit(t, coveredAudit)}).Build()

	raw, err := json.Marshal(got)
	if err != nil {
		t.Fatal(err)
	}
	body := string(raw)

	for _, field := range []string{`"gaps":null`, `"antiPatterns":null`, `"recommendations":null`} {
		if strings.Contains(body, field) {
			t.Errorf("JSON contains %s; want an empty array instead", field)
		}
	}
}

// Anti-patterns may arrive as plain strings or as objects; both must render.
func TestAntiPatternObjectsAreRendered(t *testing.T) {
	body := strings.Replace(coveredAudit, `"anti_patterns": []`,
		`"anti_patterns": [{"title": "Hot-path tracer"}, "Hardcoded endpoint"]`, 1)

	got := NewResolver(Config{WorkspaceRoot: writeAudit(t, body)}).Build()

	if len(got.AntiPatterns) != 2 || got.AntiPatterns[0] != "Hot-path tracer" {
		t.Errorf("AntiPatterns = %q", got.AntiPatterns)
	}
}

// Syntactically valid JSON is not enough: a truncated or hand-edited artifact
// must be reported as unusable rather than scored as if it were complete.
func TestRejectsStructurallyIncompleteAudit(t *testing.T) {
	cases := map[string]string{
		"only schema and kind": `{"schema_version":2,"kind":"otel-audit"}`,
		"missing service_name": `{"schema_version":2,"kind":"otel-audit","meta":{"status":"Partial"}}`,
		"missing status":       `{"schema_version":2,"kind":"otel-audit","meta":{"service_name":"checkout"}}`,
		"bogus status":         `{"schema_version":2,"kind":"otel-audit","meta":{"service_name":"checkout","status":"Great"}}`,
		"missing kind":         `{"schema_version":2,"meta":{"service_name":"checkout","status":"Partial"}}`,
		"missing schema":       `{"kind":"otel-audit","meta":{"service_name":"checkout","status":"Partial"}}`,
	}

	for name, body := range cases {
		t.Run(name, func(t *testing.T) {
			got := NewResolver(Config{WorkspaceRoot: writeAudit(t, body)}).Build()

			if got.Available {
				t.Errorf("Available = true with score %d; want the report refused as unusable", got.Score)
			}
			if !strings.Contains(got.Message, "$otel-audit") {
				t.Errorf("Message = %q, want it to point at $otel-audit", got.Message)
			}
		})
	}
}

// The HTML report must be the sibling of whichever audit is actually scored,
// so an override cannot score one audit while serving another's report.
func TestHTMLReportPairsWithOverriddenAudit(t *testing.T) {
	root := t.TempDir()
	nested := filepath.Join(root, "svc", ".observe")
	if err := os.MkdirAll(nested, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(nested, "otel-audit.json"), []byte(coveredAudit), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(nested, "otel.html"), []byte("<h1>nested</h1>"), 0o600); err != nil {
		t.Fatal(err)
	}
	// A stale report at the default location must not be served instead.
	if err := os.MkdirAll(filepath.Join(root, ".observe"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, ".observe", "otel.html"), []byte("<h1>stale</h1>"), 0o600); err != nil {
		t.Fatal(err)
	}

	r := NewResolver(Config{WorkspaceRoot: root, ReportPath: filepath.Join("svc", ".observe", "otel-audit.json")})

	raw, err := r.ReadHTML()
	if err != nil {
		t.Fatalf("ReadHTML: %v", err)
	}
	if string(raw) != "<h1>nested</h1>" {
		t.Errorf("ReadHTML = %q, want the report paired with the scored audit", raw)
	}
}

// A file swapped for a symlink after validation must not be readable.
func TestSymlinkPlantedAfterResolutionIsRefused(t *testing.T) {
	root := t.TempDir()
	outside := filepath.Join(t.TempDir(), "outside.json")
	if err := os.WriteFile(outside, []byte(coveredAudit), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(root, ".observe"), 0o755); err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(root, ".observe", "otel-audit.json")
	if err := os.WriteFile(target, []byte(coveredAudit), 0o600); err != nil {
		t.Fatal(err)
	}

	r := NewResolver(Config{WorkspaceRoot: root})
	if got := r.Build(); !got.Available {
		t.Fatalf("baseline audit not readable: %s", got.Message)
	}

	// Swap the validated regular file for a symlink pointing outside.
	if err := os.Remove(target); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(outside, target); err != nil {
		t.Skipf("symlinks unavailable: %v", err)
	}

	if got := r.Build(); got.Available {
		t.Error("Build read a symlink planted in place of the validated file")
	}
}

// --- staleness -------------------------------------------------------------

func initGitRepo(t *testing.T, root, headSHA string) {
	t.Helper()

	gitDir := filepath.Join(root, ".git", "refs", "heads")
	if err := os.MkdirAll(gitDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, ".git", "HEAD"), []byte("ref: refs/heads/main\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(gitDir, "main"), []byte(headSHA+"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
}

func auditWithCommit(commit string) string {
	return strings.Replace(coveredAudit, `"service_name": "checkout",`,
		`"service_name": "checkout", "commit": "`+commit+`",`, 1)
}

// The score describes the tree the audit ran against; when the checkout has
// moved on the report must say so rather than presenting it as current.
func TestStaleWhenWorkspaceMovedOn(t *testing.T) {
	root := writeAudit(t, auditWithCommit("abc1234"))
	initGitRepo(t, root, "def567890abcdef1234567890abcdef123456789")

	got := NewResolver(Config{WorkspaceRoot: root}).Build()

	if !got.Stale {
		t.Errorf("Stale = false; audit commit %q vs HEAD %q", got.AuditCommit, got.WorkspaceCommit)
	}
	if got.AuditCommit != "abc1234" {
		t.Errorf("AuditCommit = %q", got.AuditCommit)
	}
	if got.WorkspaceCommit == "" {
		t.Error("WorkspaceCommit not resolved from .git")
	}
}

// Audits record a short id while HEAD is full length; a prefix match is the
// same commit and must not be flagged.
func TestNotStaleWhenShortCommitMatches(t *testing.T) {
	root := writeAudit(t, auditWithCommit("def5678"))
	initGitRepo(t, root, "def567890abcdef1234567890abcdef123456789")

	if got := NewResolver(Config{WorkspaceRoot: root}).Build(); got.Stale {
		t.Errorf("Stale = true for a matching short commit (%q vs %q)", got.AuditCommit, got.WorkspaceCommit)
	}
}

// An unknown commit on either side must never be reported as stale.
func TestNotStaleWhenCommitUnknown(t *testing.T) {
	t.Run("no git checkout", func(t *testing.T) {
		root := writeAudit(t, auditWithCommit("abc1234"))

		got := NewResolver(Config{WorkspaceRoot: root}).Build()
		if got.Stale {
			t.Error("Stale = true with no .git present")
		}
		if got.WorkspaceCommit != "" {
			t.Errorf("WorkspaceCommit = %q, want empty", got.WorkspaceCommit)
		}
	})

	t.Run("audit records no commit", func(t *testing.T) {
		root := writeAudit(t, coveredAudit)
		initGitRepo(t, root, "def567890abcdef1234567890abcdef123456789")

		if got := NewResolver(Config{WorkspaceRoot: root}).Build(); got.Stale {
			t.Error("Stale = true when the audit records no commit")
		}
	})
}

func TestWorkspaceCommitFromPackedRefs(t *testing.T) {
	root := t.TempDir()
	if err := os.MkdirAll(filepath.Join(root, ".git"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, ".git", "HEAD"), []byte("ref: refs/heads/main\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	packed := "# pack-refs with: peeled fully-peeled sorted\nabc1234567890abcdef1234567890abcdef12345 refs/heads/main\n"
	if err := os.WriteFile(filepath.Join(root, ".git", "packed-refs"), []byte(packed), 0o600); err != nil {
		t.Fatal(err)
	}

	if got := workspaceCommit(root); got != "abc1234567890abcdef1234567890abcdef12345" {
		t.Errorf("workspaceCommit = %q, want the packed ref", got)
	}
}

func TestWorkspaceCommitDetachedHead(t *testing.T) {
	root := t.TempDir()
	if err := os.MkdirAll(filepath.Join(root, ".git"), 0o755); err != nil {
		t.Fatal(err)
	}
	sha := "abc1234567890abcdef1234567890abcdef12345"
	if err := os.WriteFile(filepath.Join(root, ".git", "HEAD"), []byte(sha+"\n"), 0o600); err != nil {
		t.Fatal(err)
	}

	if got := workspaceCommit(root); got != sha {
		t.Errorf("workspaceCommit = %q, want the detached HEAD sha", got)
	}
}

// Nothing unexpected from the filesystem should reach the API response.
func TestWorkspaceCommitRejectsJunk(t *testing.T) {
	root := t.TempDir()
	if err := os.MkdirAll(filepath.Join(root, ".git"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, ".git", "HEAD"), []byte("not-a-sha; rm -rf /\n"), 0o600); err != nil {
		t.Fatal(err)
	}

	if got := workspaceCommit(root); got != "" {
		t.Errorf("workspaceCommit = %q, want empty for junk", got)
	}
}

// A linked worktree keeps HEAD in its own gitdir but shares refs through
// commondir; without following it, stale audits are never flagged there.
func TestWorkspaceCommitFromLinkedWorktree(t *testing.T) {
	main := t.TempDir()
	sha := "abc1234567890abcdef1234567890abcdef12345"
	mainGit := filepath.Join(main, ".git")
	if err := os.MkdirAll(filepath.Join(mainGit, "refs", "heads"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(mainGit, "refs", "heads", "feature"), []byte(sha+"\n"), 0o600); err != nil {
		t.Fatal(err)
	}

	// The worktree's own gitdir holds HEAD and a commondir pointer, not refs.
	tree := t.TempDir()
	wtGit := filepath.Join(main, ".git", "worktrees", "wt1")
	if err := os.MkdirAll(wtGit, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(wtGit, "HEAD"), []byte("ref: refs/heads/feature\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(wtGit, "commondir"), []byte("../..\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(tree, ".git"), []byte("gitdir: "+wtGit+"\n"), 0o600); err != nil {
		t.Fatal(err)
	}

	if got := workspaceCommit(tree); got != sha {
		t.Errorf("workspaceCommit = %q, want %q resolved through commondir", got, sha)
	}
}

// Averaged readiness must not surface as 16.666666666666668 in the UI.
func TestReportedValuesAreRounded(t *testing.T) {
	body := strings.Replace(coveredAudit, `"incident_readiness": [
      {"area": "HTTP latency", "status": "covered"},
      {"area": "Error rate", "status": "covered"}
    ]`, `"incident_readiness": [
      {"area": "a", "status": "covered"},
      {"area": "b", "status": "missing"},
      {"area": "c", "status": "missing"}
    ]`, 1)

	got := NewResolver(Config{WorkspaceRoot: writeAudit(t, body)}).Build()

	for _, c := range got.Breakdown.Components {
		if c.Earned != round2(c.Earned) {
			t.Errorf("component %q earned %v is not rounded", c.Label, c.Earned)
		}
	}
	if got.Breakdown.Coverage != round2(got.Breakdown.Coverage) {
		t.Errorf("coverage %v is not rounded", got.Breakdown.Coverage)
	}
}

// Presence matters: omitted sections unmarshal as empty values, so a truncated
// file would otherwise look like a legitimately sparse audit.
func TestRejectsTruncatedCanonicalSections(t *testing.T) {
	for name, body := range map[string]string{
		"no sections at all":              `{"schema_version":2,"kind":"otel-audit","meta":{"service_name":"x","status":"Pass"}}`,
		"missing findings":                `{"schema_version":2,"kind":"otel-audit","meta":{"service_name":"x","status":"Pass"},"current_instrumentation":{}}`,
		"missing current_instrumentation": `{"schema_version":2,"kind":"otel-audit","meta":{"service_name":"x","status":"Pass"},"findings":[]}`,
	} {
		t.Run(name, func(t *testing.T) {
			got := NewResolver(Config{WorkspaceRoot: writeAudit(t, body)}).Build()
			if got.Available {
				t.Errorf("Available = true with score %d; want refused", got.Score)
			}
		})
	}
}
