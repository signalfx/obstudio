package audit

import (
	"errors"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"strings"
)

// DefaultReportRelPath is the sidecar location relative to the workspace root.
// It is intentionally relative; callers must combine it with an explicit
// workspace root rather than the process CWD.
var DefaultReportRelPath = filepath.Join(".observe", "otel.md")

// maxReportBytes caps the report size read per request. The file is fed into a
// cross-origin network handler, so an oversized file is rejected rather than
// read fully into memory.
const maxReportBytes = 2 << 20 // 2 MiB

// Config carries optional audit-score settings into api.Register.
type Config struct {
	// WorkspaceRoot is the absolute workspace directory used to locate the
	// report. When empty, the process CWD is used as a fallback (CLI use only).
	WorkspaceRoot string
	// ReportPath optionally overrides the full path to the report. Path
	// traversal and paths escaping the workspace are rejected.
	ReportPath string
}

// Resolver builds a scored Report from the .observe/otel.md sidecar.
type Resolver struct {
	reportPath string
}

// NewResolver returns a Resolver using the same path-resolution rules as the
// dashboards preview sidecar.
func NewResolver(cfg Config) *Resolver {
	return &Resolver{reportPath: resolveReportPath(cfg)}
}

func resolveReportPath(cfg Config) string {
	if cfg.ReportPath != "" {
		p := cfg.ReportPath
		if strings.Contains(filepath.ToSlash(p), "..") {
			log.Printf("[audit] rejected report path with traversal component: %s", p)
			return safeDefaultPath(cfg.WorkspaceRoot)
		}
		if filepath.IsAbs(p) {
			if cfg.WorkspaceRoot != "" {
				rel, err := filepath.Rel(cfg.WorkspaceRoot, p)
				if err != nil || strings.HasPrefix(rel, "..") {
					log.Printf("[audit] rejected report path outside workspace root: %s", p)
					return safeDefaultPath(cfg.WorkspaceRoot)
				}
			}
			return p
		}
		if cfg.WorkspaceRoot != "" {
			return filepath.Join(cfg.WorkspaceRoot, p)
		}
		return p
	}

	return safeDefaultPath(cfg.WorkspaceRoot)
}

func safeDefaultPath(workspaceRoot string) string {
	if workspaceRoot != "" {
		return filepath.Join(workspaceRoot, DefaultReportRelPath)
	}

	return DefaultReportRelPath
}

// pathErrMsg returns a safe error message that excludes the absolute path,
// which would otherwise leak the local filesystem layout through the
// cross-origin endpoint.
func pathErrMsg(err error) string {
	var pe *os.PathError
	if errors.As(err, &pe) {
		return pe.Err.Error()
	}

	return err.Error()
}

// ErrNoReport reports that no audit report exists at the resolved path.
var ErrNoReport = errors.New("no instrumentation report found")

// ReadRaw returns the report's Markdown source, for serving the file itself.
// It applies the same resolved path and size cap as Build, so it can never read
// outside the workspace. Errors are safe to surface: they never embed the
// absolute path.
func (r *Resolver) ReadRaw() ([]byte, error) {
	source := filepath.Base(r.reportPath)

	info, err := os.Stat(r.reportPath)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, ErrNoReport
		}
		log.Printf("[audit] stat %s: %v", r.reportPath, err)

		return nil, fmt.Errorf("could not read %s: %s", source, pathErrMsg(err))
	}

	if info.Size() > maxReportBytes {
		return nil, fmt.Errorf("%s is too large (%d bytes, limit %d)", source, info.Size(), maxReportBytes)
	}

	raw, err := os.ReadFile(r.reportPath)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, ErrNoReport
		}
		log.Printf("[audit] read %s: %v", r.reportPath, err)

		return nil, fmt.Errorf("could not read %s: %s", source, pathErrMsg(err))
	}

	return raw, nil
}

// Source returns the report's basename, for display and download naming. The
// absolute path is deliberately withheld.
func (r *Resolver) Source() string {
	return filepath.Base(r.reportPath)
}

// Build reads and scores the report. It is called per request (one file read),
// so re-running $otel-audit is reflected on the next refresh with no caching.
func (r *Resolver) Build() Report {
	// Only the basename is reported: this endpoint carries
	// Access-Control-Allow-Origin:*, so the resolved absolute path is withheld.
	source := filepath.Base(r.reportPath)
	unavailable := func(message string) Report {
		return Report{Source: source, Message: message}
	}

	info, err := os.Stat(r.reportPath)
	if err != nil {
		if os.IsNotExist(err) {
			return unavailable(fmt.Sprintf("No instrumentation report found at %s. Run $otel-audit to generate it.", source))
		}
		log.Printf("[audit] stat %s: %v", r.reportPath, err)

		return unavailable(fmt.Sprintf("Could not read instrumentation report at %s: %s", source, pathErrMsg(err)))
	}

	if info.Size() > maxReportBytes {
		return unavailable(fmt.Sprintf("Instrumentation report at %s is too large (%d bytes, limit %d).", source, info.Size(), maxReportBytes))
	}

	raw, err := os.ReadFile(r.reportPath)
	if err != nil {
		if os.IsNotExist(err) {
			return unavailable(fmt.Sprintf("No instrumentation report found at %s. Run $otel-audit to generate it.", source))
		}
		log.Printf("[audit] read %s: %v", r.reportPath, err)

		return unavailable(fmt.Sprintf("Could not read instrumentation report at %s: %s", source, pathErrMsg(err)))
	}

	report := Parse(string(raw))
	report.Source = source

	// A file that parses to no RED table and no signals is almost certainly not
	// an $otel-audit report; report it as unavailable rather than scoring a
	// misleading zero.
	if !report.hasAnyFacts() {
		return unavailable(fmt.Sprintf("Instrumentation report at %s is empty or malformed. Re-run $otel-audit to regenerate it.", source))
	}

	return report
}

// hasAnyFacts reports whether the parse found anything a real report would have.
func (r *Report) hasAnyFacts() bool {
	return r.ServiceName != "" ||
		r.HasSpans || r.HasMetrics || r.HasLogs ||
		r.Rate != REDMissing || r.Errors != REDMissing || r.Duration != REDMissing ||
		r.GapCount > 0 || r.AntiPatternCount > 0
}
