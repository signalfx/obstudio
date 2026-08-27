// Package audit turns the canonical report written by the $otel-audit skill
// (.observe/otel-audit.json) into a numeric instrumentation score.
//
// The score answers two questions the report already covers:
//   - Coverage: which signals exist, and how ready are the incident surfaces?
//   - Quality: how much unresolved work and how many anti-patterns remain?
package audit

import "strings"

// CurrentSchemaVersion is the audit schema this package targets; version 1 is
// still accepted because the skill documents both as supported.
const CurrentSchemaVersion = 2

// Component weights. These are the single place to tune the model. A component
// that does not apply to a given report is dropped from both the earned total
// and the maximum, so reports stay comparable — see Report.score.
const (
	weightSpans        = 15.0
	weightMetrics      = 15.0
	weightLogs         = 15.0
	weightReadiness    = 25.0
	weightFindings     = 20.0
	weightAntiPatterns = 10.0
)

// Severity weights subtracted from the findings allowance, per unresolved
// finding. Informational findings cost nothing.
var findingSeverityCost = map[string]float64{
	"critical": 8,
	"high":     5,
	"medium":   3,
	"low":      1,
	"info":     0,
}

// unresolvedFindingStatuses mirrors the skill's UNRESOLVED_FINDING_STATUSES.
// A finding that is done, rejected, or deferred is not outstanding work.
var unresolvedFindingStatuses = map[string]bool{
	"proposed":    true,
	"approved":    true,
	"in_progress": true,
}

// readinessFraction maps an incident-readiness status to the share of credit it
// earns. "owner-mapped" means ownership is known but the signal is not proven,
// so it earns nothing.
func readinessFraction(status string) float64 {
	switch strings.ToLower(strings.TrimSpace(status)) {
	case "covered":
		return 1
	case "partial":
		return 0.5
	default:
		return 0
	}
}

// --- Canonical report shape (.observe/otel-audit.json) ----------------------

type auditFile struct {
	SchemaVersion  int          `json:"schema_version"`
	Kind           string       `json:"kind"`
	Meta           auditMeta    `json:"meta"`
	Summary        []string     `json:"summary"`
	Routes         []auditRoute `json:"routes"`
	Current        currentInstr `json:"current_instrumentation"`
	Findings       []auditFind  `json:"findings"`
	AntiPatterns   []any        `json:"anti_patterns"`
	Recommendation []string     `json:"recommendation"`
}

type auditMeta struct {
	AuditID     string `json:"audit_id"`
	ServiceName string `json:"service_name"`
	Commit      string `json:"commit"`
	Language    string `json:"language"`
	Framework   string `json:"framework"`
	Date        string `json:"date"`
	Status      string `json:"status"`
}

type auditRoute struct {
	Method string `json:"method"`
	Path   string `json:"path"`
}

type currentInstr struct {
	Spans             []any          `json:"spans"`
	Metrics           []any          `json:"metrics"`
	Logs              []any          `json:"logs"`
	IncidentReadiness []readinessRow `json:"incident_readiness"`
}

type readinessRow struct {
	Area   string `json:"area"`
	Status string `json:"status"`
}

type auditFind struct {
	ID       string `json:"id"`
	Title    string `json:"title"`
	Severity string `json:"severity"`
	Status   string `json:"status"`
	Area     string `json:"area"`
	Gap      string `json:"gap"`
}

// --- Scored output ----------------------------------------------------------

// Component is one scored line item, carried to the UI so the number can be
// explained rather than just displayed.
type Component struct {
	Label  string  `json:"label"`
	Earned float64 `json:"earned"`
	Max    float64 `json:"max"`
	Detail string  `json:"detail"`
}

// Breakdown is the full derivation of a Score.
type Breakdown struct {
	Coverage    float64     `json:"coverage"`
	CoverageMax float64     `json:"coverageMax"`
	Quality     float64     `json:"quality"`
	QualityMax  float64     `json:"qualityMax"`
	Components  []Component `json:"components"`
}

// Report is the scored view of an audit the UI consumes.
type Report struct {
	Available   bool   `json:"available"`
	Source      string `json:"source"`
	Message     string `json:"message,omitempty"`
	ServiceName string `json:"serviceName,omitempty"`
	Language    string `json:"language,omitempty"`
	Framework   string `json:"framework,omitempty"`
	GeneratedAt string `json:"generatedAt,omitempty"`
	// Status is the audit's own verdict: Pass, Partial, or Blocked.
	Status string `json:"status,omitempty"`
	// AuditCommit is the commit the audit recorded; WorkspaceCommit is the
	// checkout's current HEAD. Stale is true only when both are known and
	// differ, so an unknown commit is never reported as stale.
	AuditCommit     string `json:"auditCommit,omitempty"`
	WorkspaceCommit string `json:"workspaceCommit,omitempty"`
	Stale           bool   `json:"stale"`
	// HasHTMLReport reports whether the skill's human-readable report exists
	// next to the JSON, so the UI only links to it when it is there.
	HasHTMLReport bool `json:"hasHtmlReport"`

	Score     int       `json:"score"`
	Breakdown Breakdown `json:"breakdown"`

	HasSpans   bool `json:"hasSpans"`
	HasMetrics bool `json:"hasMetrics"`
	HasLogs    bool `json:"hasLogs"`

	GapCount            int `json:"gapCount"`
	AntiPatternCount    int `json:"antiPatternCount"`
	RecommendationCount int `json:"recommendationCount"`

	// Verbatim text from the report, so the UI shows the findings themselves
	// rather than only their counts. Always non-nil: a nil slice would marshal
	// to null and clients iterate these directly.
	Gaps            []string `json:"gaps"`
	AntiPatterns    []string `json:"antiPatterns"`
	Recommendations []string `json:"recommendations"`
}

// score computes the 0-100 score and its breakdown.
//
// Each component carries a weight. Components that do not apply to this report
// — currently incident readiness, when the audit lists no readiness areas — are
// excluded from both the earned total and the maximum, and the result is scaled
// to 100. That keeps a report without a readiness section comparable to one
// with it, instead of capping it below 100 for a section it never claimed.
func (r *Report) score(file auditFile) {
	var components []Component
	earned, max := 0.0, 0.0

	add := func(label string, got, weight float64, detail string) {
		components = append(components, Component{Label: label, Earned: got, Max: weight, Detail: detail})
		earned += got
		max += weight
	}

	signal := func(label string, present bool, weight float64) float64 {
		got, detail := 0.0, "none detected"
		if present {
			got, detail = weight, "present"
		}
		add(label, got, weight, detail)

		return got
	}

	coverage := signal("Spans", r.HasSpans, weightSpans)
	coverage += signal("Metrics", r.HasMetrics, weightMetrics)
	coverage += signal("Logs", r.HasLogs, weightLogs)
	coverageMax := weightSpans + weightMetrics + weightLogs

	// Incident readiness is proportional across the areas the audit assessed.
	if rows := file.Current.IncidentReadiness; len(rows) > 0 {
		total := 0.0
		covered := 0
		for _, row := range rows {
			f := readinessFraction(row.Status)
			total += f
			if f == 1 {
				covered++
			}
		}
		got := weightReadiness * total / float64(len(rows))
		add("Incident readiness", got, weightReadiness,
			pluralCount(covered, "area covered", "areas covered")+" of "+itoa(len(rows)))
		coverage += got
		coverageMax += weightReadiness
	}

	// Quality allowances, reduced by outstanding work and floored at zero so a
	// bad report cannot drag the total negative.
	findingsPenalty := 0.0
	for _, f := range file.Findings {
		if !unresolvedFindingStatuses[strings.ToLower(strings.TrimSpace(f.Status))] {
			continue
		}
		cost, known := findingSeverityCost[strings.ToLower(strings.TrimSpace(f.Severity))]
		if !known {
			cost = findingSeverityCost["medium"]
		}
		findingsPenalty += cost
	}
	findingsScore := clampFloat(weightFindings-findingsPenalty, 0, weightFindings)
	add("Findings", findingsScore, weightFindings, pluralCount(r.GapCount, "unresolved", "unresolved"))

	antiScore := clampFloat(weightAntiPatterns-5*float64(r.AntiPatternCount), 0, weightAntiPatterns)
	add("Anti-patterns", antiScore, weightAntiPatterns, pluralCount(r.AntiPatternCount, "anti-pattern", "anti-patterns"))

	quality := findingsScore + antiScore
	qualityMax := weightFindings + weightAntiPatterns

	r.Breakdown = Breakdown{
		Coverage:    coverage,
		CoverageMax: coverageMax,
		Quality:     quality,
		QualityMax:  qualityMax,
		Components:  components,
	}

	if max <= 0 {
		r.Score = 0

		return
	}
	r.Score = int(roundHalfUp(100 * earned / max))
}

func clampFloat(v, lo, hi float64) float64 {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}

	return v
}

func roundHalfUp(v float64) float64 {
	return float64(int(v + 0.5))
}

func pluralCount(n int, singular, plural string) string {
	unit := plural
	if n == 1 {
		unit = singular
	}

	return itoa(n) + " " + unit
}
