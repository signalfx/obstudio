package dashboards

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/signalfx/obstudio/observer/internal/store"
)

// writeSpec marshals a SpecFile into a temp sidecar and returns its path.
func writeSpec(t *testing.T, spec SpecFile) string {
	t.Helper()
	dir := t.TempDir()
	path := filepath.Join(dir, "dashboards.preview.json")
	raw, err := json.Marshal(spec)
	if err != nil {
		t.Fatalf("marshal spec: %v", err)
	}

	if err := os.WriteFile(path, raw, 0o600); err != nil {
		t.Fatalf("write spec: %v", err)
	}
	return path
}

// seededStore returns a store carrying one metric point per (name, service, attrs).
func seededStore(t *testing.T, points []store.MetricDataPoint) *store.Store {
	t.Helper()
	s := store.New()
	s.AddMetricsForConnection("", points)
	return s
}

func metricPoint(name, service string, value float64, attrs map[string]any) store.MetricDataPoint {
	if attrs == nil {
		attrs = map[string]any{}
	}
	return store.MetricDataPoint{
		Name:       name,
		Type:       "gauge",
		Unit:       "1",
		Timestamp:  time.Now(),
		Value:      value,
		Attributes: attrs,
		Resource:   store.Resource{ServiceName: service, Attributes: map[string]any{}},
		Scope:      store.Scope{Name: "test-scope"},
	}
}

func TestBuildMissingSpec(t *testing.T) {
	s := store.New()
	// Point at a path that does not exist.
	r := NewResolver(s, Config{SpecPath: filepath.Join(t.TempDir(), "nope.json")})

	resp := r.Build()

	if resp.Available {
		t.Errorf("expected available=false for missing spec")
	}

	if !resp.Approximate {
		t.Errorf("expected approximate=true always")
	}
	if resp.Message == "" {
		t.Errorf("expected an actionable message for missing spec")
	}
	if resp.Source == "" {
		t.Errorf("expected source path to be set")
	}
}

func TestBuildMalformedJSON(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "dashboards.preview.json")
	if err := os.WriteFile(path, []byte("{ not json"), 0o600); err != nil {
		t.Fatalf("write: %v", err)
	}
	r := NewResolver(store.New(), Config{SpecPath: path})

	resp := r.Build()

	if resp.Available {
		t.Errorf("expected available=false for malformed JSON")
	}
	if resp.Message == "" {
		t.Errorf("expected a message describing the JSON error")
	}
}

func TestBuildMatchedPanel(t *testing.T) {
	s := seededStore(t, []store.MetricDataPoint{
		metricPoint("http.server.request.duration", "checkout", 42, nil),
	})
	spec := SpecFile{
		SchemaVersion: 1,
		GeneratedAt:   "2026-01-01T00:00:00Z",
		Groups: []SpecGroup{{
			Name: "checkout",
			Dashboards: []SpecDashboard{{
				Name: "Checkout RED",
				Charts: []SpecChart{{
					Label:       "p99_latency",
					Title:       "P99 Latency",
					ChartType:   "time_series",
					ProgramText: "data('http.server.request.duration', filter=filter('service.name','checkout')).percentile(pct=99).publish()",
					Layout:      SpecLayout{Column: 0, Row: 0, Width: 6, Height: 3},
				}},
			}},
		}},
	}
	r := NewResolver(s, Config{SpecPath: writeSpec(t, spec)})

	resp := r.Build()

	if !resp.Available {
		t.Fatalf("expected available=true")
	}
	if resp.GeneratedAt != "2026-01-01T00:00:00Z" {
		t.Errorf("generatedAt = %q, want passthrough", resp.GeneratedAt)
	}
	panel := resp.Groups[0].Dashboards[0].Panels[0]

	if !panel.Matched {
		t.Errorf("expected panel matched=true (metric is in the store)")
	}

	if panel.Query == nil || panel.Query.MetricName != "http.server.request.duration" {
		t.Errorf("expected parsed metric name, got %+v", panel.Query)
	}
	if len(panel.Metrics) == 0 {
		t.Errorf("expected resolved metric groups")
	}
}

func TestBuildUnmatchedPanel(t *testing.T) {
	// Store has a different metric than the panel targets.
	s := seededStore(t, []store.MetricDataPoint{
		metricPoint("some.other.metric", "checkout", 1, nil),
	})
	spec := SpecFile{
		SchemaVersion: 1,
		Groups: []SpecGroup{{
			Name: "checkout",
			Dashboards: []SpecDashboard{{
				Name: "Checkout RED",
				Charts: []SpecChart{{
					Label:       "p99_latency",
					ChartType:   "time_series",
					ProgramText: "data('http.server.request.duration', filter=filter('service.name','checkout')).percentile(pct=99).publish()",
					Layout:      SpecLayout{Width: 6, Height: 3},
				}},
			}},
		}},
	}
	r := NewResolver(s, Config{SpecPath: writeSpec(t, spec)})

	panel := r.Build().Groups[0].Dashboards[0].Panels[0]

	if panel.Matched {
		t.Errorf("expected matched=false when no local series matches")
	}

	if panel.Query == nil || panel.Query.MetricName != "http.server.request.duration" {
		t.Errorf("expected the parsed (unmatched) metric to still be reported")
	}
}

func TestBuildDimensionFilterNarrows(t *testing.T) {
	// Two series for the same metric+service, distinguished by an attribute.
	s := seededStore(t, []store.MetricDataPoint{
		metricPoint("http.server.request.duration", "checkout", 10, map[string]any{"http.route": "/cart"}),
		metricPoint("http.server.request.duration", "checkout", 20, map[string]any{"http.route": "/pay"}),
	})
	spec := SpecFile{
		SchemaVersion: 1,
		Groups: []SpecGroup{{
			Name: "checkout",
			Dashboards: []SpecDashboard{{
				Name: "Checkout RED",
				Charts: []SpecChart{{
					Label:       "cart_latency",
					ChartType:   "time_series",
					ProgramText: "data('http.server.request.duration', filter=filter('service.name','checkout') and filter('http.route','/cart')).percentile(pct=99).publish()",
					Layout:      SpecLayout{Width: 6, Height: 3},
				}},
			}},
		}},
	}
	r := NewResolver(s, Config{SpecPath: writeSpec(t, spec)})

	panel := r.Build().Groups[0].Dashboards[0].Panels[0]

	if !panel.Matched {
		t.Fatalf("expected matched=true after dimension narrowing")
	}
	// Only the /cart data points should survive the post-filter.
	for _, g := range panel.Metrics {
		for _, dp := range g.DataPoints {
			if route := dp.Attributes["http.route"]; route != "/cart" {
				t.Errorf("expected only http.route=/cart points, got %v", route)
			}
		}
	}
}

func TestBuildTextPanelPassthrough(t *testing.T) {
	text := "## Runbook\nSee the wiki."
	spec := SpecFile{
		SchemaVersion: 1,
		Groups: []SpecGroup{{
			Name: "checkout",
			Dashboards: []SpecDashboard{{
				Name: "Checkout RED",
				Charts: []SpecChart{{
					Label:     "notes",
					ChartType: "text",
					Text:      &text,
					Layout:    SpecLayout{Width: 12, Height: 2},
				}},
			}},
		}},
	}
	r := NewResolver(store.New(), Config{SpecPath: writeSpec(t, spec)})

	panel := r.Build().Groups[0].Dashboards[0].Panels[0]

	if panel.Text == nil || *panel.Text != text {
		t.Errorf("expected text passthrough, got %v", panel.Text)
	}
	if panel.Query != nil {
		t.Errorf("text panel should carry no parsed query")
	}
	if panel.Matched {
		t.Errorf("text panel should not be marked matched")
	}
}

func TestBuildParseErrorPanel(t *testing.T) {
	spec := SpecFile{
		SchemaVersion: 1,
		Groups: []SpecGroup{{
			Name: "checkout",
			Dashboards: []SpecDashboard{{
				Name: "Checkout RED",
				Charts: []SpecChart{{
					Label:       "broken",
					ChartType:   "time_series",
					ProgramText: "const(42).publish()",
					Layout:      SpecLayout{Width: 6, Height: 3},
				}},
			}},
		}},
	}
	r := NewResolver(store.New(), Config{SpecPath: writeSpec(t, spec)})

	panel := r.Build().Groups[0].Dashboards[0].Panels[0]

	if panel.Query == nil || panel.Query.ParseError == "" {
		t.Errorf("expected a ParseError for a program with no data() call")
	}
	if panel.Matched {
		t.Errorf("a parse-error panel cannot be matched")
	}
}

func TestNewResolverDefaultsSpecPath(t *testing.T) {
	r := NewResolver(store.New(), Config{})
	// Build should not panic; it reports the default path in the message/source.
	resp := r.Build()
	if resp.Source == "" {
		t.Errorf("expected a resolved default source path")
	}
}

// TestBuildConflictingServiceAlias verifies that a program with both
// service.name and sf_service set to different values yields Matched=false
// without a store query.
func TestBuildConflictingServiceAlias(t *testing.T) {
	s := seededStore(t, []store.MetricDataPoint{
		metricPoint("http.server.request.duration", "checkout", 42, nil),
	})
	spec := SpecFile{
		SchemaVersion: 1,
		Groups: []SpecGroup{{
			Name: "g",
			Dashboards: []SpecDashboard{{
				Name: "d",
				Charts: []SpecChart{{
					Label:     "conflict",
					ChartType: "time_series",
					// service.name=checkout AND sf_service=legacy-checkout → contradiction
					ProgramText: "data('http.server.request.duration', filter=filter('service.name','checkout') and filter('sf_service','legacy-checkout')).sum().publish()",
					Layout:      SpecLayout{Width: 6, Height: 3},
				}},
			}},
		}},
	}
	r := NewResolver(s, Config{SpecPath: writeSpec(t, spec)})

	panel := r.Build().Groups[0].Dashboards[0].Panels[0]

	if panel.Matched {
		t.Errorf("expected Matched=false for conflicting service.name/sf_service pair")
	}
	if len(panel.Metrics) > 0 {
		t.Errorf("expected no metrics returned for conflicting service alias")
	}
}

// TestBuildOTLPArrayAttributeMatch verifies that a metric attribute stored as
// []any (OTLP array ingest) is matched by a scalar SignalFlow filter value when
// the string representation equals the scalar (json.Marshal vs fmt.Sprintf fix).
func TestBuildOTLPArrayAttributeMatch(t *testing.T) {
	// Simulate a metric whose "region" attribute was ingested as a single-element
	// OTLP array and is stored as []any{"us-east"}.
	s := seededStore(t, []store.MetricDataPoint{
		metricPoint("req.duration", "svc", 10, map[string]any{"region": []any{"us-east"}}),
	})
	spec := SpecFile{
		SchemaVersion: 1,
		Groups: []SpecGroup{{
			Name: "g",
			Dashboards: []SpecDashboard{{
				Name: "d",
				Charts: []SpecChart{{
					Label:     "region_panel",
					ChartType: "time_series",
					// The filter value is the JSON-serialized form of the array element.
					ProgramText: `data('req.duration', filter=filter('service.name','svc') and filter('region','["us-east"]')).mean().publish()`,
					Layout:      SpecLayout{Width: 6, Height: 3},
				}},
			}},
		}},
	}
	r := NewResolver(s, Config{SpecPath: writeSpec(t, spec)})

	panel := r.Build().Groups[0].Dashboards[0].Panels[0]

	if !panel.Matched {
		t.Errorf("expected Matched=true: []any{\"us-east\"} should match filter value [\"us-east\"] via json.Marshal serialization")
	}
}

// TestBuildMultiValueFilterMatchesAny verifies OR-semantics: a panel with a
// multi-value filter('region','us1','us2') matches a series whose region is
// 'us1', even though 'us2' is not present.
func TestBuildMultiValueFilterMatchesAny(t *testing.T) {
	s := seededStore(t, []store.MetricDataPoint{
		metricPoint("req.duration", "svc", 10, map[string]any{"region": "us1"}),
		metricPoint("req.duration", "svc", 20, map[string]any{"region": "eu1"}),
	})
	spec := SpecFile{
		SchemaVersion: 1,
		Groups: []SpecGroup{{
			Name: "g",
			Dashboards: []SpecDashboard{{
				Name: "d",
				Charts: []SpecChart{{
					Label:       "region_or",
					ChartType:   "time_series",
					ProgramText: "data('req.duration', filter=filter('service.name','svc') and filter('region','us1','us2')).mean().publish()",
					Layout:      SpecLayout{Width: 6, Height: 3},
				}},
			}},
		}},
	}
	r := NewResolver(s, Config{SpecPath: writeSpec(t, spec)})

	panel := r.Build().Groups[0].Dashboards[0].Panels[0]

	if !panel.Matched {
		t.Fatalf("expected Matched=true: region=us1 satisfies filter('region','us1','us2')")
	}
	// eu1 series must be excluded.
	for _, g := range panel.Metrics {
		for _, dp := range g.DataPoints {
			if dp.Attributes["region"] == "eu1" {
				t.Errorf("eu1 series should not survive the multi-value filter")
			}
		}
	}
}

// TestBuildDataPointCountSyncedAfterFilter verifies that DataPointCount on a
// returned MetricGroup equals len(DataPoints) after applyDimensionFilters trims
// the data points (finding #7).
func TestBuildDataPointCountSyncedAfterFilter(t *testing.T) {
	s := seededStore(t, []store.MetricDataPoint{
		metricPoint("m", "svc", 1, map[string]any{"env": "prod"}),
		metricPoint("m", "svc", 2, map[string]any{"env": "staging"}),
		metricPoint("m", "svc", 3, map[string]any{"env": "prod"}),
	})
	spec := SpecFile{
		SchemaVersion: 1,
		Groups: []SpecGroup{{
			Name: "g",
			Dashboards: []SpecDashboard{{
				Name: "d",
				Charts: []SpecChart{{
					Label:       "prod_only",
					ChartType:   "time_series",
					ProgramText: "data('m', filter=filter('service.name','svc') and filter('env','prod')).mean().publish()",
					Layout:      SpecLayout{Width: 6, Height: 3},
				}},
			}},
		}},
	}
	r := NewResolver(s, Config{SpecPath: writeSpec(t, spec)})

	panel := r.Build().Groups[0].Dashboards[0].Panels[0]

	if !panel.Matched {
		t.Fatalf("expected matched=true")
	}
	for _, g := range panel.Metrics {
		if g.DataPointCount != len(g.DataPoints) {
			t.Errorf("DataPointCount=%d but len(DataPoints)=%d: they must stay in sync after filtering",
				g.DataPointCount, len(g.DataPoints))
		}
	}
}

// TestBuildMultiValueServiceFilterExcludesUnrelated verifies that a multi-value
// service filter (filter('service.name','checkout','payments')) excludes a third
// unrelated service in the store (finding F2). Before the fix, a multi-value
// service filter left svcArg="" so the store returned ALL services and
// applyDimensionFilters skipped service keys, leaking billing into the panel.
func TestBuildMultiValueServiceFilterExcludesUnrelated(t *testing.T) {
	s := seededStore(t, []store.MetricDataPoint{
		metricPoint("req.duration", "checkout", 10, nil),
		metricPoint("req.duration", "payments", 20, nil),
		metricPoint("req.duration", "billing", 30, nil),
	})
	spec := SpecFile{
		SchemaVersion: 1,
		Groups: []SpecGroup{{
			Name: "g",
			Dashboards: []SpecDashboard{{
				Name: "d",
				Charts: []SpecChart{{
					Label:       "svc_or",
					ChartType:   "time_series",
					ProgramText: "data('req.duration', filter=filter('service.name','checkout','payments')).mean().publish()",
					Layout:      SpecLayout{Width: 6, Height: 3},
				}},
			}},
		}},
	}
	r := NewResolver(s, Config{SpecPath: writeSpec(t, spec)})

	panel := r.Build().Groups[0].Dashboards[0].Panels[0]

	if !panel.Matched {
		t.Fatalf("expected matched=true: checkout and payments are in the store")
	}
	sawCheckout, sawPayments := false, false
	for _, g := range panel.Metrics {
		switch g.ServiceName {
		case "checkout":
			sawCheckout = true
		case "payments":
			sawPayments = true
		case "billing":
			t.Errorf("billing must be excluded by the multi-value service filter")
		default:
			t.Errorf("unexpected service %q in resolved groups", g.ServiceName)
		}
	}
	if !sawCheckout || !sawPayments {
		t.Errorf("expected both checkout and payments groups, got checkout=%v payments=%v", sawCheckout, sawPayments)
	}
}

// TestBuildMultiValueServiceFilterMixedCase verifies the multi-value service
// constraint is case-insensitive against MetricGroup.ServiceName (finding
// F2/F5): a filter value 'CHECKOUT' matches a stored service 'checkout'.
func TestBuildMultiValueServiceFilterMixedCase(t *testing.T) {
	s := seededStore(t, []store.MetricDataPoint{
		metricPoint("req.duration", "checkout", 10, nil),
		metricPoint("req.duration", "billing", 30, nil),
	})
	spec := SpecFile{
		SchemaVersion: 1,
		Groups: []SpecGroup{{
			Name: "g",
			Dashboards: []SpecDashboard{{
				Name: "d",
				Charts: []SpecChart{{
					Label:       "svc_or_case",
					ChartType:   "time_series",
					ProgramText: "data('req.duration', filter=filter('service.name','CHECKOUT','PAYMENTS')).mean().publish()",
					Layout:      SpecLayout{Width: 6, Height: 3},
				}},
			}},
		}},
	}
	r := NewResolver(s, Config{SpecPath: writeSpec(t, spec)})

	panel := r.Build().Groups[0].Dashboards[0].Panels[0]

	if !panel.Matched {
		t.Fatalf("expected matched=true: CHECKOUT must match stored checkout case-insensitively")
	}
	for _, g := range panel.Metrics {
		if g.ServiceName == "billing" {
			t.Errorf("billing must be excluded by the multi-value service filter")
		}
	}
}

// TestBuildNegatedServiceFilterExcludesService verifies that a negated service
// filter (not filter('service.name','billing')) drops the excluded service's
// groups from the result (finding H1). Before the fix, applyDimensionFilters
// skipped the service key on BOTH the positive and negated branches, so a
// negated service value was a silent no-op and billing leaked into the panel.
func TestBuildNegatedServiceFilterExcludesService(t *testing.T) {
	s := seededStore(t, []store.MetricDataPoint{
		metricPoint("req.duration", "checkout", 10, nil),
		metricPoint("req.duration", "payments", 20, nil),
		metricPoint("req.duration", "billing", 30, nil),
	})
	spec := SpecFile{
		SchemaVersion: 1,
		Groups: []SpecGroup{{
			Name: "g",
			Dashboards: []SpecDashboard{{
				Name: "d",
				Charts: []SpecChart{{
					Label:     "not_billing",
					ChartType: "time_series",
					// Exclude billing; checkout and payments must remain.
					ProgramText: "data('req.duration', filter=not filter('service.name','billing')).mean().publish()",
					Layout:      SpecLayout{Width: 6, Height: 3},
				}},
			}},
		}},
	}
	r := NewResolver(s, Config{SpecPath: writeSpec(t, spec)})

	panel := r.Build().Groups[0].Dashboards[0].Panels[0]

	if !panel.Matched {
		t.Fatalf("expected matched=true: checkout and payments survive the negated service filter")
	}
	sawCheckout, sawPayments := false, false
	for _, g := range panel.Metrics {
		switch g.ServiceName {
		case "checkout":
			sawCheckout = true
		case "payments":
			sawPayments = true
		case "billing":
			t.Errorf("billing must be excluded by the negated service filter")
		default:
			t.Errorf("unexpected service %q in resolved groups", g.ServiceName)
		}
	}
	if !sawCheckout || !sawPayments {
		t.Errorf("expected both checkout and payments groups, got checkout=%v payments=%v", sawCheckout, sawPayments)
	}
}

// TestBuildNegatedServiceFilterMixedCase verifies the negated service exclusion
// is case-insensitive against MetricGroup.ServiceName (finding H1): a negated
// value 'BILLING' still drops a stored service 'billing'.
func TestBuildNegatedServiceFilterMixedCase(t *testing.T) {
	s := seededStore(t, []store.MetricDataPoint{
		metricPoint("req.duration", "checkout", 10, nil),
		metricPoint("req.duration", "billing", 30, nil),
	})
	spec := SpecFile{
		SchemaVersion: 1,
		Groups: []SpecGroup{{
			Name: "g",
			Dashboards: []SpecDashboard{{
				Name: "d",
				Charts: []SpecChart{{
					Label:       "not_billing_case",
					ChartType:   "time_series",
					ProgramText: "data('req.duration', filter=not filter('sf_service','BILLING')).mean().publish()",
					Layout:      SpecLayout{Width: 6, Height: 3},
				}},
			}},
		}},
	}
	r := NewResolver(s, Config{SpecPath: writeSpec(t, spec)})

	panel := r.Build().Groups[0].Dashboards[0].Panels[0]

	if !panel.Matched {
		t.Fatalf("expected matched=true: checkout survives the negated service filter")
	}
	for _, g := range panel.Metrics {
		if strings.EqualFold(g.ServiceName, "billing") {
			t.Errorf("billing must be excluded by the negated service filter (case-insensitive)")
		}
	}
}

// TestBuildFilterBeforeCap verifies that dimension filtering runs before the
// display cap so a matching series in a group beyond the cap is not dropped
// (finding F4). The store would otherwise truncate to maxResolvedGroups before
// applyDimensionFilters and falsely report the panel unmatched.
func TestBuildFilterBeforeCap(t *testing.T) {
	var points []store.MetricDataPoint
	// The matching group is ingested FIRST so it is the oldest point. The store
	// query iterates newest-first, so the matching group sorts to the END of the
	// group order and lands beyond maxResolvedGroups. If the store cap is applied
	// before dimension filtering (the bug), this group is truncated away and the
	// panel falsely reports unmatched.
	points = append(points, metricPoint("m", "svc-match", 999, map[string]any{"env": "target"}))
	// Then more than maxResolvedGroups distinct groups (one service each) that do
	// NOT match the env=target filter.
	for i := 0; i < maxResolvedGroups+20; i++ {
		svc := "svc-noise-" + string(rune('a'+i%26)) + string(rune('a'+i/26))
		points = append(points, metricPoint("m", svc, float64(i), map[string]any{"env": "other"}))
	}

	s := seededStore(t, points)
	spec := SpecFile{
		SchemaVersion: 1,
		Groups: []SpecGroup{{
			Name: "g",
			Dashboards: []SpecDashboard{{
				Name: "d",
				Charts: []SpecChart{{
					Label:       "env_target",
					ChartType:   "time_series",
					ProgramText: "data('m', filter=filter('env','target')).mean().publish()",
					Layout:      SpecLayout{Width: 6, Height: 3},
				}},
			}},
		}},
	}
	r := NewResolver(s, Config{SpecPath: writeSpec(t, spec)})

	panel := r.Build().Groups[0].Dashboards[0].Panels[0]

	if !panel.Matched {
		t.Fatalf("expected matched=true: env=target group must survive even though it is beyond the display cap")
	}
	if len(panel.Metrics) > maxResolvedGroups {
		t.Errorf("expected at most %d groups after cap, got %d", maxResolvedGroups, len(panel.Metrics))
	}
	for _, g := range panel.Metrics {
		for _, dp := range g.DataPoints {
			if dp.Attributes["env"] != "target" {
				t.Errorf("expected only env=target points, got %v", dp.Attributes["env"])
			}
		}
	}
}

// TestBuildFilterBeyondQueryFanout verifies that dimension filtering is not
// defeated by the store-side group cap (metricGroupQueryFanout) when a metric
// fans out into more distinct groups than the old 1000-group fanout (R1-207).
// The single env=target group is ingested FIRST (oldest), so the store's
// newest-first group order sorts it LAST — beyond the previous 1000-group cap,
// which would truncate it away before applyDimensionFilters and falsely report
// the panel unmatched. With the fanout raised to the ring capacity, the group
// survives.
func TestBuildFilterBeyondQueryFanout(t *testing.T) {
	var points []store.MetricDataPoint
	// Matching group first => oldest => sorts last in newest-first group order.
	points = append(points, metricPoint("m", "svc-match", 999, map[string]any{"env": "target"}))
	// More than the old metricGroupQueryFanout (1000) distinct non-matching groups.
	const noise = 1200
	for i := 0; i < noise; i++ {
		svc := "svc-noise-" + string(rune('a'+i%26)) + string(rune('a'+(i/26)%26)) + string(rune('a'+i/676))
		points = append(points, metricPoint("m", svc, float64(i), map[string]any{"env": "other"}))
	}

	s := seededStore(t, points)
	spec := SpecFile{
		SchemaVersion: 1,
		Groups: []SpecGroup{{
			Name: "g",
			Dashboards: []SpecDashboard{{
				Name: "d",
				Charts: []SpecChart{{
					Label:       "env_target",
					ChartType:   "time_series",
					ProgramText: "data('m', filter=filter('env','target')).mean().publish()",
					Layout:      SpecLayout{Width: 6, Height: 3},
				}},
			}},
		}},
	}
	r := NewResolver(s, Config{SpecPath: writeSpec(t, spec)})

	panel := r.Build().Groups[0].Dashboards[0].Panels[0]

	if !panel.Matched {
		t.Fatalf("expected matched=true: env=target group must survive even though it sorts beyond the old 1000-group fanout")
	}
	for _, g := range panel.Metrics {
		for _, dp := range g.DataPoints {
			if dp.Attributes["env"] != "target" {
				t.Errorf("expected only env=target points, got %v", dp.Attributes["env"])
			}
		}
	}
}

// TestBuildPanelCap verifies that the number of panels resolved against the
// store per request is capped (finding F6): panels beyond maxPanelsPerBuild
// report their parsed query but skip store resolution.
func TestBuildPanelCap(t *testing.T) {
	prev := maxPanelsPerBuild
	maxPanelsPerBuild = 2
	defer func() { maxPanelsPerBuild = prev }()

	s := seededStore(t, []store.MetricDataPoint{
		metricPoint("m", "svc", 1, nil),
	})

	chart := func(label string) SpecChart {
		return SpecChart{
			Label:       label,
			ChartType:   "time_series",
			ProgramText: "data('m', filter=filter('service.name','svc')).mean().publish()",
			Layout:      SpecLayout{Width: 6, Height: 3},
		}
	}
	spec := SpecFile{
		SchemaVersion: 1,
		Groups: []SpecGroup{{
			Name: "g",
			Dashboards: []SpecDashboard{{
				Name:   "d",
				Charts: []SpecChart{chart("p0"), chart("p1"), chart("p2"), chart("p3")},
			}},
		}},
	}
	r := NewResolver(s, Config{SpecPath: writeSpec(t, spec)})

	panels := r.Build().Groups[0].Dashboards[0].Panels
	matched := 0
	for _, p := range panels {
		if p.Query == nil {
			t.Errorf("every non-text panel should still report its parsed query")
		}
		if p.Matched {
			matched++
		}
	}
	if matched != 2 {
		t.Errorf("expected exactly 2 panels resolved against the store (cap), got %d", matched)
	}
}

// TestBuildSourceHidesAbsolutePath verifies the cross-origin PreviewResponse
// does not disclose the absolute resolved sidecar path in Source or Message
// (finding F11).
func TestBuildSourceHidesAbsolutePath(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "dashboards.preview.json")
	if err := os.WriteFile(path, []byte("{ not json"), 0o600); err != nil {
		t.Fatalf("write: %v", err)
	}
	r := NewResolver(store.New(), Config{SpecPath: path})

	resp := r.Build()

	if resp.Source != "dashboards.preview.json" {
		t.Errorf("Source = %q, want basename only", resp.Source)
	}
	if filepath.IsAbs(resp.Source) {
		t.Errorf("Source must not be an absolute path: %q", resp.Source)
	}
	if strings.Contains(resp.Source, dir) || strings.Contains(resp.Message, dir) {
		t.Errorf("response must not contain the absolute repo path %q (source=%q message=%q)", dir, resp.Source, resp.Message)
	}
}

// TestBuildOversizedFileRejected verifies that a sidecar exceeding the size cap
// is rejected without unmarshalling (finding P1).
func TestBuildOversizedFileRejected(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "dashboards.preview.json")
	big := make([]byte, maxSpecFileBytes+1)
	for i := range big {
		big[i] = ' '
	}
	if err := os.WriteFile(path, big, 0o600); err != nil {
		t.Fatalf("write: %v", err)
	}
	r := NewResolver(store.New(), Config{SpecPath: path})

	resp := r.Build()

	if resp.Available {
		t.Errorf("expected available=false for oversized sidecar")
	}
	if !strings.Contains(strings.ToLower(resp.Message), "too large") {
		t.Errorf("expected an oversize message, got %q", resp.Message)
	}
}
