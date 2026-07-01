package dashboards

import (
	"slices"
	"strings"
	"testing"
)

func TestParseProgramText(t *testing.T) { //nolint:gocognit,revive // table-driven test; complexity is inherent
	tests := []struct {
		name        string
		program     string
		wantMetric  string
		wantFilters map[string][]string
		wantNegated map[string][]string
		wantIgnored []string
		wantAgg     string
		wantPct     *float64
		wantErr     bool
	}{
		{
			name:        "percentile latency",
			program:     "data('http.server.request.duration', filter=filter('service.name','checkout')).percentile(pct=99).publish(label='p99')",
			wantMetric:  "http.server.request.duration",
			wantFilters: map[string][]string{"service.name": {"checkout"}},
			wantAgg:     "percentile",
			wantPct:     floatPtr(99),
		},
		{
			name:        "sum rate",
			program:     "data('http.server.request.count', filter=filter('service.name','checkout')).sum().publish()",
			wantMetric:  "http.server.request.count",
			wantFilters: map[string][]string{"service.name": {"checkout"}},
			wantAgg:     "sum",
		},
		{
			name:        "mean gauge",
			program:     "data('process.runtime.memory').mean().publish()",
			wantMetric:  "process.runtime.memory",
			wantFilters: map[string][]string{},
			wantAgg:     "mean",
		},
		{
			name:        "count agg",
			program:     "data('events.total').count().publish()",
			wantMetric:  "events.total",
			wantFilters: map[string][]string{},
			wantAgg:     "count",
		},
		{
			name:       "two filters AND-combined",
			program:    "data('http.server.request.duration', filter=filter('service.name','checkout') and filter('http.route','/cart')).percentile(pct=50).publish()",
			wantMetric: "http.server.request.duration",
			wantFilters: map[string][]string{
				"service.name": {"checkout"},
				"http.route":   {"/cart"},
			},
			wantAgg: "percentile",
			wantPct: floatPtr(50),
		},
		{
			name:        "no aggregation raw data",
			program:     "data('cpu.utilization').publish()",
			wantMetric:  "cpu.utilization",
			wantFilters: map[string][]string{},
			wantAgg:     "",
		},
		{
			name:        "unresolved variable filter is skipped",
			program:     "data('http.server.request.duration', filter=filter('service.name','${var.service_name}')).percentile(pct=95).publish()",
			wantMetric:  "http.server.request.duration",
			wantFilters: map[string][]string{},
			wantAgg:     "percentile",
			wantPct:     floatPtr(95),
		},
		{
			name:        "empty filter value is skipped",
			program:     "data('m', filter=filter('env','')).sum().publish()",
			wantMetric:  "m",
			wantFilters: map[string][]string{},
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
			wantFilters: map[string][]string{"service.name": {"api"}},
			wantAgg:     "mean",
		},
		{
			name:        "percentile takes precedence over agg hints",
			program:     "data('lat').sum().percentile(pct=99.9).publish()",
			wantMetric:  "lat",
			wantFilters: map[string][]string{},
			wantAgg:     "percentile",
			wantPct:     floatPtr(99.9),
		},
		{
			// negated filter must not be captured as a positive constraint,
			// and its value must appear in NegatedFilters.
			name:        "not filter is skipped (single space)",
			program:     "data('m', filter=not filter('env','prod') and filter('service.name','api')).sum().publish()",
			wantMetric:  "m",
			wantFilters: map[string][]string{"service.name": {"api"}},
			wantNegated: map[string][]string{"env": {"prod"}},
			wantAgg:     "sum",
		},
		{
			name:        "negated filter value captured in NegatedFilters",
			program:     "data('m', filter=not filter('env','prod')).sum().publish()",
			wantMetric:  "m",
			wantFilters: map[string][]string{},
			wantNegated: map[string][]string{"env": {"prod"}},
			wantAgg:     "sum",
		},
		{
			name:        "negated multi-value filter captured in NegatedFilters",
			program:     "data('m', filter=not filter('region','us-east','eu-west')).mean().publish()",
			wantMetric:  "m",
			wantFilters: map[string][]string{},
			wantNegated: map[string][]string{"region": {"us-east", "eu-west"}},
			wantAgg:     "mean",
		},
		{
			name:        "negated filter with templated value recorded as ignored",
			program:     "data('m', filter=not filter('env','${var.e}')).sum().publish()",
			wantMetric:  "m",
			wantFilters: map[string][]string{},
			wantIgnored: []string{"env"},
			wantAgg:     "sum",
		},
		{
			// multi-value filter is now parsed and OR-semantics applied.
			name:       "multi-value filter captured as OR slice",
			program:    "data('m', filter=filter('region','a','b') and filter('service.name','svc')).mean().publish()",
			wantMetric: "m",
			wantFilters: map[string][]string{
				"region":       {"a", "b"},
				"service.name": {"svc"},
			},
			wantAgg: "mean",
		},
		// New cases for negation robustness fixes.
		{
			name:        "not filter with 12+ spaces is still negated",
			program:     "data('m', filter=not            filter('env','prod') and filter('service.name','api')).sum().publish()",
			wantMetric:  "m",
			wantFilters: map[string][]string{"service.name": {"api"}},
			wantAgg:     "sum",
		},
		{
			name:        "not filter with newline between not and filter",
			program:     "data('m', filter=not\nfilter('env','prod') and filter('service.name','api')).sum().publish()",
			wantMetric:  "m",
			wantFilters: map[string][]string{"service.name": {"api"}},
			wantAgg:     "sum",
		},
		{
			name:        "identifier ending in 'not' does not suppress positive filter",
			program:     "data('m', filter=cannot filter('service.name','api')).sum().publish()",
			wantMetric:  "m",
			wantFilters: map[string][]string{"service.name": {"api"}},
			wantAgg:     "sum",
		},
		// F10: dropped template/empty filters are recorded in IgnoredFilters.
		{
			name:        "unresolved variable filter is recorded as ignored",
			program:     "data('http.server.request.duration', filter=filter('http.route','${var.route}')).percentile(pct=95).publish()",
			wantMetric:  "http.server.request.duration",
			wantFilters: map[string][]string{},
			wantIgnored: []string{"http.route"},
			wantAgg:     "percentile",
			wantPct:     floatPtr(95),
		},
		{
			name:        "empty filter value is recorded as ignored",
			program:     "data('m', filter=filter('env','')).sum().publish()",
			wantMetric:  "m",
			wantFilters: map[string][]string{},
			wantIgnored: []string{"env"},
			wantAgg:     "sum",
		},
		{
			name:        "multi-value filter with all templated values is recorded as ignored",
			program:     "data('m', filter=filter('region','${var.r1}','${var.r2}')).mean().publish()",
			wantMetric:  "m",
			wantFilters: map[string][]string{},
			wantIgnored: []string{"region"},
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
			for k, wantVals := range tt.wantFilters {
				gotVals := got.Filters[k]
				if len(gotVals) != len(wantVals) {
					t.Errorf("filter[%q] = %v, want %v", k, gotVals, wantVals)
					continue
				}
				for _, v := range wantVals {
					if !slices.Contains(gotVals, v) {
						t.Errorf("filter[%q] missing value %q (got %v)", k, v, gotVals)
					}
				}
			}

			if len(tt.wantIgnored) > 0 {
				for _, k := range tt.wantIgnored {
					if !slices.Contains(got.IgnoredFilters, k) {
						t.Errorf("expected %q in IgnoredFilters, got %v", k, got.IgnoredFilters)
					}
				}
			}

			for k, wantVals := range tt.wantNegated {
				gotVals := got.NegatedFilters[k]
				if len(gotVals) != len(wantVals) {
					t.Errorf("negatedFilter[%q] = %v, want %v", k, gotVals, wantVals)
					continue
				}
				for _, v := range wantVals {
					if !slices.Contains(gotVals, v) {
						t.Errorf("negatedFilter[%q] missing value %q (got %v)", k, v, gotVals)
					}
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

// TestParseProgramNotParenthesizedFilter verifies that a filter wrapped in a
// parenthesized group after "not" — "not (filter('env','prod'))" — is recognized
// as negated and therefore NOT applied as a positive constraint (R1-67). Before
// the fix the prefix ended in "(" so the word-boundary "not" check failed and
// env=prod was captured, inverting the panel's intent.
func TestParseProgramNotParenthesizedFilter(t *testing.T) {
	got := ParseProgramText("data('m', filter=not (filter('env','prod'))).sum().publish()")
	if got.ParseError != "" {
		t.Fatalf("unexpected ParseError: %s", got.ParseError)
	}
	if vals := got.Filters["env"]; len(vals) != 0 {
		t.Errorf("negated filter should not be applied, got Filters[env]=%v", vals)
	}
	if !slices.Contains(got.NegatedFilters["env"], "prod") {
		t.Errorf("expected env=prod in NegatedFilters, got %v", got.NegatedFilters)
	}
}

// TestParseProgramTemplatedThenPositiveSameKey verifies that when a key is first
// seen as a templated (ignored) filter and later as a positive filter, the key
// ends up in Filters and NOT in IgnoredFilters (R1-255). Before the fix the
// result was the contradictory Filters={env:[prod]} + IgnoredFilters=[env].
func TestParseProgramTemplatedThenPositiveSameKey(t *testing.T) {
	got := ParseProgramText("data('m', filter=filter('env','${var}') and filter('env','prod')).sum().publish()")
	if got.ParseError != "" {
		t.Fatalf("unexpected ParseError: %s", got.ParseError)
	}
	if vals := got.Filters["env"]; !slices.Contains(vals, "prod") {
		t.Errorf("expected env=prod applied, got Filters[env]=%v", vals)
	}
	if slices.Contains(got.IgnoredFilters, "env") {
		t.Errorf("env was applied, so it must not remain in IgnoredFilters, got %v", got.IgnoredFilters)
	}
}

// TestParseProgramMetadataDoesNotShadowMetric verifies that a metadata('foo')
// call does not shadow the real metric from a later data() call. Before the fix
// the unanchored `data\(` regex matched the "data(" substring inside
// "metadata('foo'", returning MetricName="foo" (R3-go-signalflow-13).
func TestParseProgramMetadataDoesNotShadowMetric(t *testing.T) {
	got := ParseProgramText("m = metadata('foo'); d = data('http.requests').sum().publish()")
	if got.ParseError != "" {
		t.Fatalf("unexpected ParseError: %s", got.ParseError)
	}
	if got.MetricName != "http.requests" {
		t.Errorf("metric = %q, want %q", got.MetricName, "http.requests")
	}
}

// TestParseProgramPureMetadataYieldsParseError verifies that a program with only
// a metadata() call (no data() call) is reported as unresolvable rather than
// treating "sf_service" as a metric (R3-go-signalflow-13).
func TestParseProgramPureMetadataYieldsParseError(t *testing.T) {
	got := ParseProgramText("metadata('sf_service').publish()")
	if got.ParseError == "" {
		t.Fatalf("expected ParseError for metadata-only program, got metric=%q", got.MetricName)
	}
}

// TestParseProgramDoubleParenNotFilter verifies that a filter wrapped in two
// parens after "not" — "not ((filter('env','prod')))" — is still recognized as
// negated. Before the fix the single optional-paren prefix regex failed on the
// second "(" and env=prod was captured (R3-go-signalflow-28).
func TestParseProgramDoubleParenNotFilter(t *testing.T) {
	got := ParseProgramText("data('m', filter=not ((filter('env','prod')))).sum().publish()")
	if got.ParseError != "" {
		t.Fatalf("unexpected ParseError: %s", got.ParseError)
	}
	if vals := got.Filters["env"]; len(vals) != 0 {
		t.Errorf("negated filter should not be applied, got Filters[env]=%v", vals)
	}
}

// TestParseProgramNotMultiFilterGroupAllNegated verifies that EVERY filter in a
// parenthesized negation group is treated as negated, not just the first — so
// "not (filter('env','prod') and filter('region','us'))" applies neither
// constraint. Before the fix only the first filter of the group was negated and
// region=us was applied as a positive constraint, inverting the panel's intent
// (R3-go-preview-28).
func TestParseProgramNotMultiFilterGroupAllNegated(t *testing.T) {
	got := ParseProgramText("data('m', filter=not (filter('env','prod') and filter('region','us'))).sum().publish()")
	if got.ParseError != "" {
		t.Fatalf("unexpected ParseError: %s", got.ParseError)
	}
	if vals := got.Filters["env"]; len(vals) != 0 {
		t.Errorf("first negated filter should not be applied, got Filters[env]=%v", vals)
	}
	if vals := got.Filters["region"]; len(vals) != 0 {
		t.Errorf("second negated filter should not be applied, got Filters[region]=%v", vals)
	}
}

// TestParseProgramMultiDataCallScopesFiltersToFirst verifies that in a
// multi-stream ratio program only the first data() call's filters are attached
// to the metric. Before the fix the whole program was scanned and the
// denominator's service.name=db was unioned in with the numerator's
// service.name=api (R3-go-signalflow-180).
func TestParseProgramMultiDataCallScopesFiltersToFirst(t *testing.T) {
	got := ParseProgramText("A = data('errors', filter=filter('service.name','api')); B = data('total', filter=filter('service.name','db')); (A/B).publish()")
	if got.ParseError != "" {
		t.Fatalf("unexpected ParseError: %s", got.ParseError)
	}
	if got.MetricName != "errors" {
		t.Errorf("metric = %q, want %q", got.MetricName, "errors")
	}
	vals := got.Filters["service.name"]
	if len(vals) != 1 || !slices.Contains(vals, "api") {
		t.Errorf("expected only numerator service.name=[api], got %v", vals)
	}
	if slices.Contains(vals, "db") {
		t.Errorf("denominator service.name=db leaked into first data() call's filters: %v", vals)
	}
}

// A ')' inside a quoted filter value must NOT be counted as the data() call's
// closing paren. Before the quote-aware scan, firstDataCallSpan closed the span
// at the ')' in 'a)b', truncating the span before the region filter and dropping
// it entirely.
func TestParseProgramCloseParenInFilterValueDoesNotTruncateSpan(t *testing.T) {
	got := ParseProgramText("data('cpu', filter=filter('host','a)b') and filter('region','us')).publish()")
	if got.ParseError != "" {
		t.Fatalf("unexpected ParseError: %s", got.ParseError)
	}
	if hosts := got.Filters["host"]; len(hosts) != 1 || !slices.Contains(hosts, "a)b") {
		t.Errorf("host filter = %v, want [a)b]", hosts)
	}
	if regions := got.Filters["region"]; len(regions) != 1 || !slices.Contains(regions, "us") {
		t.Errorf("region filter dropped by a ')' inside the host value: got %v, want [us]", regions)
	}
}

// A '(' inside a quoted filter value must NOT extend the first data() call's span
// past its real closing paren. Before the quote-aware scan, an unbalanced '(' in
// the numerator value ran the span on into the denominator data() call, folding
// the denominator's svc filter onto the numerator metric.
func TestParseProgramOpenParenInFilterValueDoesNotOverExtendSpan(t *testing.T) {
	got := ParseProgramText("A = data('errors', filter=filter('k','a(b')); B = data('total', filter=filter('svc','db')); (A/B).publish()")
	if got.ParseError != "" {
		t.Fatalf("unexpected ParseError: %s", got.ParseError)
	}
	if got.MetricName != "errors" {
		t.Errorf("metric = %q, want %q", got.MetricName, "errors")
	}
	if ks := got.Filters["k"]; len(ks) != 1 || !slices.Contains(ks, "a(b") {
		t.Errorf("k filter = %v, want [a(b]", ks)
	}
	if svc, ok := got.Filters["svc"]; ok {
		t.Errorf("denominator svc filter leaked into numerator via a '(' in the value: got svc=%v", svc)
	}
}

func TestCanonicalServiceFilterNoServiceKeys(t *testing.T) {
	_, ok, conflict := canonicalServiceFilter(map[string][]string{"region": {"us1"}})
	if ok || conflict {
		t.Errorf("expected ok=false conflict=false, got ok=%v conflict=%v", ok, conflict)
	}
}

func TestCanonicalServiceFilterServiceNameOnly(t *testing.T) {
	vals, ok, conflict := canonicalServiceFilter(map[string][]string{"service.name": {"checkout"}})
	if !ok || conflict {
		t.Errorf("expected ok=true conflict=false, got ok=%v conflict=%v", ok, conflict)
	}
	if !slices.Contains(vals, "checkout") {
		t.Errorf("expected checkout in values, got %v", vals)
	}
}

func TestCanonicalServiceFilterSfServiceOnly(t *testing.T) {
	vals, ok, conflict := canonicalServiceFilter(map[string][]string{"sf_service": {"legacy"}})
	if !ok || conflict {
		t.Errorf("expected ok=true conflict=false, got ok=%v conflict=%v", ok, conflict)
	}
	if !slices.Contains(vals, "legacy") {
		t.Errorf("expected legacy in values, got %v", vals)
	}
}

func TestCanonicalServiceFilterSameValueBoth(t *testing.T) {
	vals, ok, conflict := canonicalServiceFilter(map[string][]string{
		"service.name": {"checkout"},
		"sf_service":   {"checkout"},
	})
	if !ok || conflict {
		t.Errorf("expected ok=true conflict=false, got ok=%v conflict=%v", ok, conflict)
	}
	if !slices.Contains(vals, "checkout") {
		t.Errorf("expected checkout in values, got %v", vals)
	}
}

func TestCanonicalServiceFilterConflict(t *testing.T) {
	_, ok, conflict := canonicalServiceFilter(map[string][]string{
		"service.name": {"checkout"},
		"sf_service":   {"legacy-checkout"},
	})
	if !ok || !conflict {
		t.Errorf("expected ok=true conflict=true, got ok=%v conflict=%v", ok, conflict)
	}
}

// TestCanonicalServiceFilterMixedCaseKey verifies that a mixed-case alias key
// (SERVICE.NAME) is recognized rather than dropped (finding F5). A dropped key
// would yield ok=false and over-match all services.
func TestCanonicalServiceFilterMixedCaseKey(t *testing.T) {
	vals, ok, conflict := canonicalServiceFilter(map[string][]string{"SERVICE.NAME": {"checkout"}})
	if !ok || conflict {
		t.Errorf("expected ok=true conflict=false for mixed-case key, got ok=%v conflict=%v", ok, conflict)
	}
	if !slices.Contains(vals, "checkout") {
		t.Errorf("expected checkout in values, got %v", vals)
	}
}

// TestCanonicalServiceFilterMixedCaseAliasValuesNoConflict verifies that
// service.name=Checkout and sf_service=checkout are NOT flagged as a conflict
// because the values compare case-insensitively (finding F5).
func TestCanonicalServiceFilterMixedCaseAliasValuesNoConflict(t *testing.T) {
	vals, ok, conflict := canonicalServiceFilter(map[string][]string{
		"service.name": {"Checkout"},
		"sf_service":   {"checkout"},
	})
	if !ok || conflict {
		t.Errorf("expected ok=true conflict=false for case-differing alias values, got ok=%v conflict=%v", ok, conflict)
	}
	// Union must be deduped case-insensitively to a single value.
	if len(vals) != 1 {
		t.Errorf("expected a single deduped service value, got %v", vals)
	}
}

// TestParseProgramCaseVariantNonServiceKeysMerge verifies that case-variant
// spellings of the same non-service dimension key are folded into a single
// Filters entry whose values are the union (finding D1). Before the fix
// filter('Region','us') and filter('region','eu') produced two distinct map
// entries {"Region":["us"], "region":["eu"]}; because applyDimensionFilters
// AND-combines every key while attrMatchesAny compares case-insensitively, no
// data point could satisfy both contradictory constraints and every group was
// wrongly dropped.
func TestParseProgramCaseVariantNonServiceKeysMerge(t *testing.T) {
	got := ParseProgramText("data('m', filter=filter('Region','us') and filter('region','eu')).sum().publish()")
	if got.ParseError != "" {
		t.Fatalf("unexpected ParseError: %s", got.ParseError)
	}

	// The two case-variant keys must merge into exactly one Filters entry.
	nonEmpty := 0
	var mergedKey string
	for k, vs := range got.Filters {
		if len(vs) > 0 {
			nonEmpty++
			mergedKey = k
		}
	}
	if nonEmpty != 1 {
		t.Fatalf("expected a single merged region key, got Filters=%v", got.Filters)
	}

	vals := got.Filters[mergedKey]
	if !slices.Contains(vals, "us") || !slices.Contains(vals, "eu") {
		t.Errorf("merged key %q should hold the union [us eu], got %v", mergedKey, vals)
	}

	// Simulate the downstream case-insensitive OR-per-key match: a data point
	// tagged region=us must satisfy the merged constraint rather than being
	// dropped by a contradictory case-variant twin.
	matched := false
	for _, v := range vals {
		if strings.EqualFold(v, "us") {
			matched = true
		}
	}
	if !matched {
		t.Errorf("data point region=us should match merged constraint %v", vals)
	}
}

// TestParseProgramAggregationScopedToFirstDataCall verifies that resolveAggregation
// is scoped to the first data() call span, matching the filter/metric extraction
// (finding D2). For a ratio program whose denominator carries .sum(), the first
// stream's aggregation must be empty, not "sum" borrowed from the denominator.
func TestParseProgramAggregationScopedToFirstDataCall(t *testing.T) {
	got := ParseProgramText("A = data('errors'); B = data('total').sum(); (A/B).publish()")
	if got.ParseError != "" {
		t.Fatalf("unexpected ParseError: %s", got.ParseError)
	}
	if got.MetricName != "errors" {
		t.Errorf("metric = %q, want %q", got.MetricName, "errors")
	}
	if got.Aggregation != "" {
		t.Errorf("aggregation = %q, want %q (the .sum() belongs to denominator 'total')", got.Aggregation, "")
	}

	// A single-stream program must still report its own aggregation.
	single := ParseProgramText("data('x').sum().publish()")
	if single.Aggregation != "sum" {
		t.Errorf("single-stream aggregation = %q, want %q", single.Aggregation, "sum")
	}
}

// TestParseProgramNegatedFilterRecordedAsNegated verifies that a negated filter
// with a parseable value lands in NegatedFilters (not IgnoredFilters and not
// Filters) so applyDimensionFilters can actively exclude matching series.
func TestParseProgramNegatedFilterRecordedAsNegated(t *testing.T) {
	// Single negated filter — must appear in NegatedFilters, NOT in Filters.
	got := ParseProgramText("data('m', filter=not filter('env','prod')).mean().publish()")
	if got.ParseError != "" {
		t.Fatalf("unexpected ParseError: %s", got.ParseError)
	}
	if len(got.Filters["env"]) > 0 {
		t.Errorf("negated filter must not be in Filters, got %v", got.Filters["env"])
	}
	if !slices.Contains(got.NegatedFilters["env"], "prod") {
		t.Errorf("negated filter value must be in NegatedFilters[env], got %v", got.NegatedFilters)
	}

	// Negated multi-value filter inside a group — values must land in NegatedFilters.
	got2 := ParseProgramText("data('m', filter=not (filter('region','us1','us2'))).sum().publish()")
	if got2.ParseError != "" {
		t.Fatalf("unexpected ParseError: %s", got2.ParseError)
	}
	if len(got2.Filters["region"]) > 0 {
		t.Errorf("negated multi-value filter must not be in Filters, got %v", got2.Filters["region"])
	}
	if !slices.Contains(got2.NegatedFilters["region"], "us1") || !slices.Contains(got2.NegatedFilters["region"], "us2") {
		t.Errorf("negated multi-value filter values must be in NegatedFilters[region], got %v", got2.NegatedFilters)
	}
}

// TestParseProgramUnbalancedNegationGroup verifies that a negated group with no
// matching closing paren still marks its filters as negated (issue #25). Before
// the fix, matchingCloseParen returned -1 and the span was stored as
// negatedSpan{end:-1}; since isNegatedFilter checks matchStart < span.end, no
// positive matchStart could satisfy matchStart < -1, so filters inside the
// unbalanced group were treated as positive constraints.
func TestParseProgramUnbalancedNegationGroup(t *testing.T) {
	// Unbalanced "not (" — the outer data() paren closes before the negation group.
	got := ParseProgramText("data('m', filter=not (filter('env','prod'))")
	if got.ParseError != "" {
		t.Fatalf("unexpected ParseError: %s", got.ParseError)
	}
	if len(got.Filters["env"]) > 0 {
		t.Errorf("filter inside unbalanced negation group must not be a positive constraint, got %v", got.Filters["env"])
	}
	if !slices.Contains(got.NegatedFilters["env"], "prod") {
		t.Errorf("filter inside unbalanced negation group must be in NegatedFilters, got %v", got.NegatedFilters)
	}
}

func floatPtr(f float64) *float64 { return &f }
