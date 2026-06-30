package dashboards

import (
	"regexp"
	"strconv"
	"strings"
)

// These are focused extraction regexes, NOT a SignalFlow parser. They recover
// just enough — metric, filters, aggregation — to resolve matching local series.
var (
	// data('metric.name', ...) — the first data() argument is the metric.
	reMetric = regexp.MustCompile(`data\(\s*'([^']+)'`)
	// filter('key', 'value') — every occurrence, AND-combined.
	reFilter = regexp.MustCompile(`filter\(\s*'([^']+)'\s*,\s*'([^']*)'\s*\)`)
	// .percentile(pct=99) — capture the percentile value.
	rePercentile = regexp.MustCompile(`\.percentile\(\s*pct\s*=\s*([0-9.]+)\s*\)`)
)

// aggHints maps a SignalFlow aggregation call to a normalized aggregation name.
// percentile is handled separately because it carries a pct argument.
var aggHints = []struct {
	token string
	name  string
}{
	{".sum(", "sum"},
	{".mean(", "mean"},
	{".count(", "count"},
	{".min(", "min"},
	{".max(", "max"},
	{".last(", "last"},
}

// resolveAggregation scans program for the first aggregation call and returns
// the normalized name plus, for percentile, the pct value.
func resolveAggregation(program string) (string, *float64) {
	if p := rePercentile.FindStringSubmatch(program); p != nil {
		if v, err := strconv.ParseFloat(p[1], 64); err == nil {
			return "percentile", &v
		}

		return "percentile", nil
	}

	for _, hint := range aggHints {
		if strings.Contains(program, hint.token) {
			return hint.name, nil
		}
	}

	return "", nil
}

// isNegatedFilter reports whether the filter match at matchStart is preceded by
// a "not" keyword, indicating an exclusion rather than a positive constraint.
func isNegatedFilter(program string, matchStart int) bool {
	lookback := matchStart - 10
	if lookback < 0 {
		lookback = 0
	}
	before := program[lookback:matchStart]
	return strings.HasSuffix(strings.TrimRight(before, " \t"), "not")
}

// ParseProgramText extracts { metric, filters, aggregation } from a panel's
// resolved SignalFlow. An unresolved ${...} value is treated as "no constraint"
// (skipped), not a literal filter. A program with no data() call yields a
// ParsedQuery with ParseError set.
func ParseProgramText(program string) ParsedQuery {
	q := ParsedQuery{Filters: map[string]string{}}

	m := reMetric.FindStringSubmatch(program)
	if m == nil {
		q.ParseError = "no data('<metric>') call found in program_text"

		return q
	}

	q.MetricName = m[1]

	// reFilter matches single-value filter('key','val') only. Multi-value
	// filter('key','a','b') does not match (the closing ')' is not adjacent
	// to the second arg), so it is intentionally skipped — the local preview
	// cannot reduce multiple accepted values to a single equality constraint.
	for _, loc := range reFilter.FindAllStringSubmatchIndex(program, -1) {
		key := program[loc[2]:loc[3]]
		val := program[loc[4]:loc[5]]

		if key == "" || isNegatedFilter(program, loc[0]) {
			continue
		}

		// An unresolved Terraform variable is not a real constraint.
		if val == "" || strings.Contains(val, "${") {
			continue
		}

		q.Filters[key] = val
	}

	q.Aggregation, q.Percentile = resolveAggregation(program)

	return q
}
