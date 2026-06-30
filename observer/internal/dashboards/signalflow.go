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
	// filter('key', 'v1') — single-value form.
	reFilter = regexp.MustCompile(`filter\(\s*'([^']+)'\s*,\s*'([^']*)'\s*\)`)
	// filter('key', 'v1', 'v2', ...) — multi-value form: captures key + all
	// quoted values. The trailing \) is required so it doesn't greedily match
	// across separate filter() calls.
	reFilterMulti = regexp.MustCompile(`filter\(\s*'([^']+)'((?:\s*,\s*'[^']*')+)\s*\)`)
	// individual quoted value within a multi-value arg list.
	reQuotedVal = regexp.MustCompile(`'([^']*)'`)
	// .percentile(pct=99) — capture the percentile value.
	rePercentile = regexp.MustCompile(`\.percentile\(\s*pct\s*=\s*([0-9.]+)\s*\)`)
	// word-boundary "not" immediately before a filter() call, allowing any
	// amount of whitespace (including newlines) between "not" and "filter(".
	reNot = regexp.MustCompile(`(?i)\bnot\s*$`)
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
// a "not" keyword. Uses a full-prefix regex with a word boundary so any amount
// of whitespace (including newlines) and identifiers ending in "not" are
// handled correctly.
func isNegatedFilter(program string, matchStart int) bool {
	return reNot.MatchString(program[:matchStart])
}

// canonicalServiceFilter resolves the service.name / sf_service alias pair from
// a filter map and returns the effective service name to pass to the store query.
//
//   - ok=false: neither key is present → no service filter.
//   - conflict=true: both keys present but their value sets are disjoint →
//     the panel's intent is self-contradictory; the caller should treat it as
//     unmatched with no store query.
//   - otherwise: returns the union of values found under either key.
func canonicalServiceFilter(filters map[string][]string) (values []string, ok, conflict bool) {
	sn := filters["service.name"]
	sf := filters["sf_service"]

	if len(sn) == 0 && len(sf) == 0 {
		return nil, false, false
	}

	if svcAliasConflict(sn, sf) {
		return nil, true, true
	}

	seen := svcUnion(sn, sf)
	out := make([]string, 0, len(seen))
	for v := range seen {
		out = append(out, v)
	}
	return out, true, false
}

// svcAliasConflict reports true when both service-alias slices are non-empty
// and share no common value (i.e. the filter is self-contradictory).
func svcAliasConflict(sn, sf []string) bool {
	if len(sn) == 0 || len(sf) == 0 {
		return false
	}
	for _, v := range sf {
		if containsStr(sn, v) {
			return false
		}
	}
	return true
}

// svcUnion returns the set union of two service-alias value slices.
func svcUnion(sn, sf []string) map[string]bool {
	seen := make(map[string]bool, len(sn)+len(sf))
	for _, v := range sn {
		seen[v] = true
	}
	for _, v := range sf {
		seen[v] = true
	}
	return seen
}

func containsStr(ss []string, s string) bool {
	for _, v := range ss {
		if v == s {
			return true
		}
	}
	return false
}

// ParseProgramText extracts { metric, filters, aggregation } from a panel's
// resolved SignalFlow. An unresolved ${...} value is treated as "no constraint"
// (skipped), not a literal filter. A program with no data() call yields a
// ParsedQuery with ParseError set.
//
// Filters: multi-value filter('k','a','b') is parsed as OR-semantics (all
// values collected). Unresolved or unparseable constraints are listed in
// IgnoredFilters so callers can surface them to the user.
func ParseProgramText(program string) ParsedQuery {
	q := ParsedQuery{Filters: map[string][]string{}}

	m := reMetric.FindStringSubmatch(program)
	if m == nil {
		q.ParseError = "no data('<metric>') call found in program_text"

		return q
	}

	q.MetricName = m[1]
	collectFilters(program, q.Filters)
	q.Aggregation, q.Percentile = resolveAggregation(program)

	return q
}

// collectFilters populates out with all non-negated, non-template filter()
// constraints found in program. Two-pass: multi-value first so the single-value
// pass does not double-count overlapping matches.
func collectFilters(program string, out map[string][]string) {
	handled := collectMultiValueFilters(program, out)
	collectSingleValueFilters(program, out, handled)
}

// collectMultiValueFilters handles filter('key','a','b',...) forms and returns
// the set of match start positions that were processed.
func collectMultiValueFilters(program string, out map[string][]string) map[int]bool {
	handled := make(map[int]bool)

	for _, loc := range reFilterMulti.FindAllStringSubmatchIndex(program, -1) {
		start := loc[0]
		key := program[loc[2]:loc[3]]
		argList := program[loc[4]:loc[5]]

		handled[start] = true

		if key == "" || isNegatedFilter(program, start) {
			continue
		}

		for _, v := range reQuotedVal.FindAllStringSubmatch(argList, -1) {
			if val := v[1]; val != "" && !strings.Contains(val, "${") {
				out[key] = append(out[key], val)
			}
		}
	}

	return handled
}

// collectSingleValueFilters handles filter('key','val') forms, skipping
// positions already covered by collectMultiValueFilters.
func collectSingleValueFilters(program string, out map[string][]string, handled map[int]bool) {
	for _, loc := range reFilter.FindAllStringSubmatchIndex(program, -1) {
		start := loc[0]
		if handled[start] {
			continue
		}

		key := program[loc[2]:loc[3]]
		val := program[loc[4]:loc[5]]

		if key == "" || isNegatedFilter(program, start) {
			continue
		}

		if val == "" || strings.Contains(val, "${") {
			continue
		}

		out[key] = append(out[key], val)
	}
}
