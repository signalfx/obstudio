package validator

import "time"

type Signal string

const SignalValidation Signal = "validation"

type RuntimeStatus string

const (
	StatusDisabled RuntimeStatus = "disabled"
	StatusIdle     RuntimeStatus = "idle"
	StatusRunning  RuntimeStatus = "running"
	StatusReady    RuntimeStatus = "ready"
	StatusError    RuntimeStatus = "error"
)

type Severity string

const (
	SeverityInformation Severity = "information"
	SeverityImprovement Severity = "improvement"
	SeverityViolation   Severity = "violation"
)

type SignalRef struct {
	Type        string `json:"type"`
	ServiceName string `json:"serviceName,omitempty"`
	TraceID     string `json:"traceId,omitempty"`
	SpanID      string `json:"spanId,omitempty"`
	SpanName    string `json:"spanName,omitempty"`
	MetricName  string `json:"metricName,omitempty"`
	ScopeName   string `json:"scopeName,omitempty"`
	LogBody     string `json:"logBody,omitempty"`
}

type Finding struct {
	EntityKey string         `json:"entityKey"`
	Source    string         `json:"source"`
	RuleID    string         `json:"ruleId"`
	Severity  Severity       `json:"severity"`
	Message   string         `json:"message"`
	Context   map[string]any `json:"context,omitempty"`
	Signal    SignalRef      `json:"signal"`
	UpdatedAt time.Time      `json:"updatedAt"`
}

type Entity struct {
	Key             string    `json:"key"`
	HighestSeverity Severity  `json:"highestSeverity"`
	Signal          SignalRef `json:"signal"`
	Findings        []Finding `json:"findings"`
	UpdatedAt       time.Time `json:"updatedAt"`
}

type Summary struct {
	Enabled               bool           `json:"enabled"`
	Ready                 bool           `json:"ready"`
	Status                RuntimeStatus  `json:"status"`
	Message               string         `json:"message,omitempty"`
	LastError             string         `json:"lastError,omitempty"`
	HasResult             bool           `json:"hasResult"`
	Stale                 bool           `json:"stale"`
	NeedsRun              bool           `json:"needsRun"`
	ActiveRunID           string         `json:"activeRunId,omitempty"`
	ResultRunID           string         `json:"resultRunId,omitempty"`
	LastRunStartedAt      time.Time      `json:"lastRunStartedAt,omitempty"`
	LastRunCompletedAt    time.Time      `json:"lastRunCompletedAt,omitempty"`
	LastTelemetryAt       time.Time      `json:"lastTelemetryAt,omitempty"`
	TotalEntities         int            `json:"totalEntities"`
	TotalAdvisories       int            `json:"totalAdvisories"`
	NoAdviceCount         int            `json:"noAdviceCount"`
	SeverityCounts        map[string]int `json:"severityCounts"`
	HighestSeverityCounts map[string]int `json:"highestSeverityCounts"`
	SignalCounts          map[string]int `json:"signalCounts"`
	UpdatedAt             time.Time      `json:"updatedAt"`
}

type Issue struct {
	Key                 string    `json:"key"`
	Severity            Severity  `json:"severity"`
	Message             string    `json:"message"`
	SignalType          string    `json:"signalType"`
	TargetLabel         string    `json:"targetLabel"`
	ServiceName         string    `json:"serviceName,omitempty"`
	ScopeName           string    `json:"scopeName,omitempty"`
	Count               int       `json:"count"`
	ViolationCount      int       `json:"violationCount"`
	ImprovementCount    int       `json:"improvementCount"`
	InformationCount    int       `json:"informationCount"`
	AffectedEntityCount int       `json:"affectedEntityCount"`
	FirstSeen           time.Time `json:"firstSeen"`
	LastSeen            time.Time `json:"lastSeen"`
	Findings            []Finding `json:"findings"`
}

type Snapshot struct {
	Summary  Summary   `json:"summary"`
	Findings []Finding `json:"findings"`
	Issues   []Issue   `json:"issues"`
}

type AnalysisBasis string

const (
	AnalysisBasisFreshRun    AnalysisBasis = "fresh_run"
	AnalysisBasisLatestFresh AnalysisBasis = "latest_fresh_result"
	AnalysisBasisStaleResult AnalysisBasis = "stale_result"
)

type Analysis struct {
	AnalysisBasis   AnalysisBasis `json:"analysisBasis"`
	AnalysisMessage string        `json:"analysisMessage,omitempty"`
	Summary         Summary       `json:"summary"`
	Findings        []Finding     `json:"findings"`
	Issues          []Issue       `json:"issues"`
}

type Query struct {
	ServiceName string
	SignalType  string
	Severity    string
	RuleID      string
	TraceID     string
	SpanID      string
	MetricName  string
	LogBody     string
	Limit       int
}

type weaverStats struct {
	AdviceLevelCounts        map[string]int `json:"advice_level_counts"`
	HighestAdviceLevelCounts map[string]int `json:"highest_advice_level_counts"`
	NoAdviceCount            int            `json:"no_advice_count"`
	TotalAdvisories          int            `json:"total_advisories"`
	TotalEntities            int            `json:"total_entities"`
	TotalEntitiesByType      map[string]int `json:"total_entities_by_type"`
}

type RunStats = weaverStats

func severityRank(severity Severity) int {
	switch severity {
	case SeverityViolation:
		return 3
	case SeverityImprovement:
		return 2
	case SeverityInformation:
		return 1
	default:
		return 0
	}
}

func maxSeverity(a, b Severity) Severity {
	if severityRank(b) > severityRank(a) {
		return b
	}
	return a
}
