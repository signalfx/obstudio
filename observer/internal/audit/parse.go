package audit

import (
	"strings"
)

// Parse reads the Markdown produced by $otel-audit and derives a scored Report.
//
// It targets only the sections the skill's report template mandates, so it
// degrades gracefully: an unrecognized section leaves its facts at zero rather
// than failing the whole parse.
func Parse(markdown string) Report {
	r := Report{
		Available: true,
		Rate:      REDMissing,
		Errors:    REDMissing,
		Duration:  REDMissing,
	}

	sections := splitSections(markdown)

	r.ServiceName = parseServiceName(markdown)
	r.Language, r.Framework = parseLanguageFramework(markdown)
	r.GeneratedAt = parseGeneratedAt(markdown)

	r.Rate, r.Errors, r.Duration = parseREDTable(sections["red signals"])

	r.HasSpans = sectionHasSignal(sections["spans"], "no spans detected")
	r.HasMetrics = sectionHasSignal(sections["metrics"], "no metrics detected")
	r.HasLogs = sectionHasSignal(sections["logs"], "no otel log instrumentation detected")

	// Always non-nil so the JSON carries [] rather than null; clients iterate
	// these directly.
	r.Gaps = nonNil(collectFindings(sections["gaps"], "no additional gaps detected"))
	r.AntiPatterns = nonNil(collectFindings(sections["anti-patterns"], "none detected"))
	r.Recommendations = nonNil(collectBullets(sections["recommendation"]))

	r.GapCount = len(r.Gaps)
	r.AntiPatternCount = len(r.AntiPatterns)
	r.RecommendationCount = len(r.Recommendations)

	r.score()

	return r
}

// splitSections maps a lowercased heading title to the lines beneath it, for
// both "## Title" and "### Title" levels.
func splitSections(markdown string) map[string][]string {
	sections := make(map[string][]string)
	current := ""

	for _, line := range strings.Split(markdown, "\n") {
		trimmed := strings.TrimSpace(line)
		if strings.HasPrefix(trimmed, "#") {
			title := strings.ToLower(strings.TrimSpace(strings.TrimLeft(trimmed, "#")))
			current = title
			if _, seen := sections[current]; !seen {
				sections[current] = nil
			}
			continue
		}
		if current != "" {
			sections[current] = append(sections[current], line)
		}
	}

	return sections
}

// parseREDTable reads the three status cells out of the RED Signals table.
func parseREDTable(lines []string) (rate, errs, duration REDStatus) {
	rate, errs, duration = REDMissing, REDMissing, REDMissing

	for _, line := range lines {
		cells := tableCells(line)
		if len(cells) < 2 {
			continue
		}
		status := normalizeREDStatus(cells[1])
		if status == "" {
			continue
		}
		switch strings.ToLower(strings.TrimSpace(cells[0])) {
		case "rate":
			rate = status
		case "errors":
			errs = status
		case "duration":
			duration = status
		}
	}

	return rate, errs, duration
}

func normalizeREDStatus(cell string) REDStatus {
	switch strings.ToLower(strings.TrimSpace(cell)) {
	case string(REDCovered):
		return REDCovered
	case string(REDPartial):
		return REDPartial
	case string(REDMissing):
		return REDMissing
	default:
		return ""
	}
}

// sectionHasSignal reports whether a signal section lists any instrumentation.
// The skill mandates an explicit "No X detected." sentence when nothing is
// found, which is checked first; otherwise any data row in the table counts.
func sectionHasSignal(lines []string, emptyPhrase string) bool {
	for _, line := range lines {
		if strings.Contains(strings.ToLower(line), emptyPhrase) {
			return false
		}
	}

	return countTableRows(lines) > 0
}

// countTableRows counts data rows in a Markdown table, skipping the header row
// and the |---|---| separator.
func countTableRows(lines []string) int {
	rows := 0
	seenSeparator := false

	for _, line := range lines {
		trimmed := strings.TrimSpace(line)
		if !strings.HasPrefix(trimmed, "|") {
			continue
		}
		if isTableSeparator(trimmed) {
			seenSeparator = true
			continue
		}
		if !seenSeparator {
			// Header row, or a table whose separator has not appeared yet.
			continue
		}
		if len(tableCells(trimmed)) > 0 {
			rows++
		}
	}

	return rows
}

func isTableSeparator(line string) bool {
	stripped := strings.Map(func(r rune) rune {
		switch r {
		case '|', '-', ':', ' ', '\t':
			return -1
		}
		return r
	}, line)

	return stripped == "" && strings.Contains(line, "-")
}

func tableCells(line string) []string {
	trimmed := strings.TrimSpace(line)
	if !strings.HasPrefix(trimmed, "|") {
		return nil
	}
	trimmed = strings.Trim(trimmed, "|")
	parts := strings.Split(trimmed, "|")
	cells := make([]string, 0, len(parts))
	for _, p := range parts {
		cells = append(cells, strings.TrimSpace(p))
	}

	return cells
}

// collectFindings returns the bullet text of a findings section. The skill
// mandates an explicit "nothing found" sentence, and when that phrase appears
// the section yields nothing regardless of any surrounding commentary — a report
// may legitimately add context bullets (for example noting a previously flagged
// item is now resolved) that must not be counted as live findings.
func collectFindings(lines []string, emptyPhrase string) []string {
	for _, line := range lines {
		if strings.Contains(strings.ToLower(line), emptyPhrase) {
			return nil
		}
	}

	return collectBullets(lines)
}

// collectBullets returns the text of each top-level bullet, joined with any
// continuation lines that the report wrapped, and stripped of Markdown emphasis
// so the UI can render it as plain text.
func collectBullets(lines []string) []string {
	var bullets []string

	for _, line := range lines {
		trimmed := strings.TrimSpace(line)
		switch {
		case strings.HasPrefix(trimmed, "- "), strings.HasPrefix(trimmed, "* "):
			bullets = append(bullets, stripInlineMarkdown(strings.TrimSpace(trimmed[2:])))
		case trimmed == "":
			// Blank line ends any continuation.
		case len(bullets) > 0 && strings.HasPrefix(line, " "):
			// Indented wrap of the previous bullet.
			bullets[len(bullets)-1] += " " + stripInlineMarkdown(trimmed)
		}
	}

	return bullets
}

// nonNil returns an empty slice in place of nil so encoding/json emits [] and
// clients can iterate the field without a null check.
func nonNil(items []string) []string {
	if items == nil {
		return []string{}
	}

	return items
}

// stripInlineMarkdown removes the emphasis and code markers the report uses so
// bullets read as plain sentences in the UI.
func stripInlineMarkdown(s string) string {
	replacer := strings.NewReplacer("**", "", "`", "")

	return strings.TrimSpace(replacer.Replace(s))
}

func parseServiceName(markdown string) string {
	for _, line := range strings.Split(markdown, "\n") {
		trimmed := strings.TrimSpace(line)
		const prefix = "# Observability Report:"
		if strings.HasPrefix(trimmed, prefix) {
			return strings.TrimSpace(strings.TrimPrefix(trimmed, prefix))
		}
	}

	return ""
}

// parseLanguageFramework reads the "**Language:** X | **Framework:** Y" header.
func parseLanguageFramework(markdown string) (language, framework string) {
	for _, line := range strings.Split(markdown, "\n") {
		if !strings.Contains(line, "**Language:**") {
			continue
		}
		for _, part := range strings.Split(line, "|") {
			part = strings.TrimSpace(part)
			switch {
			case strings.HasPrefix(part, "**Language:**"):
				language = strings.TrimSpace(strings.TrimPrefix(part, "**Language:**"))
			case strings.HasPrefix(part, "**Framework:**"):
				framework = strings.TrimSpace(strings.TrimPrefix(part, "**Framework:**"))
			}
		}

		return language, framework
	}

	return "", ""
}

// parseGeneratedAt reads the trailing "*Generated by ... on <timestamp>*" line.
func parseGeneratedAt(markdown string) string {
	const marker = " on "
	for _, line := range strings.Split(markdown, "\n") {
		trimmed := strings.TrimSpace(line)
		if !strings.HasPrefix(trimmed, "*Generated by") {
			continue
		}
		idx := strings.LastIndex(trimmed, marker)
		if idx < 0 {
			return ""
		}

		return strings.TrimSpace(strings.Trim(trimmed[idx+len(marker):], "*"))
	}

	return ""
}
