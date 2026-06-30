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

	for _, f := range reFilter.FindAllStringSubmatch(program, -1) {
		key, val := f[1], f[2]
		if key == "" {
			continue
		}
		// An unresolved Terraform variable is not a real constraint.
		if val == "" || strings.Contains(val, "${") {
			continue
		}

		q.Filters[key] = val
	}

	if p := rePercentile.FindStringSubmatch(program); p != nil {
		q.Aggregation = "percentile"
		if v, err := strconv.ParseFloat(p[1], 64); err == nil {
			q.Percentile = &v
		}
	} else {
		for _, hint := range aggHints {
			if strings.Contains(program, hint.token) {
				q.Aggregation = hint.name

				break
			}
		}
	}

	return q
}
