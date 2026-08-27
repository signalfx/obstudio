package audit

import (
	"encoding/json"
	"errors"
	"fmt"
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
func NewResolver(cfg Config) *Resolver {
	return &Resolver{
		workspaceRoot: cfg.WorkspaceRoot,
		reportPath:    resolveArtifactPath(cfg, cfg.ReportPath, DefaultReportRelPath),
		htmlPath:      resolveArtifactPath(cfg, "", DefaultHTMLRelPath),
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

	real, err := filepath.EvalSymlinks(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, ErrNoReport
		}
		log.Printf("[audit] resolve %s: %v", path, err)

		return nil, fmt.Errorf("could not read %s: %s", source, pathErrMsg(err))
	}

	if r.workspaceRoot != "" {
		root, err := filepath.EvalSymlinks(r.workspaceRoot)
		if err != nil {
			root = r.workspaceRoot
		}
		rel, err := filepath.Rel(root, real)
		if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
			log.Printf("[audit] refused %s: resolves outside the workspace", path)

			return nil, ErrNoReport
		}
	}

	info, err := os.Stat(real)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, ErrNoReport
		}

		return nil, fmt.Errorf("could not read %s: %s", source, pathErrMsg(err))
	}
	if !info.Mode().IsRegular() {
		log.Printf("[audit] refused %s: not a regular file", path)

		return nil, ErrNoReport
	}
	if info.Size() > maxReportBytes {
		return nil, fmt.Errorf("%s is too large (%d bytes, limit %d)", source, info.Size(), maxReportBytes)
	}

	raw, err := os.ReadFile(real)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, ErrNoReport
		}
		log.Printf("[audit] read %s: %v", path, err)

		return nil, fmt.Errorf("could not read %s: %s", source, pathErrMsg(err))
	}

	return raw, nil
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

	if file.Kind != "" && file.Kind != "otel-audit" {
		return unavailable(fmt.Sprintf("%s is not an $otel-audit report (kind %q).", source, file.Kind))
	}
	if file.SchemaVersion > CurrentSchemaVersion {
		return unavailable(fmt.Sprintf(
			"Instrumentation report at %s has unsupported schema_version %d (expected %d or lower). Re-run $otel-audit.",
			source, file.SchemaVersion, CurrentSchemaVersion,
		))
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
