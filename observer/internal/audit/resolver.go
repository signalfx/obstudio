package audit

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

// Artifacts the $otel-audit skill writes, relative to the workspace root.
//
//	otel-audit.json — canonical machine-readable source, scored here.
//	otel.html       — the skill's own human-readable report, served as-is.
var (
	DefaultReportRelPath = filepath.Join(".observe", "otel-audit.json")
	DefaultHTMLRelPath   = filepath.Join(".observe", "otel.html")
)

// maxReportBytes caps the file size read per request. These files are reachable
// over the network, so an oversized one is rejected rather than read into memory.
const maxReportBytes = 8 << 20 // 8 MiB

// ErrNoReport reports that no audit artifact exists at the resolved path.
var ErrNoReport = errors.New("no instrumentation report found")

// Config carries optional audit settings into api.Register.
type Config struct {
	// WorkspaceRoot is the absolute workspace directory used to locate the
	// artifacts. When empty, the process CWD is used (CLI use only).
	WorkspaceRoot string
	// ReportPath optionally overrides the full path to the JSON audit.
	// Traversal and paths escaping the workspace are rejected.
	ReportPath string
}

// Resolver builds a scored Report from the audit artifacts.
type Resolver struct {
	workspaceRoot string
	reportPath    string
	htmlPath      string
}

// NewResolver returns a Resolver bound to the configured workspace.
//
// The HTML report is always resolved as a sibling of the JSON audit actually
// being scored. Pinning it to the default location instead would let an
// override score one audit while serving a different, possibly stale, report.
func NewResolver(cfg Config) *Resolver {
	// Documented to fall back to the process CWD. Resolving it here rather than
	// leaving it empty keeps containment and staleness active in the default
	// CLI configuration instead of silently disabling both.
	if cfg.WorkspaceRoot == "" {
		if cwd, err := os.Getwd(); err == nil {
			cfg.WorkspaceRoot = cwd
		}
	}

	reportPath := resolveArtifactPath(cfg, cfg.ReportPath, DefaultReportRelPath)

	return &Resolver{
		workspaceRoot: cfg.WorkspaceRoot,
		reportPath:    reportPath,
		htmlPath:      filepath.Join(filepath.Dir(reportPath), filepath.Base(DefaultHTMLRelPath)),
	}
}

func resolveArtifactPath(cfg Config, override, defaultRel string) string {
	fallback := func() string {
		if cfg.WorkspaceRoot != "" {
			return filepath.Join(cfg.WorkspaceRoot, defaultRel)
		}

		return defaultRel
	}

	if override == "" {
		return fallback()
	}
	if strings.Contains(filepath.ToSlash(override), "..") {
		log.Printf("[audit] rejected report path with traversal component: %s", override)

		return fallback()
	}
	if filepath.IsAbs(override) {
		if cfg.WorkspaceRoot != "" {
			rel, err := filepath.Rel(cfg.WorkspaceRoot, override)
			if err != nil || strings.HasPrefix(rel, "..") {
				log.Printf("[audit] rejected report path outside workspace root: %s", override)

				return fallback()
			}
		}

		return override
	}
	if cfg.WorkspaceRoot != "" {
		return filepath.Join(cfg.WorkspaceRoot, override)
	}

	return override
}

// containedRel converts an absolute artifact path into a path relative to the
// workspace root, refusing anything that points outside it.
func (r *Resolver) containedRel(path string) (string, error) {
	if r.workspaceRoot == "" {
		// Nothing to contain against; refuse rather than touch an unbounded path.
		return "", ErrNoReport
	}

	rel, err := filepath.Rel(r.workspaceRoot, path)
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		log.Printf("[audit] refused %s: outside the workspace", filepath.Base(path))

		return "", ErrNoReport
	}

	return rel, nil
}

// openRoot returns a root-scoped handle on the workspace.
//
// os.Root scopes every path operation to the workspace and is resolved by the
// kernel per component, so a symlink, junction, or reparse point that escapes
// the root is refused even when planted between checks. This replaces
// resolve-then-reopen, which left a window in which the validated file could be
// swapped, and it behaves the same on Windows, where O_NOFOLLOW does not exist.
func (r *Resolver) openRoot() (*os.Root, error) {
	root, err := os.OpenRoot(r.workspaceRoot)
	if err != nil {
		log.Printf("[audit] open workspace root: %v", err)

		return nil, ErrNoReport
	}

	return root, nil
}

// statContained reports an artifact's metadata without reading it, for callers
// that only need to know whether the file is there.
func (r *Resolver) statContained(path string) (os.FileInfo, error) {
	rel, err := r.containedRel(path)
	if err != nil {
		return nil, err
	}

	root, err := r.openRoot()
	if err != nil {
		return nil, err
	}
	defer root.Close()

	info, err := root.Stat(rel)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, ErrNoReport
		}
		// An escape attempt surfaces here too; treat it as absent.
		log.Printf("[audit] refused %s: %v", filepath.Base(path), err)

		return nil, ErrNoReport
	}
	if !info.Mode().IsRegular() {
		return nil, ErrNoReport
	}

	return info, nil
}

// readContained reads an artifact through a root-scoped handle on the
// workspace, so no path operation can leave it.
func (r *Resolver) readContained(path string) ([]byte, error) {
	raw, _, err := r.readContainedInfo(path)

	return raw, err
}

// readContainedInfo reads an artifact and also returns the metadata of the
// exact descriptor it read, so callers can use the file's modification time
// without a second, racy stat by path.
func (r *Resolver) readContainedInfo(path string) ([]byte, os.FileInfo, error) {
	source := filepath.Base(path)

	rel, err := r.containedRel(path)
	if err != nil {
		return nil, nil, err
	}

	root, err := r.openRoot()
	if err != nil {
		return nil, nil, err
	}
	defer root.Close()

	file, err := root.Open(rel)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil, ErrNoReport
		}
		// An escape attempt surfaces here too; treat it as absent.
		log.Printf("[audit] refused %s: %v", source, err)

		return nil, nil, ErrNoReport
	}
	defer file.Close()

	// fstat on the open descriptor describes exactly the bytes about to be read.
	info, err := file.Stat()
	if err != nil {
		return nil, nil, fmt.Errorf("could not read %s: %s", source, pathErrMsg(err))
	}
	if !info.Mode().IsRegular() {
		log.Printf("[audit] refused %s: not a regular file", source)

		return nil, nil, ErrNoReport
	}
	if info.Size() > maxReportBytes {
		return nil, nil, fmt.Errorf("%s is too large (%d bytes, limit %d)", source, info.Size(), maxReportBytes)
	}

	// Bound the read so a file growing after fstat cannot pull an unbounded
	// amount into memory.
	raw, err := io.ReadAll(io.LimitReader(file, maxReportBytes+1))
	if err != nil {
		log.Printf("[audit] read %s: %v", source, err)

		return nil, nil, fmt.Errorf("could not read %s: %s", source, pathErrMsg(err))
	}
	if int64(len(raw)) > maxReportBytes {
		return nil, nil, fmt.Errorf("%s is too large (limit %d bytes)", source, maxReportBytes)
	}

	return raw, info, nil
}

// pathErrMsg returns an error message that excludes the absolute path, which
// would otherwise disclose the local filesystem layout to callers.
func pathErrMsg(err error) string {
	var pe *os.PathError
	if errors.As(err, &pe) {
		return pe.Err.Error()
	}

	return err.Error()
}

// ReportArtifacts are the files the $otel-audit report links to relatively,
// mirroring the allowlist the skill's own report server exposes. Serving the
// report without its siblings leaves those links broken.
var ReportArtifacts = map[string]string{
	"otel.html":                 "text/html; charset=utf-8",
	"otel-instrumentation.html": "text/html; charset=utf-8",
	"otel-audit.json":           "application/json; charset=utf-8",
}

// ReadArtifact returns one allowlisted report artifact and its content type.
// The name is looked up in ReportArtifacts rather than joined from the request,
// so it can never address a file the report does not link to.
func (r *Resolver) ReadArtifact(name string) ([]byte, string, error) {
	contentType, ok := ReportArtifacts[name]
	if !ok {
		return nil, "", ErrNoReport
	}

	// Siblings of the audit actually being scored, so an override keeps the
	// report and its data together.
	raw, err := r.readContained(filepath.Join(filepath.Dir(r.reportPath), name))
	if err != nil {
		return nil, "", err
	}

	return raw, contentType, nil
}

// ReadHTML returns the skill's own human-readable report.
func (r *Resolver) ReadHTML() ([]byte, error) {
	return r.readContained(r.htmlPath)
}

// HTMLSource returns the HTML report's basename, for display and naming. The
// absolute path is deliberately withheld.
func (r *Resolver) HTMLSource() string {
	return filepath.Base(r.htmlPath)
}

// Source returns the JSON audit's basename.
func (r *Resolver) Source() string {
	return filepath.Base(r.reportPath)
}

// Build reads and scores the audit. It is called per request (one file read),
// so re-running $otel-audit is reflected on the next refresh with no caching.
func (r *Resolver) Build() Report {
	source := r.Source()
	unavailable := func(message string) Report {
		return Report{Source: source, Message: message, Gaps: []string{}, AntiPatterns: []string{}, Recommendations: []string{}}
	}

	raw, info, err := r.readContainedInfo(r.reportPath)
	if err != nil {
		if errors.Is(err, ErrNoReport) {
			return unavailable(fmt.Sprintf("No instrumentation report found at %s. Run $otel-audit to generate it.", source))
		}

		return unavailable(fmt.Sprintf("Could not read instrumentation report at %s: %v", source, err))
	}

	var file auditFile
	if err := json.Unmarshal(raw, &file); err != nil {
		return unavailable(fmt.Sprintf("Instrumentation report at %s is not valid JSON: %v", source, err))
	}

	// Presence, not just shape: omitted sections unmarshal as empty values, so a
	// truncated file would otherwise look like a legitimately sparse audit.
	var present map[string]json.RawMessage
	if err := json.Unmarshal(raw, &present); err != nil {
		return unavailable(fmt.Sprintf("Instrumentation report at %s is not a JSON object: %v", source, err))
	}

	if problem := validateCanonical(file, present); problem != "" {
		// Syntactically valid JSON is not enough: a truncated or hand-edited
		// artifact would otherwise be presented as a real score.
		return unavailable(fmt.Sprintf("Instrumentation report at %s is not a usable $otel-audit report: %s. Re-run $otel-audit.", source, problem))
	}

	report := Report{
		Available:   true,
		Source:      source,
		ServiceName: file.Meta.ServiceName,
		Language:    file.Meta.Language,
		Framework:   file.Meta.Framework,
		GeneratedAt: file.Meta.Date,
		Status:      file.Meta.Status,
		AuditCommit: sanitizeCommit(file.Meta.Commit),
		HasSpans:    len(file.Current.Spans) > 0,
		HasMetrics:  len(file.Current.Metrics) > 0,
		HasLogs:     len(file.Current.Logs) > 0,
	}

	report.Gaps = unresolvedFindingTexts(file.Findings)
	report.AntiPatterns = stringList(file.AntiPatterns)
	report.Recommendations = nonNil(file.Recommendation)
	report.GapCount = len(report.Gaps)
	report.AntiPatternCount = len(report.AntiPatterns)
	report.RecommendationCount = len(report.Recommendations)

	// Only existence matters here, and the report endpoint reads the file
	// itself; statting keeps an 8 MiB read off every score request.
	if _, err := r.statContained(r.htmlPath); err == nil {
		report.HasHTMLReport = true
	}

	// A saved audit describes the tree it was run against. When the checkout has
	// moved on, say so rather than presenting an old score as current.
	report.WorkspaceCommit = workspaceCommit(r.workspaceRoot)
	switch {
	case commitsDiffer(report.AuditCommit, report.WorkspaceCommit):
		report.Stale, report.StaleReason = true, StaleCommit
	case sourceChangedAfter(r.workspaceRoot, info.ModTime()):
		// $otel-instrument edits source in place and commits nothing, so the
		// commit check alone would keep presenting the pre-instrumentation
		// score as current. The audit artifact's own mtime is the reference
		// point: anything in the tree written after it postdates the audit.
		report.Stale, report.StaleReason = true, StaleChanges
	}

	report.score(file)

	return report
}

// unresolvedFindingTexts renders the outstanding findings as display strings.
// Resolved findings (done, rejected, deferred) are not outstanding work and are
// left out of both the list and the score.
func unresolvedFindingTexts(findings []auditFind) []string {
	out := []string{}
	for _, f := range findings {
		if !unresolvedFindingStatuses[strings.ToLower(strings.TrimSpace(f.Status))] {
			continue
		}
		text := strings.TrimSpace(f.Title)
		if text == "" {
			text = strings.TrimSpace(f.Gap)
		}
		if text == "" {
			text = strings.TrimSpace(f.ID)
		}
		if text == "" {
			continue
		}
		if id := strings.TrimSpace(f.ID); id != "" {
			text = id + " — " + text
		}
		out = append(out, text)
	}

	return out
}

// stringList renders a loosely-typed JSON array as display strings, accepting
// either plain strings or objects carrying a title/description-style field.
func stringList(items []any) []string {
	out := []string{}
	for _, item := range items {
		switch v := item.(type) {
		case string:
			if s := strings.TrimSpace(v); s != "" {
				out = append(out, s)
			}
		case map[string]any:
			for _, key := range []string{"title", "issue", "description", "detail", "name"} {
				if s, ok := v[key].(string); ok && strings.TrimSpace(s) != "" {
					out = append(out, strings.TrimSpace(s))

					break
				}
			}
		}
	}

	return out
}

func nonNil(items []string) []string {
	if items == nil {
		return []string{}
	}

	return items
}

func itoa(n int) string {
	return strconv.Itoa(n)
}

// auditStatuses mirrors the skill's meta.status domain.
var auditStatuses = map[string]bool{"Pass": true, "Partial": true, "Blocked": true}

// validateCanonical reports why a report cannot be scored, or "" when it can.
// It checks the parts the score actually depends on, so a partial artifact is
// reported as unusable rather than scored as if it were complete.
func validateCanonical(file auditFile, present map[string]json.RawMessage) string {
	if file.Kind != "otel-audit" {
		if file.Kind == "" {
			return "missing kind"
		}

		return fmt.Sprintf("kind is %q, not \"otel-audit\"", file.Kind)
	}
	if file.SchemaVersion <= 0 {
		return "missing schema_version"
	}
	if file.SchemaVersion > CurrentSchemaVersion {
		return fmt.Sprintf("unsupported schema_version %d (expected %d or lower)", file.SchemaVersion, CurrentSchemaVersion)
	}
	if strings.TrimSpace(file.Meta.ServiceName) == "" {
		return "missing meta.service_name"
	}
	if !auditStatuses[strings.TrimSpace(file.Meta.Status)] {
		return fmt.Sprintf("meta.status is %q, expected Pass, Partial, or Blocked", file.Meta.Status)
	}
	// finalize-audit always emits these sections, so a file missing one never
	// went through finalization and must not be scored as if it had.
	for _, key := range []string{"current_instrumentation", "findings"} {
		if _, ok := present[key]; !ok {
			return "missing " + key
		}
	}

	return ""
}
