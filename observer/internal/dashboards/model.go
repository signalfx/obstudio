// Package dashboards builds an approximate, local-data preview of a Splunk
// Observability Cloud dashboard from the sidecar file that the $splunk-dashboard
// skill writes (.observe/dashboards.preview.json).
//
// The preview is deliberately approximate: SignalFlow program_text executes on
// Splunk's backend, not here. This package parses each panel's SignalFlow to
// recover { metric, filters, aggregation }, resolves the matching series already
// in the in-memory store, and reports them laid out on the dashboard's real
// 12-column grid. It verifies "this panel targets a metric you are actually
// emitting, placed where Splunk will put it" — not "this is the exact chart
// Splunk renders".
package dashboards

import "github.com/signalfx/obstudio/observer/internal/store"

// SpecFile is the decoded shape of .observe/dashboards.preview.json.
type SpecFile struct {
	SchemaVersion int         `json:"schemaVersion"`
	GeneratedAt   string      `json:"generatedAt"`
	Groups        []SpecGroup `json:"groups"`
}

// SpecGroup mirrors a signalfx_dashboard_group.
type SpecGroup struct {
	Name        string          `json:"name"`
	Description string          `json:"description"`
	Dashboards  []SpecDashboard `json:"dashboards"`
}

// SpecDashboard mirrors a signalfx_dashboard.
type SpecDashboard struct {
	Name        string      `json:"name"`
	Description string      `json:"description"`
	Charts      []SpecChart `json:"charts"`
}

// SpecChart mirrors one per-panel signalfx_*_chart, with the SignalFlow already
// resolved by the skill (no ${var.*}, dedented heredoc).
type SpecChart struct {
	Label       string     `json:"label"`
	Title       string     `json:"title"`
	ChartType   string     `json:"chartType"`
	ProgramText string     `json:"programText"`
	Text        *string    `json:"text"`
	Layout      SpecLayout `json:"layout"`
}

// SpecLayout mirrors the HCL chart {} grid block exactly.
type SpecLayout struct {
	Column int `json:"column"`
	Row    int `json:"row"`
	Width  int `json:"width"`
	Height int `json:"height"`
}

// PreviewResponse is the API payload for GET /api/dashboards/preview.
type PreviewResponse struct {
	Available   bool           `json:"available"`
	Approximate bool           `json:"approximate"`
	Source      string         `json:"source"`
	GeneratedAt string         `json:"generatedAt,omitempty"`
	Message     string         `json:"message,omitempty"`
	Groups      []PreviewGroup `json:"groups"`
}

// PreviewGroup is a resolved dashboard group.
type PreviewGroup struct {
	Name        string             `json:"name"`
	Description string             `json:"description,omitempty"`
	Dashboards  []PreviewDashboard `json:"dashboards"`
}

// PreviewDashboard is a resolved dashboard.
type PreviewDashboard struct {
	Name        string         `json:"name"`
	Description string         `json:"description,omitempty"`
	Panels      []PreviewPanel `json:"panels"`
}

// PreviewPanel is a resolved panel: its grid placement, the parsed query, and
// the local series (if any) that match it. Metrics reuse store.MetricGroup
// verbatim so the frontend feeds them straight into useMetricTimeSeries.
type PreviewPanel struct {
	Label     string              `json:"label"`
	Title     string              `json:"title"`
	ChartType string              `json:"chartType"`
	Layout    SpecLayout          `json:"layout"`
	Text      *string             `json:"text,omitempty"`
	Query     *ParsedQuery        `json:"query,omitempty"`
	Matched   bool                `json:"matched"`
	Metrics   []store.MetricGroup `json:"metrics,omitempty"`
}

// ParsedQuery is the focused extraction from a panel's SignalFlow program_text.
// Filters maps each dimension key to the accepted values (OR-semantics: a data
// point matches if its attribute equals any one of the listed values).
// NegatedFilters maps each negated dimension key to the excluded values; data
// points whose attribute matches any listed value for a key are excluded.
// IgnoredFilters lists dimension keys whose constraints could not be applied
// (e.g. a nested-function value that the regex could not parse).
type ParsedQuery struct {
	MetricName     string              `json:"metricName,omitempty"`
	Filters        map[string][]string `json:"filters,omitempty"`
	NegatedFilters map[string][]string `json:"negatedFilters,omitempty"`
	IgnoredFilters []string            `json:"ignoredFilters,omitempty"`
	Aggregation    string              `json:"aggregation,omitempty"`
	Percentile     *float64            `json:"percentile,omitempty"`
	ParseError     string              `json:"parseError,omitempty"`
}
