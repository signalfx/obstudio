package dashboards

import (
	"regexp"
	"strconv"
	"strings"
)

// These are focused extraction regexes, NOT a SignalFlow parser. They recover
// just enough — metric, filters, aggregation — to resolve matching local series.
var (
	// data('metric.name', ...) — the first data() argument is the metric. The
	// leading boundary group ensures we match a real data() call and not the
	// "data(" substring inside metadata(/alldata(/etc., which would otherwise
	// shadow the real metric.
	reMetric = regexp.MustCompile(`(?:^|[^A-Za-z0-9_.])data\(\s*'([^']+)'`)
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
	// amount of whitespace (including newlines) between "not" and "filter(",
	// and zero-or-more opening parens (with interleaved whitespace) so a
	// parenthesized group like "not (filter('env','prod'))" or
	// "not ((filter('env','prod')))" is also recognized as negated.
	reNot = regexp.MustCompile(`(?i)\bnot\s*(?:\(\s*)*$`)
	// word-boundary "not" followed by an opening paren — the start of a
	// parenthesized negation group. Used to compute the byte span each such
	// group covers so every filter() inside it (not just the first) is treated
	// as negated.
	reNotGroup = regexp.MustCompile(`(?i)\bnot\s*\(`)
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

// negatedSpan is the [start, end) byte range of a "not ( ... )" negation group.
type negatedSpan struct {
	start int
	end   int
}

// negatedGroupSpans returns the byte spans of every parenthesized negation
// group ("not ( ... )") in program. A filter() whose start falls inside any of
// these spans is negated even when it is not the first filter in the group —
// e.g. the second filter of "not (filter('env','prod') and filter('region','us'))".
// Spans are matched by scanning for the balanced closing paren of the group's
// opener; an unbalanced group extends to end-of-string (best effort).
func negatedGroupSpans(program string) []negatedSpan {
	var spans []negatedSpan
	for _, loc := range reNotGroup.FindAllStringIndex(program, -1) {
		// loc[1]-1 is the index of the opening paren that begins the group.
		open := loc[1] - 1
		depth := 0
		end := len(program)
		for i := open; i < len(program); i++ {
			switch program[i] {
			case '(':
				depth++
			case ')':
				depth--
				if depth == 0 {
					end = i + 1
				}
			}
			if depth == 0 {
				break
			}
		}
		spans = append(spans, negatedSpan{start: loc[0], end: end})
	}

	return spans
}

// isNegatedFilter reports whether the filter match at matchStart is negated,
// either by an immediately preceding "not" keyword (with optional wrapping
// parens) or by falling inside a "not ( ... )" negation group. Uses a
// full-prefix regex with a word boundary so any amount of whitespace (including
// newlines) and identifiers ending in "not" are handled correctly.
func isNegatedFilter(program string, matchStart int, negated []negatedSpan) bool {
	if reNot.MatchString(program[:matchStart]) {
		return true
	}
	for _, span := range negated {
		if matchStart >= span.start && matchStart < span.end {
			return true
		}
	}

	return false
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
	// Look up the alias keys case-insensitively so a mixed-case SERVICE.NAME /
	// SF_SERVICE key is not dropped (isServiceKey, attrMatchesAny, and the store
	// query all use EqualFold; this must match).
	var sn, sf []string
	for k, vs := range filters {
		switch {
		case strings.EqualFold(k, "service.name"):
			sn = append(sn, vs...)
		case strings.EqualFold(k, "sf_service"):
			sf = append(sf, vs...)
		}
	}

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
// and share no common value (i.e. the filter is self-contradictory). Values are
// compared case-insensitively to match the store query and attribute matching,
// so service.name=Checkout + sf_service=checkout is NOT flagged as a conflict.
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

// svcUnion returns the case-insensitive set union of two service-alias value
// slices. The first-seen spelling of each value is preserved; later values that
// differ only in case are folded into it.
func svcUnion(sn, sf []string) map[string]bool {
	seen := make(map[string]bool, len(sn)+len(sf))
	for _, v := range sn {
		addFolded(seen, v)
	}
	for _, v := range sf {
		addFolded(seen, v)
	}
	return seen
}

// addFolded adds v to seen unless a case-insensitively equal value is already
// present.
func addFolded(seen map[string]bool, v string) {
	for existing := range seen {
		if strings.EqualFold(existing, v) {
			return
		}
	}
	seen[v] = true
}

func containsStr(ss []string, s string) bool {
	for _, v := range ss {
		if strings.EqualFold(v, s) {
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
	// Scope filter extraction to the argument span of the FIRST data() call so a
	// multi-stream program like
	//   A = data('errors', filter=filter('service.name','api'));
	//   B = data('total',  filter=filter('service.name','db')); (A/B).publish()
	// does not fold the denominator's filters into the numerator's metric. The
	// metric name comes from the first data() call, so its filters must too.
	collectFilters(firstDataCallSpan(program), &q)
	// Scope aggregation resolution to the first stream (the first data() call up to
	// the next data() call) rather than the whole program, so a multi-stream ratio
	// like A = data('errors'); B = data('total').sum() does not attribute the
	// denominator's .sum() to the numerator's metric. Aggregations are chained
	// AFTER the data() call — outside its argument parens — so this uses a wider
	// span than firstDataCallSpan (which is parens-only, correct for filters).
	q.Aggregation, q.Percentile = resolveAggregation(firstStreamSpan(program))

	return q
}

// firstDataCallSpan returns the substring covering the first data() call's
// argument list — from the opening "data(" through its balanced closing paren.
// Filters are only extracted from this span so that later data() calls in a
// multi-stream program (e.g. an errors/total ratio) do not contribute their
// filters to the first call's metric. When no balanced span is found (unusual /
// malformed input) it falls back to the whole program.
func firstDataCallSpan(program string) string {
	loc := reMetric.FindStringIndex(program)
	if loc == nil {
		return program
	}
	// Find the "data(" open paren at or after the match start; the boundary
	// group may consume one leading byte, so search within the matched region.
	open := strings.Index(program[loc[0]:loc[1]], "data(")
	if open < 0 {
		return program
	}
	open = loc[0] + open + len("data(") - 1 // index of '('

	depth := 0
	for i := open; i < len(program); i++ {
		switch program[i] {
		case '(':
			depth++
		case ')':
			depth--
			if depth == 0 {
				return program[loc[0] : i+1]
			}
		}
	}

	return program
}

// firstStreamSpan returns the substring covering the first stream's expression —
// from the first data() call's start up to (but not including) the SECOND data()
// call in the program, or end-of-program when there is only one data() call.
// Unlike firstDataCallSpan (which is the data() call's argument parens, used for
// filter extraction), aggregations are chained AFTER the data() call and outside
// its parens, so aggregation resolution needs this wider stream-scoped span. This
// keeps a later stream's .sum()/.percentile() from being attributed to the first
// stream's metric in a multi-stream ratio program.
func firstStreamSpan(program string) string {
	locs := reMetric.FindAllStringIndex(program, -1)
	if len(locs) == 0 {
		return program
	}
	start := locs[0][0]
	if len(locs) >= 2 {
		return program[start:locs[1][0]]
	}

	return program[start:]
}

// collectFilters populates q.Filters with all non-negated, non-template filter()
// constraints found in program, and records dropped keys in q.IgnoredFilters.
// Two-pass: multi-value first so the single-value pass does not double-count
// overlapping matches.
func collectFilters(program string, q *ParsedQuery) {
	negated := negatedGroupSpans(program)
	handled := collectMultiValueFilters(program, q, negated)
	collectSingleValueFilters(program, q, handled, negated)

	// Post-process: a key can be recorded as ignored (e.g. a templated
	// filter('env','${var}')) and later applied by a positive filter('env','prod')
	// on the same key. recordIgnoredFilter only sees the state at append time, so
	// drop any ignored key that ended up populated in q.Filters to avoid a
	// contradictory Filters={env:[prod]} + IgnoredFilters=[env] result.
	if len(q.IgnoredFilters) > 0 {
		kept := q.IgnoredFilters[:0]
		for _, key := range q.IgnoredFilters {
			// Fold to any applied case-variant so an ignored 'Region' is dropped
			// once 'region' ended up populated (keys compare case-insensitively).
			if folded := foldedFilterKey(q, key); folded == "" || len(q.Filters[folded]) == 0 {
				kept = append(kept, key)
			}
		}
		q.IgnoredFilters = kept
	}
}

// collectMultiValueFilters handles filter('key','a','b',...) forms and returns
// the set of match start positions that were processed. A non-negated filter
// whose every value is empty or templated (${...}) contributes nothing to
// q.Filters and is recorded in q.IgnoredFilters.
func collectMultiValueFilters(program string, q *ParsedQuery, negated []negatedSpan) map[int]bool {
	handled := make(map[int]bool)

	for _, loc := range reFilterMulti.FindAllStringSubmatchIndex(program, -1) {
		start := loc[0]
		key := program[loc[2]:loc[3]]
		argList := program[loc[4]:loc[5]]

		handled[start] = true

		if key == "" || isNegatedFilter(program, start, negated) {
			continue
		}

		applied := false
		for _, v := range reQuotedVal.FindAllStringSubmatch(argList, -1) {
			if val := v[1]; val != "" && !strings.Contains(val, "${") {
				appendFilterValue(q, key, val)
				applied = true
			}
		}

		if !applied {
			recordIgnoredFilter(q, key)
		}
	}

	return handled
}

// collectSingleValueFilters handles filter('key','val') forms, skipping
// positions already covered by collectMultiValueFilters. A non-negated filter
// whose value is empty or templated (${...}) is recorded in q.IgnoredFilters.
func collectSingleValueFilters(program string, q *ParsedQuery, handled map[int]bool, negated []negatedSpan) {
	for _, loc := range reFilter.FindAllStringSubmatchIndex(program, -1) {
		start := loc[0]
		if handled[start] {
			continue
		}

		key := program[loc[2]:loc[3]]
		val := program[loc[4]:loc[5]]

		if key == "" || isNegatedFilter(program, start, negated) {
			continue
		}

		if val == "" || strings.Contains(val, "${") {
			recordIgnoredFilter(q, key)
			continue
		}

		appendFilterValue(q, key, val)
	}
}

// appendFilterValue records val under key in q.Filters, folding case-variant
// spellings of the same dimension into a single map entry. Every downstream
// comparison (applyDimensionFilters / dataPointMatches / attrMatchesAny, and the
// service-alias resolution) is case-insensitive, so collecting keys verbatim
// would let filter('Region','us') and filter('region','eu') become two distinct,
// mutually-contradictory constraints that AND-combine to drop every data point.
// The first-seen key spelling is preserved for display; a later case-variant
// merges its values into that entry rather than creating a rival key.
func appendFilterValue(q *ParsedQuery, key, val string) {
	if existing := foldedFilterKey(q, key); existing != "" {
		key = existing
	}
	q.Filters[key] = append(q.Filters[key], val)
}

// foldedFilterKey returns the already-present key in q.Filters that matches key
// case-insensitively, or "" if none exists yet.
func foldedFilterKey(q *ParsedQuery, key string) string {
	if _, ok := q.Filters[key]; ok {
		return key
	}
	for existing := range q.Filters {
		if strings.EqualFold(existing, key) {
			return existing
		}
	}
	return ""
}

// recordIgnoredFilter appends key to q.IgnoredFilters unless it is already an
// applied filter or already recorded as ignored (deduped).
func recordIgnoredFilter(q *ParsedQuery, key string) {
	// Fold to any applied case-variant so an ignored 'Region' is suppressed once
	// 'region' has been applied (keys compare case-insensitively downstream).
	if folded := foldedFilterKey(q, key); folded != "" && len(q.Filters[folded]) > 0 {
		return
	}
	for _, existing := range q.IgnoredFilters {
		if strings.EqualFold(existing, key) {
			return
		}
	}
	q.IgnoredFilters = append(q.IgnoredFilters, key)
}
