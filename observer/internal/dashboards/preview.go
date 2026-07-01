package dashboards

import (
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"strings"

	"github.com/signalfx/obstudio/observer/internal/store"
)

// DefaultSpecRelPath is the sidecar location relative to the workspace root.
// It is intentionally relative; callers must combine it with an explicit
// workspace root (see Config.WorkspaceRoot) rather than the process CWD.
var DefaultSpecRelPath = filepath.Join(".observe", "dashboards.preview.json")

// maxSpecFileBytes caps the sidecar size read per request. The file is fed into
// a cross-origin network handler, so an oversized file is rejected rather than
// read fully into memory and unmarshalled.
const maxSpecFileBytes = 4 << 20 // 4 MiB

// maxPanelsPerBuild caps the number of non-text panels resolved against the
// store per request, bounding the work an unauthenticated cross-origin caller
// can trigger. Panels beyond the cap are reported with their grid placement and
// parsed query but no store resolution. It is a var so tests can lower it.
var maxPanelsPerBuild = 500

// maxResponseDataPoints is the build-wide total datapoint budget across all
// panels and all metric groups in a single preview response. Once reached,
// further groups are returned without datapoints to keep JSON payload size and
// auto-refresh allocation bounded. It is a var so tests can lower it.
var maxResponseDataPoints = 50_000

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
	// WorkspaceRoot is the absolute workspace directory used to locate the
	// sidecar. When empty, the process CWD is used as a fallback (CLI use
	// only). The VS Code extension must always supply an explicit root.
	WorkspaceRoot string
	// SpecPath is an optional override for the full absolute path to the
	// preview sidecar. When set it takes precedence over WorkspaceRoot.
	// The path must be relative or within a known safe root; absolute paths
	// pointing outside the workspace are rejected.
	SpecPath string
}

// Resolver builds a PreviewResponse from the sidecar file plus the live store.
type Resolver struct {
	store    *store.Store
	specPath string
}

// NewResolver returns a Resolver. specPath is resolved as follows:
//  1. If cfg.SpecPath is set: validate it is not an absolute path outside
//     cfg.WorkspaceRoot, reject path traversal (absolute paths and ".." components).
//  2. Otherwise: join cfg.WorkspaceRoot + DefaultSpecRelPath.
//  3. If cfg.WorkspaceRoot is also empty: fall back to DefaultSpecRelPath
//     relative to the process CWD (CLI/test use only).
func NewResolver(s *store.Store, cfg Config) *Resolver {
	specPath := resolveSpecPath(cfg)
	return &Resolver{store: s, specPath: specPath}
}

// resolveSpecPath computes the final spec path from cfg, enforcing:
//   - No absolute paths that escape the workspace root.
//   - No ".." path components.
//   - Fall back to workspace-relative DefaultSpecRelPath when no override given.
func resolveSpecPath(cfg Config) string {
	if cfg.SpecPath != "" {
		p := cfg.SpecPath
		// Reject ".." components to prevent traversal.
		if strings.Contains(filepath.ToSlash(p), "..") {
			log.Printf("[dashboards] rejected spec path with traversal component: %s", p)
			return safeDefaultPath(cfg.WorkspaceRoot)
		}
		// If the path is absolute and a workspace root is configured, verify the
		// path is contained within the workspace. When no workspace root is set
		// (e.g. plain CLI use), an absolute SpecPath is accepted as-is — the user
		// supplied it explicitly via OBSTUDIO_DASHBOARDS_PREVIEW.
		if filepath.IsAbs(p) {
			if cfg.WorkspaceRoot != "" {
				rel, err := filepath.Rel(cfg.WorkspaceRoot, p)
				if err != nil || strings.HasPrefix(rel, "..") {
					log.Printf("[dashboards] rejected spec path outside workspace root: %s", p)
					return safeDefaultPath(cfg.WorkspaceRoot)
				}
			}
			return p
		}
		// Relative path — join with workspace root when provided.
		if cfg.WorkspaceRoot != "" {
			return filepath.Join(cfg.WorkspaceRoot, p)
		}
		return p
	}
	return safeDefaultPath(cfg.WorkspaceRoot)
}

func safeDefaultPath(workspaceRoot string) string {
	if workspaceRoot != "" {
		return filepath.Join(workspaceRoot, DefaultSpecRelPath)
	}
	return DefaultSpecRelPath
}

// pathErrMsg returns a safe error message for an *os.PathError that excludes
// the absolute file-system path (which would be served through the
// Access-Control-Allow-Origin:* endpoint and leak the local FS layout).
func pathErrMsg(err error) string {
	var pe *os.PathError
	if errors.As(err, &pe) {
		// pe.Err is the underlying syscall error (e.g. "no such file or
		// directory") with no path embedded — safe to expose.
		return pe.Err.Error()
	}
	return err.Error()
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

		// Log the detailed path error server-side; return only the OS message
		// to callers (the endpoint carries Access-Control-Allow-Origin:*).
		log.Printf("[dashboards] stat %s: %v", r.specPath, err)
		resp.Message = fmt.Sprintf("Could not read dashboard preview at %s: %s", source, pathErrMsg(err))

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

		// Log the detailed path error server-side; return only the OS message.
		log.Printf("[dashboards] read %s: %v", r.specPath, err)
		resp.Message = fmt.Sprintf("Could not read dashboard preview at %s: %s", source, pathErrMsg(err))

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
	// totalDataPoints tracks the build-wide datapoint count across all resolved
	// groups. Once it reaches maxResponseDataPoints, further groups are returned
	// without datapoints to keep the JSON payload bounded.
	totalDataPoints := 0

	for _, g := range spec.Groups {
		pg := PreviewGroup{Name: g.Name, Description: g.Description, Dashboards: []PreviewDashboard{}}

		for _, d := range g.Dashboards {
			pd := PreviewDashboard{Name: d.Name, Description: d.Description, Panels: []PreviewPanel{}}

			for _, c := range d.Charts {
				pd.Panels = append(pd.Panels, r.resolvePanel(c, points, &resolved, &totalDataPoints))
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
// report their query/placement but skip the store resolution. totalDataPoints
// is the build-wide datapoint accumulator; groups are stripped of their points
// once the budget is reached.
func (r *Resolver) resolvePanel(c SpecChart, points []store.MetricDataPoint, resolved, totalDataPoints *int) PreviewPanel {
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

	// Apply the build-wide datapoint budget. Groups that would push the total
	// over the limit are included in the response (so the panel shows as
	// matched) but their DataPoints slice is trimmed to zero.
	for i := range groups {
		dp := groups[i].DataPoints
		if *totalDataPoints >= maxResponseDataPoints {
			groups[i].DataPoints = nil
		} else {
			remaining := maxResponseDataPoints - *totalDataPoints
			if len(dp) > remaining {
				groups[i].DataPoints = dp[:remaining]
				*totalDataPoints += remaining
			} else {
				*totalDataPoints += len(dp)
			}
		}
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

	groups = applyDimensionFilters(groups, q.Filters, q.NegatedFilters)

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

// applyDimensionFilters narrows resolved groups by positive and negated filters,
// skipping the service dimension (already applied by the store query). A group
// is kept when at least one of its data points satisfies all positive filters
// AND fails all negated exclusions on either its own attributes or its resource
// attributes (case-insensitive). Positive filters use OR-semantics per key.
func applyDimensionFilters(groups []store.MetricGroup, filters, negated map[string][]string) []store.MetricGroup {
	extra := make(map[string][]string)
	for k, vs := range filters {
		if isServiceKey(k) {
			continue
		}
		extra[k] = vs
	}

	negExtra := make(map[string][]string)
	for k, vs := range negated {
		if isServiceKey(k) {
			continue
		}
		negExtra[k] = vs
	}

	if len(extra) == 0 && len(negExtra) == 0 {
		return groups
	}

	kept := make([]store.MetricGroup, 0, len(groups))

	for _, g := range groups {
		matchedPoints := make([]store.MetricDataPoint, 0, len(g.DataPoints))

		for _, dp := range g.DataPoints {
			if dataPointMatches(dp, extra, negExtra) {
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

func dataPointMatches(dp store.MetricDataPoint, filters, negated map[string][]string) bool {
	for k, wantVals := range filters {
		if !attrMatchesAny(dp.Attributes, k, wantVals) && !attrMatchesAny(dp.Resource.Attributes, k, wantVals) {
			return false
		}
	}
	for k, excludeVals := range negated {
		if attrMatchesAny(dp.Attributes, k, excludeVals) || attrMatchesAny(dp.Resource.Attributes, k, excludeVals) {
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
