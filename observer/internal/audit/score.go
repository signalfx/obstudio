// Package audit turns the Markdown report written by the $otel-audit skill
// (.observe/otel.md) into a numeric instrumentation score.
//
// The score answers two questions the report already covers in prose:
//   - Coverage: which signals actually exist? (RED statuses, spans/metrics/logs)
//   - Quality: how clean is what exists? (anti-patterns, remaining gaps)
package audit

import "strconv"

// Scoring weights. These sum to 100 and are the single place to tune the
// model — everything else derives from them.
const (
	// Coverage — 70 points.
	pointsPerREDSignal = 15.0 // x3 signals (Rate, Errors, Duration) = 45
	pointsSpans        = 10.0
	pointsMetrics      = 10.0
	pointsLogs         = 5.0

	// Quality — 30 points, scored by subtraction from a full allowance.
	antiPatternAllowance  = 15.0
	penaltyPerAntiPattern = 5.0
	gapAllowance          = 15.0
	penaltyPerGap         = 3.0
)

// REDStatus is the per-signal status reported in the RED Signals table.
type REDStatus string

const (
	REDCovered REDStatus = "covered"
	REDPartial REDStatus = "partial"
	REDMissing REDStatus = "missing"
)

// fraction is the share of a signal's points awarded for a status.
func (s REDStatus) fraction() float64 {
	switch s {
	case REDCovered:
		return 1.0
	case REDPartial:
		return 0.5
	default:
		return 0.0
	}
}

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

// Report is the parsed shape of .observe/otel.md plus its derived score.
type Report struct {
	Available   bool   `json:"available"`
	Source      string `json:"source"`
	Message     string `json:"message,omitempty"`
	ServiceName string `json:"serviceName,omitempty"`
	Language    string `json:"language,omitempty"`
	Framework   string `json:"framework,omitempty"`
	GeneratedAt string `json:"generatedAt,omitempty"`

	Score     int       `json:"score"`
	Breakdown Breakdown `json:"breakdown"`

	Rate     REDStatus `json:"rate"`
	Errors   REDStatus `json:"errors"`
	Duration REDStatus `json:"duration"`

	HasSpans   bool `json:"hasSpans"`
	HasMetrics bool `json:"hasMetrics"`
	HasLogs    bool `json:"hasLogs"`

	GapCount            int `json:"gapCount"`
	AntiPatternCount    int `json:"antiPatternCount"`
	RecommendationCount int `json:"recommendationCount"`

	// Verbatim bullet text from the report, so the UI can show the findings
	// themselves rather than only their counts.
	Gaps            []string `json:"gaps"`
	AntiPatterns    []string `json:"antiPatterns"`
	Recommendations []string `json:"recommendations"`
}

// score computes the 0-100 score and its breakdown from already-parsed facts.
func (r *Report) score() {
	var components []Component

	redSignal := func(label string, status REDStatus) float64 {
		earned := pointsPerREDSignal * status.fraction()
		components = append(components, Component{
			Label:  label,
			Earned: earned,
			Max:    pointsPerREDSignal,
			Detail: string(status),
		})
		return earned
	}

	coverage := redSignal("Rate", r.Rate) +
		redSignal("Errors", r.Errors) +
		redSignal("Duration", r.Duration)

	signal := func(label string, present bool, max float64) float64 {
		earned := 0.0
		detail := "none detected"
		if present {
			earned = max
			detail = "present"
		}
		components = append(components, Component{Label: label, Earned: earned, Max: max, Detail: detail})
		return earned
	}

	coverage += signal("Spans", r.HasSpans, pointsSpans)
	coverage += signal("Metrics", r.HasMetrics, pointsMetrics)
	coverage += signal("Logs", r.HasLogs, pointsLogs)

	// Quality is an allowance reduced by each finding, floored at zero, so a
	// badly instrumented service cannot drag the total negative.
	antiPatterns := clampFloat(antiPatternAllowance-penaltyPerAntiPattern*float64(r.AntiPatternCount), 0, antiPatternAllowance)
	gaps := clampFloat(gapAllowance-penaltyPerGap*float64(r.GapCount), 0, gapAllowance)

	components = append(components,
		Component{
			Label:  "Anti-patterns",
			Earned: antiPatterns,
			Max:    antiPatternAllowance,
			Detail: pluralCount(r.AntiPatternCount, "anti-pattern", "anti-patterns"),
		},
		Component{
			Label:  "Gaps",
			Earned: gaps,
			Max:    gapAllowance,
			Detail: pluralCount(r.GapCount, "gap", "gaps"),
		},
	)

	quality := antiPatterns + gaps
	coverageMax := 3*pointsPerREDSignal + pointsSpans + pointsMetrics + pointsLogs
	qualityMax := antiPatternAllowance + gapAllowance

	r.Breakdown = Breakdown{
		Coverage:    coverage,
		CoverageMax: coverageMax,
		Quality:     quality,
		QualityMax:  qualityMax,
		Components:  components,
	}
	r.Score = int(roundHalfUp(coverage + quality))
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

	return strconv.Itoa(n) + " " + unit
}
