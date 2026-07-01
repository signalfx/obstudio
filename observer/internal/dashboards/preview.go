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

// maxSpecFileBytes caps the sidecar size read per request. The file is fed into
// a cross-origin network handler, so an oversized file is rejected rather than
// read fully into memory and unmarshalled.
const maxSpecFileBytes = 4 << 20 // 4 MiB

// maxPanelsPerBuild caps the number of non-text panels resolved against the
// store per request, bounding the work an unauthenticated cross-origin caller
// can trigger. Panels beyond the cap are reported with their grid placement and
// parsed query but no store resolution. It is a var so tests can lower it.
var maxPanelsPerBuild = 500

// metricGroupQueryFanout is the number of metric groups requested from the store
// before dimension filters and the display cap are applied. It is set to the ring
// capacity (store.DefaultMetricCap) so that even when a metric fans out into more
// distinct groups than the display cap, no dimension-matching group can be
// truncated by the store-side group cap before applyDimensionFilters runs. Each
// group needs at least one point and the ring holds at most DefaultMetricCap
// points, so this fanout can never drop a group the ring actually contains.
const metricGroupQueryFanout = store.DefaultMetricCap

// maxResolvedGroups caps the metric groups returned per panel after dimension
// filtering.
const maxResolvedGroups = 50

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
	// Source is reported as the basename only. The sidecar is served through a
	// cross-origin (Access-Control-Allow-Origin:*) endpoint, so the absolute
	// resolved path is withheld to avoid disclosing OS username/home/working-dir
	// layout to any origin.
	source := filepath.Base(r.specPath)

	resp := PreviewResponse{Approximate: true, Source: source, Groups: []PreviewGroup{}}

	info, err := os.Stat(r.specPath)
	if err != nil {
		if os.IsNotExist(err) {
			resp.Message = fmt.Sprintf("No dashboard preview found at %s. Run $splunk-dashboard to generate it.", source)

			return resp
		}

		resp.Message = fmt.Sprintf("Could not read dashboard preview at %s: %v", source, err)

		return resp
	}

	if info.Size() > maxSpecFileBytes {
		resp.Message = fmt.Sprintf("Dashboard preview at %s is too large (%d bytes, limit %d).", source, info.Size(), maxSpecFileBytes)

		return resp
	}

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

	// Snapshot the metric ring once for the whole build so every panel resolves
	// against the same point set instead of re-snapshotting the ring per panel.
	points := r.store.SnapshotMetrics()

	// resolved counts non-text panels resolved against the store so the per-
	// request work is bounded regardless of how many panels the spec declares.
	resolved := 0

	for _, g := range spec.Groups {
		pg := PreviewGroup{Name: g.Name, Description: g.Description, Dashboards: []PreviewDashboard{}}

		for _, d := range g.Dashboards {
			pd := PreviewDashboard{Name: d.Name, Description: d.Description, Panels: []PreviewPanel{}}

			for _, c := range d.Charts {
				pd.Panels = append(pd.Panels, r.resolvePanel(c, points, &resolved))
			}

			pg.Dashboards = append(pg.Dashboards, pd)
		}

		resp.Groups = append(resp.Groups, pg)
	}

	return resp
}

// resolvePanel resolves one chart spec into a PreviewPanel against the supplied
// metric snapshot. resolved tracks the running count of non-text panels resolved
// against the store this build; once it reaches maxPanelsPerBuild further panels
// report their query/placement but skip the store resolution.
func (r *Resolver) resolvePanel(c SpecChart, points []store.MetricDataPoint, resolved *int) PreviewPanel {
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

	if *resolved >= maxPanelsPerBuild {
		return panel
	}
	*resolved++

	groups, ok := resolveMetricGroups(points, q)
	if !ok {
		return panel
	}

	panel.Metrics = groups
	panel.Matched = len(groups) > 0

	return panel
}

// resolveMetricGroups resolves the metric groups matching a parsed query
// against a metric snapshot. The bool result is false when the query is
// self-contradictory (conflicting service alias values), in which case no store
// query is run and the panel stays unmatched.
func resolveMetricGroups(points []store.MetricDataPoint, q ParsedQuery) ([]store.MetricGroup, bool) {
	// Resolve the service filter through the canonical alias helper so
	// service.name and sf_service are treated as one dimension. A conflicting
	// pair (both keys present, disjoint values) means the panel's intent is
	// self-contradictory — return unmatched with no store query.
	svcValues, hasSvc, conflict := canonicalServiceFilter(q.Filters)
	if conflict {
		return nil, false
	}

	// QueryMetricsFilteredFromSnapshot accepts a single service name, applied
	// against the dedicated Resource.ServiceName field. When the filter has
	// exactly one accepted service value we push it into the store query. When it
	// has multiple, we query all services for the metric and enforce the
	// service-value set below against MetricGroup.ServiceName (attrMatchesAny does
	// NOT inspect that field, so the constraint must be re-applied here).
	svcArg := ""
	if hasSvc && len(svcValues) == 1 {
		svcArg = svcValues[0]
	}

	// Request a larger group set than the display cap so a series in a group
	// beyond maxResolvedGroups is not truncated before applyDimensionFilters runs.
	groups := store.QueryMetricsFilteredFromSnapshot(points, store.MetricFilter{
		MetricName:  q.MetricName,
		ServiceName: svcArg,
	}, metricGroupQueryFanout, 10_000)

	if hasSvc && len(svcValues) > 1 {
		groups = filterGroupsByService(groups, svcValues)
	}

	groups = applyDimensionFilters(groups, q.Filters)

	// Apply the display cap AFTER dimension filtering so the cap counts matching
	// groups, not pre-filter groups.
	if len(groups) > maxResolvedGroups {
		groups = groups[:maxResolvedGroups]
	}

	return groups, true
}

// filterGroupsByService keeps only groups whose ServiceName matches one of the
// accepted service values (case-insensitive). Service identity lives in the
// dedicated Resource.ServiceName field surfaced as MetricGroup.ServiceName,
// which the attribute-based applyDimensionFilters does not inspect, so a
// multi-value service constraint is enforced here.
func filterGroupsByService(groups []store.MetricGroup, svcValues []string) []store.MetricGroup {
	kept := make([]store.MetricGroup, 0, len(groups))
	for _, g := range groups {
		for _, want := range svcValues {
			if strings.EqualFold(g.ServiceName, want) {
				kept = append(kept, g)
				break
			}
		}
	}

	return kept
}

// isServiceKey reports whether a filter key is the service.name / sf_service
// alias pair that is handled at the store-query level.
func isServiceKey(k string) bool {
	return strings.EqualFold(k, "service.name") || strings.EqualFold(k, "sf_service")
}

// applyDimensionFilters narrows resolved groups by every filter other than the
// service dimension (already applied by the store query). A group is kept when
// at least one of its data points satisfies all remaining filters on either its
// own attributes or its resource attributes (case-insensitive).
// Filters use OR-semantics per key: a data point satisfies a key's constraint
// if its attribute value matches any one of the listed values.
func applyDimensionFilters(groups []store.MetricGroup, filters map[string][]string) []store.MetricGroup {
	extra := make(map[string][]string)

	for k, vs := range filters {
		if isServiceKey(k) {
			continue
		}

		extra[k] = vs
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
		g.DataPointCount = len(matchedPoints)
		kept = append(kept, g)
	}

	return kept
}

func dataPointMatches(dp store.MetricDataPoint, filters map[string][]string) bool {
	for k, wantVals := range filters {
		if !attrMatchesAny(dp.Attributes, k, wantVals) && !attrMatchesAny(dp.Resource.Attributes, k, wantVals) {
			return false
		}
	}

	return true
}

// attrMatchesAny reports whether any attribute in attrs whose key
// case-insensitively matches key has a value equal to at least one of wantVals.
// Attribute values are serialized via store.StringifyMetricValue to match the
// store's canonical representation (strings as-is, composites JSON-marshalled).
func attrMatchesAny(attrs map[string]any, key string, wantVals []string) bool {
	for ak, av := range attrs {
		if !strings.EqualFold(ak, key) {
			continue
		}

		got := store.StringifyMetricValue(av)
		for _, want := range wantVals {
			if strings.EqualFold(got, want) {
				return true
			}
		}
	}

	return false
}
