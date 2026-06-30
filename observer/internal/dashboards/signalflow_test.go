package dashboards

import "testing"

func TestParseProgramText(t *testing.T) { //nolint:gocognit,revive // table-driven test with 11 cases; complexity is inherent
	tests := []struct {
		name        string
		program     string
		wantMetric  string
		wantFilters map[string]string
		wantAgg     string
		wantPct     *float64
		wantErr     bool
	}{
		{
			name:        "percentile latency",
			program:     "data('http.server.request.duration', filter=filter('service.name','checkout')).percentile(pct=99).publish(label='p99')",
			wantMetric:  "http.server.request.duration",
			wantFilters: map[string]string{"service.name": "checkout"},
			wantAgg:     "percentile",
			wantPct:     floatPtr(99),
		},
		{
			name:        "sum rate",
			program:     "data('http.server.request.count', filter=filter('service.name','checkout')).sum().publish()",
			wantMetric:  "http.server.request.count",
			wantFilters: map[string]string{"service.name": "checkout"},
			wantAgg:     "sum",
		},
		{
			name:        "mean gauge",
			program:     "data('process.runtime.memory').mean().publish()",
			wantMetric:  "process.runtime.memory",
			wantFilters: map[string]string{},
			wantAgg:     "mean",
		},
		{
			name:        "count agg",
			program:     "data('events.total').count().publish()",
			wantMetric:  "events.total",
			wantFilters: map[string]string{},
			wantAgg:     "count",
		},
		{
			name:       "two filters AND-combined",
			program:    "data('http.server.request.duration', filter=filter('service.name','checkout') and filter('http.route','/cart')).percentile(pct=50).publish()",
			wantMetric: "http.server.request.duration",
			wantFilters: map[string]string{
				"service.name": "checkout",
				"http.route":   "/cart",
			},
			wantAgg: "percentile",
			wantPct: floatPtr(50),
		},
		{
			name:        "no aggregation raw data",
			program:     "data('cpu.utilization').publish()",
			wantMetric:  "cpu.utilization",
			wantFilters: map[string]string{},
			wantAgg:     "",
		},
		{
			name:        "unresolved variable filter is skipped",
			program:     "data('http.server.request.duration', filter=filter('service.name','${var.service_name}')).percentile(pct=95).publish()",
			wantMetric:  "http.server.request.duration",
			wantFilters: map[string]string{},
			wantAgg:     "percentile",
			wantPct:     floatPtr(95),
		},
		{
			name:        "empty filter value is skipped",
			program:     "data('m', filter=filter('env','')).sum().publish()",
			wantMetric:  "m",
			wantFilters: map[string]string{},
			wantAgg:     "sum",
		},
		{
			name:    "no data call yields parse error",
			program: "const(42).publish()",
			wantErr: true,
		},
		{
			name:        "whitespace variants",
			program:     "data( 'http.requests' ,  filter = filter( 'service.name' , 'api' ) ).mean( ).publish()",
			wantMetric:  "http.requests",
			wantFilters: map[string]string{"service.name": "api"},
			wantAgg:     "mean",
		},
		{
			name:        "percentile takes precedence over agg hints",
			program:     "data('lat').sum().percentile(pct=99.9).publish()",
			wantMetric:  "lat",
			wantFilters: map[string]string{},
			wantAgg:     "percentile",
			wantPct:     floatPtr(99.9),
		},
		{
			// m3: negated filter must not be captured as a positive constraint.
			name:        "not filter is skipped",
			program:     "data('m', filter=not filter('env','prod') and filter('service.name','api')).sum().publish()",
			wantMetric:  "m",
			wantFilters: map[string]string{"service.name": "api"},
			wantAgg:     "sum",
		},
		{
			// m3: multi-value filter is silently skipped (regex requires single value).
			name:        "multi-value filter is skipped",
			program:     "data('m', filter=filter('region','a','b') and filter('service.name','svc')).mean().publish()",
			wantMetric:  "m",
			wantFilters: map[string]string{"service.name": "svc"},
			wantAgg:     "mean",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := ParseProgramText(tt.program)

			if tt.wantErr {
				if got.ParseError == "" {
					t.Fatalf("expected ParseError, got none (metric=%q)", got.MetricName)
				}
				return
			}
			if got.ParseError != "" {
				t.Fatalf("unexpected ParseError: %s", got.ParseError)
			}
			if got.MetricName != tt.wantMetric {
				t.Errorf("metric = %q, want %q", got.MetricName, tt.wantMetric)
			}
			if len(got.Filters) != len(tt.wantFilters) {
				t.Errorf("filters = %v, want %v", got.Filters, tt.wantFilters)
			}
			for k, v := range tt.wantFilters {
				if got.Filters[k] != v {
					t.Errorf("filter[%q] = %q, want %q", k, got.Filters[k], v)
				}
			}

			if got.Aggregation != tt.wantAgg {
				t.Errorf("aggregation = %q, want %q", got.Aggregation, tt.wantAgg)
			}

			switch {
			case tt.wantPct == nil && got.Percentile != nil:
				t.Errorf("percentile = %v, want nil", *got.Percentile)
			case tt.wantPct != nil && got.Percentile == nil:
				t.Errorf("percentile = nil, want %v", *tt.wantPct)
			case tt.wantPct != nil && got.Percentile != nil && *got.Percentile != *tt.wantPct:
				t.Errorf("percentile = %v, want %v", *got.Percentile, *tt.wantPct)
			}
		})
	}
}

func floatPtr(f float64) *float64 { return &f }
