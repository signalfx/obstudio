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

// A symlink that stays inside the workspace is legitimate and must still work.
func TestSymlinkInsideWorkspaceIsAllowed(t *testing.T) {
	root := t.TempDir()
	if err := os.MkdirAll(filepath.Join(root, ".observe"), 0o755); err != nil {
		t.Fatal(err)
	}
	real := filepath.Join(root, "real-audit.json")
	if err := os.WriteFile(real, []byte(coveredAudit), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(real, filepath.Join(root, ".observe", "otel-audit.json")); err != nil {
		t.Skipf("symlinks unavailable: %v", err)
	}

	if got := NewResolver(Config{WorkspaceRoot: root}).Build(); !got.Available {
		t.Errorf("in-workspace symlink refused: %s", got.Message)
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
