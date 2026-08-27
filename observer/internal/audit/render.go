package audit

import (
	"html"
	"regexp"
	"strings"
)

// RenderHTML converts an $otel-audit report to a standalone HTML page.
//
// This is deliberately not a general Markdown implementation: it covers only
// the constructs the skill's report template emits (headings, tables, bullet
// lists, paragraphs, rules, and inline bold/code/links). Anything it does not
// recognize falls through as escaped text rather than being dropped.
//
// Every piece of document text is HTML-escaped before any markup is applied,
// and the only tags emitted are ones this file writes, so report content can
// never inject markup.
func RenderHTML(markdown, title string) string {
	var b strings.Builder

	b.WriteString("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n")
	b.WriteString("<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n")
	b.WriteString("<title>")
	b.WriteString(html.EscapeString(title))
	b.WriteString("</title>\n<style>\n")
	b.WriteString(reportStyles)
	b.WriteString("</style>\n</head>\n<body>\n<main>\n")
	b.WriteString(renderBlocks(markdown))
	b.WriteString("</main>\n</body>\n</html>\n")

	return b.String()
}

const reportStyles = `:root { color-scheme: dark light; }
body {
  margin: 0;
  padding: 32px 20px 64px;
  background: #030811;
  color: #c9ccd1;
  font: 15px/1.65 Inter, system-ui, -apple-system, sans-serif;
}
main { max-width: 900px; margin: 0 auto; }
h1, h2, h3 { color: #fafafa; line-height: 1.25; }
h1 { margin: 0 0 4px; font-size: 26px; }
h2 { margin: 32px 0 10px; padding-bottom: 6px; border-bottom: 1px solid #2a3040; font-size: 19px; }
h3 { margin: 22px 0 8px; font-size: 15px; letter-spacing: 0.04em; text-transform: uppercase; color: #909090; }
p { margin: 10px 0; }
ul { margin: 10px 0; padding-left: 22px; }
li { margin: 6px 0; }
li::marker { color: #909090; }
code {
  padding: 1px 5px;
  border: 1px solid #2a3040;
  border-radius: 4px;
  background: #0f1825;
  font-family: 'Roboto Mono', ui-monospace, monospace;
  font-size: 0.88em;
  color: #61cafa;
}
a { color: #3993ff; }
hr { margin: 32px 0 16px; border: 0; border-top: 1px solid #2a3040; }
em { color: #909090; }
.table-scroll { overflow-x: auto; margin: 12px 0; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { padding: 7px 10px; border: 1px solid #2a3040; text-align: left; vertical-align: top; }
th { background: #0f1825; color: #fafafa; font-weight: 600; }
td code { white-space: nowrap; }
`

// renderBlocks walks the document line by line, emitting one HTML block per
// Markdown block.
func renderBlocks(markdown string) string {
	lines := strings.Split(strings.ReplaceAll(markdown, "\r\n", "\n"), "\n")
	var b strings.Builder

	for i := 0; i < len(lines); {
		line := lines[i]
		trimmed := strings.TrimSpace(line)

		switch {
		case trimmed == "":
			i++

		case isThematicBreak(trimmed):
			b.WriteString("<hr>\n")
			i++

		case strings.HasPrefix(trimmed, "#"):
			b.WriteString(renderHeading(trimmed))
			i++

		case strings.HasPrefix(trimmed, "|"):
			block, next := collectWhile(lines, i, func(l string) bool {
				return strings.HasPrefix(strings.TrimSpace(l), "|")
			})
			b.WriteString(renderTable(block))
			i = next

		case isBullet(trimmed):
			block, next := collectWhile(lines, i, func(l string) bool {
				t := strings.TrimSpace(l)
				// A bullet, or an indented continuation of one.
				return isBullet(t) || (t != "" && strings.HasPrefix(l, " "))
			})
			b.WriteString(renderList(block))
			i = next

		default:
			block, next := collectWhile(lines, i, func(l string) bool {
				t := strings.TrimSpace(l)
				return t != "" && !isBullet(t) && !strings.HasPrefix(t, "|") &&
					!strings.HasPrefix(t, "#") && !isThematicBreak(t)
			})
			b.WriteString("<p>" + renderInline(strings.Join(trimAll(block), " ")) + "</p>\n")
			i = next
		}
	}

	return b.String()
}

// collectWhile returns the run of lines from start for which keep holds, and
// the index just past it. It always advances at least one line.
func collectWhile(lines []string, start int, keep func(string) bool) ([]string, int) {
	end := start + 1
	for end < len(lines) && keep(lines[end]) {
		end++
	}

	return lines[start:end], end
}

func trimAll(lines []string) []string {
	out := make([]string, 0, len(lines))
	for _, l := range lines {
		out = append(out, strings.TrimSpace(l))
	}

	return out
}

func isBullet(trimmed string) bool {
	return strings.HasPrefix(trimmed, "- ") || strings.HasPrefix(trimmed, "* ")
}

func isThematicBreak(trimmed string) bool {
	return trimmed == "---" || trimmed == "***" || trimmed == "___"
}

func renderHeading(trimmed string) string {
	level := 0
	for level < len(trimmed) && trimmed[level] == '#' {
		level++
	}
	if level > 6 {
		level = 6
	}
	text := strings.TrimSpace(trimmed[level:])
	tag := "h" + string(rune('0'+level))

	return "<" + tag + ">" + renderInline(text) + "</" + tag + ">\n"
}

// renderList joins wrapped continuation lines back onto their bullet.
func renderList(block []string) string {
	var items []string
	for _, line := range block {
		trimmed := strings.TrimSpace(line)
		if isBullet(trimmed) {
			items = append(items, strings.TrimSpace(trimmed[2:]))
			continue
		}
		if len(items) > 0 && trimmed != "" {
			items[len(items)-1] += " " + trimmed
		}
	}

	var b strings.Builder
	b.WriteString("<ul>\n")
	for _, item := range items {
		b.WriteString("<li>" + renderInline(item) + "</li>\n")
	}
	b.WriteString("</ul>\n")

	return b.String()
}

// renderTable treats the first row as the header and skips the |---| separator.
func renderTable(block []string) string {
	var b strings.Builder
	b.WriteString("<div class=\"table-scroll\">\n<table>\n")

	wroteHeader := false
	openedBody := false

	for _, line := range block {
		trimmed := strings.TrimSpace(line)
		if isTableSeparator(trimmed) {
			continue
		}
		cells := tableCells(trimmed)
		if len(cells) == 0 {
			continue
		}

		if !wroteHeader {
			b.WriteString("<thead>\n<tr>")
			for _, c := range cells {
				b.WriteString("<th>" + renderInline(c) + "</th>")
			}
			b.WriteString("</tr>\n</thead>\n")
			wroteHeader = true

			continue
		}

		if !openedBody {
			b.WriteString("<tbody>\n")
			openedBody = true
		}
		b.WriteString("<tr>")
		for _, c := range cells {
			b.WriteString("<td>" + renderInline(c) + "</td>")
		}
		b.WriteString("</tr>\n")
	}

	if openedBody {
		b.WriteString("</tbody>\n")
	}
	b.WriteString("</table>\n</div>\n")

	return b.String()
}

var (
	boldPattern   = regexp.MustCompile(`\*\*([^*]+)\*\*`)
	italicPattern = regexp.MustCompile(`\*([^*]+)\*`)
	linkPattern   = regexp.MustCompile(`\[([^\]]*)\]\(([^)\s]+)\)`)
)

// renderInline escapes text, then applies inline markup. Code spans are
// escaped but otherwise left alone so their contents are never reinterpreted.
func renderInline(text string) string {
	var b strings.Builder

	for i, segment := range strings.Split(text, "`") {
		if i%2 == 1 {
			b.WriteString("<code>" + html.EscapeString(segment) + "</code>")

			continue
		}
		b.WriteString(renderEmphasis(html.EscapeString(segment)))
	}

	return b.String()
}

// renderEmphasis applies bold, italic, and links to already-escaped text.
func renderEmphasis(escaped string) string {
	out := boldPattern.ReplaceAllString(escaped, "<strong>$1</strong>")
	out = italicPattern.ReplaceAllString(out, "<em>$1</em>")
	out = linkPattern.ReplaceAllStringFunc(out, func(match string) string {
		parts := linkPattern.FindStringSubmatch(match)
		label, href := parts[1], parts[2]
		if !isSafeHref(href) {
			// Leave an unsafe target as plain text rather than linking it.
			return label
		}

		return `<a href="` + href + `" rel="noopener noreferrer" target="_blank">` + label + `</a>`
	})

	return out
}

// isSafeHref allows only http(s) and same-document or relative targets, so a
// report can never introduce a javascript: or data: link.
func isSafeHref(href string) bool {
	lower := strings.ToLower(href)
	switch {
	case strings.HasPrefix(lower, "http://"), strings.HasPrefix(lower, "https://"):
		return true
	case strings.HasPrefix(href, "#"), strings.HasPrefix(href, "/"):
		return true
	case strings.Contains(lower, ":"):
		// Any other scheme (javascript:, data:, file:) is refused.
		return false
	default:
		return true
	}
}
