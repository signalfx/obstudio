package dashboards

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/signalfx/obstudio/observer/internal/store"
)

// DefaultSpecPath is the sidecar location relative to the working directory.
var DefaultSpecPath = filepath.Join(".observe", "dashboards.preview.json")

// Config carries optional dashboards-preview settings into api.Register.
type Config struct {
	SpecPath string
}

// Resolver builds a PreviewResponse from the sidecar file plus the live store.
type Resolver struct {
	store    *store.Store
	specPath string
}

// NewResolver returns a Resolver. An empty specPath falls back to DefaultSpecPath.
func NewResolver(s *store.Store, specPath string) *Resolver {
	if specPath == "" {
		specPath = DefaultSpecPath
	}

	return &Resolver{store: s, specPath: specPath}
}

// Build reads the sidecar and resolves every panel against local telemetry. It
// is called per request (one file read + an in-memory scan), so sidecar edits
// appear on refresh with no caching.
func (r *Resolver) Build() PreviewResponse {
	source := r.specPath
	if abs, err := filepath.Abs(r.specPath); err == nil {
		source = abs
	}

	resp := PreviewResponse{Approximate: true, Source: source, Groups: []PreviewGroup{}}

	raw, err := os.ReadFile(r.specPath)
	if err != nil {
		if os.IsNotExist(err) {
			resp.Message = fmt.Sprintf("No dashboard preview found at %s. Run $splunk-dashboard to generate it.", source)

			return resp
		}

		resp.Message = fmt.Sprintf("Could not read dashboard preview at %s: %v", source, err)

		return resp
	}

	var spec SpecFile
	if err := json.Unmarshal(raw, &spec); err != nil {
		resp.Message = fmt.Sprintf("Dashboard preview at %s is not valid JSON: %v", source, err)

		return resp
	}

	resp.Available = true
	resp.GeneratedAt = spec.GeneratedAt

	for _, g := range spec.Groups {
		pg := PreviewGroup{Name: g.Name, Description: g.Description, Dashboards: []PreviewDashboard{}}

		for _, d := range g.Dashboards {
			pd := PreviewDashboard{Name: d.Name, Description: d.Description, Panels: []PreviewPanel{}}

			for _, c := range d.Charts {
				pd.Panels = append(pd.Panels, r.resolvePanel(c))
			}

			pg.Dashboards = append(pg.Dashboards, pd)
		}

		resp.Groups = append(resp.Groups, pg)
	}

	return resp
}

// resolvePanel resolves one chart spec into a PreviewPanel.
func (r *Resolver) resolvePanel(c SpecChart) PreviewPanel {
	panel := PreviewPanel{
		Label:     c.Label,
		Title:     c.Title,
		ChartType: c.ChartType,
		Layout:    c.Layout,
	}

	// text/event panels carry markdown, not a query.
	if c.ChartType == "text" || c.ChartType == "event" {
		panel.Text = c.Text

		return panel
	}

	q := ParseProgramText(c.ProgramText)
	panel.Query = &q

	if q.ParseError != "" || q.MetricName == "" {
		return panel
	}

	// service.name is the OTel key; sf_service is the legacy SignalFx alias.
	serviceName := q.Filters["service.name"]
	if serviceName == "" {
		serviceName = q.Filters["sf_service"]
	}
	groups := r.store.QueryMetricsFiltered(q.MetricName, serviceName, "", "", "", 50, 10_000)
	groups = applyDimensionFilters(groups, q.Filters)
	panel.Metrics = groups
	panel.Matched = len(groups) > 0

	return panel
}

// applyDimensionFilters narrows resolved groups by every filter other than
// service.name (already applied by the store query). A group is kept when at
// least one of its data points satisfies all remaining filters on either its
// own attributes or its resource attributes (case-insensitive). Filters whose
// key is service.name are skipped here.
func applyDimensionFilters(groups []store.MetricGroup, filters map[string]string) []store.MetricGroup {
	extra := make(map[string]string)

	for k, v := range filters {
		if strings.EqualFold(k, "service.name") || strings.EqualFold(k, "sf_service") {
			continue
		}

		extra[k] = v
	}

	if len(extra) == 0 {
		return groups
	}

	kept := make([]store.MetricGroup, 0, len(groups))

	for _, g := range groups {
		matchedPoints := make([]store.MetricDataPoint, 0, len(g.DataPoints))

		for _, dp := range g.DataPoints {
			if dataPointMatches(dp, extra) {
				matchedPoints = append(matchedPoints, dp)
			}
		}

		if len(matchedPoints) == 0 {
			continue
		}

		g.DataPoints = matchedPoints
		kept = append(kept, g)
	}

	return kept
}

func dataPointMatches(dp store.MetricDataPoint, filters map[string]string) bool {
	for k, v := range filters {
		if !attrEquals(dp.Attributes, k, v) && !attrEquals(dp.Resource.Attributes, k, v) {
			return false
		}
	}

	return true
}

func attrEquals(attrs map[string]any, key, want string) bool {
	for ak, av := range attrs {
		if !strings.EqualFold(ak, key) {
			continue
		}

		if strings.EqualFold(fmt.Sprintf("%v", av), want) {
			return true
		}
	}

	return false
}
