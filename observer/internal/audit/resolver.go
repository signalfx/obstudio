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

// readContained reads a file after resolving symlinks and re-checking that the
// real target is a regular file still inside the workspace.
//
// The string-level checks in resolveArtifactPath are not enough on their own:
// os.ReadFile follows symlinks, so a symlinked artifact could otherwise serve
// a file from anywhere on disk through a network endpoint.
func (r *Resolver) readContained(path string) ([]byte, error) {
	source := filepath.Base(path)

	// Resolve symlinks and confirm containment before opening. os.ReadFile
	// follows symlinks, so without this a symlinked artifact would serve a file
	// from anywhere on disk through a network endpoint.
	real, err := filepath.EvalSymlinks(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, ErrNoReport
		}
		log.Printf("[audit] resolve %s: %v", path, err)

		return nil, fmt.Errorf("could not read %s: %s", source, pathErrMsg(err))
	}

	if !r.contains(real) {
		log.Printf("[audit] refused %s: resolves outside the workspace", path)

		return nil, ErrNoReport
	}

	// Open once and validate the descriptor rather than the pathname. Checking
	// the path and then reopening it leaves a window in which the file can be
	// swapped for a symlink, device, or oversized file; fstat on the open
	// descriptor describes exactly the bytes about to be read. openNoFollow
	// additionally refuses a final symlink planted after the check above.
	file, err := openNoFollow(real)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, ErrNoReport
		}
		// ELOOP from O_NOFOLLOW lands here: the path became a symlink after the
		// containment check, so refuse it the same way.
		log.Printf("[audit] open %s: %v", path, err)

		return nil, ErrNoReport
	}
	defer file.Close()

	info, err := file.Stat()
	if err != nil {
		return nil, fmt.Errorf("could not read %s: %s", source, pathErrMsg(err))
	}
	if !info.Mode().IsRegular() {
		log.Printf("[audit] refused %s: not a regular file", path)

		return nil, ErrNoReport
	}
	if info.Size() > maxReportBytes {
		return nil, fmt.Errorf("%s is too large (%d bytes, limit %d)", source, info.Size(), maxReportBytes)
	}

	// Bound the read itself so a file growing between fstat and read cannot
	// pull an unbounded amount into memory.
	raw, err := io.ReadAll(io.LimitReader(file, maxReportBytes+1))
	if err != nil {
		log.Printf("[audit] read %s: %v", path, err)

		return nil, fmt.Errorf("could not read %s: %s", source, pathErrMsg(err))
	}
	if int64(len(raw)) > maxReportBytes {
		return nil, fmt.Errorf("%s is too large (limit %d bytes)", source, maxReportBytes)
	}

	return raw, nil
}

// contains reports whether a resolved path is inside the workspace. With no
// workspace configured (plain CLI use) there is nothing to contain against.
func (r *Resolver) contains(real string) bool {
	if r.workspaceRoot == "" {
		return true
	}
	root, err := filepath.EvalSymlinks(r.workspaceRoot)
	if err != nil {
		root = r.workspaceRoot
	}
	rel, err := filepath.Rel(root, real)
	if err != nil {
		return false
	}

	return rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator))
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

	raw, err := r.readContained(r.reportPath)
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

	if problem := validateCanonical(file); problem != "" {
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

	if _, err := r.readContained(r.htmlPath); err == nil {
		report.HasHTMLReport = true
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
func validateCanonical(file auditFile) string {
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

	return ""
}
