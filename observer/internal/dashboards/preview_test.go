package dashboards

import (
	"encoding/json"
	"os"
	"path/filepath"
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
	r := NewResolver(s, filepath.Join(t.TempDir(), "nope.json"))

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
	r := NewResolver(store.New(), path)

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
	r := NewResolver(s, writeSpec(t, spec))

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
	r := NewResolver(s, writeSpec(t, spec))

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
	r := NewResolver(s, writeSpec(t, spec))

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
	r := NewResolver(store.New(), writeSpec(t, spec))

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
	r := NewResolver(store.New(), writeSpec(t, spec))

	panel := r.Build().Groups[0].Dashboards[0].Panels[0]

	if panel.Query == nil || panel.Query.ParseError == "" {
		t.Errorf("expected a ParseError for a program with no data() call")
	}
	if panel.Matched {
		t.Errorf("a parse-error panel cannot be matched")
	}
}

func TestNewResolverDefaultsSpecPath(t *testing.T) {
	r := NewResolver(store.New(), "")
	// Build should not panic; it reports the default path in the message/source.
	resp := r.Build()
	if resp.Source == "" {
		t.Errorf("expected a resolved default source path")
	}
}
