package audit

import (
	"strings"
	"testing"
)

func TestRenderHTMLStructure(t *testing.T) {
	got := RenderHTML(instrumentedReport, "otel.md")

	for _, want := range []string{
		"<!doctype html>",
		"<title>otel.md</title>",
		"<h1>Observability Report: checkout</h1>",
		"<h2>RED Signals</h2>",
		"<h3>Spans</h3>",
		"<table>",
		"<th>Signal</th>",
		"<td>covered</td>",
		"<li>No OTLP log pipeline.</li>",
		"<strong>Language:</strong>",
		"<hr>",
	} {
		if !strings.Contains(got, want) {
			t.Errorf("rendered HTML missing %q", want)
		}
	}
}

func TestRenderHTMLEscapesContent(t *testing.T) {
	report := "# Report\n\nA <script>alert(1)</script> body & an \"attr\".\n"

	got := RenderHTML(report, "otel.md")

	if strings.Contains(got, "<script>") {
		t.Error("raw <script> survived into the output")
	}
	if !strings.Contains(got, "&lt;script&gt;alert(1)&lt;/script&gt;") {
		t.Errorf("script tag was not escaped: %s", got)
	}
	if !strings.Contains(got, "&amp; an") {
		t.Error("ampersand was not escaped")
	}
}

func TestRenderHTMLEscapesTitle(t *testing.T) {
	got := RenderHTML("# ok\n", `"><script>x</script>`)

	if strings.Contains(got, "<script>x</script>") {
		t.Errorf("title was not escaped: %s", got)
	}
}

// Code spans must be escaped but never reinterpreted as emphasis.
func TestRenderHTMLCodeSpans(t *testing.T) {
	got := RenderHTML("Run `$otel-instrument` and `a**b**c` now.\n", "otel.md")

	if !strings.Contains(got, "<code>$otel-instrument</code>") {
		t.Errorf("code span not rendered: %s", got)
	}
	if !strings.Contains(got, "<code>a**b**c</code>") {
		t.Errorf("emphasis inside a code span was reinterpreted: %s", got)
	}
}

func TestRenderHTMLLinkSafety(t *testing.T) {
	report := "# Links\n\n" +
		"- [docs](https://example.com/a)\n" +
		"- [xss](javascript:alert)\n" +
		"- [data](data:text/html;base64,PHN2Zz4=)\n"

	got := RenderHTML(report, "otel.md")

	if !strings.Contains(got, `<a href="https://example.com/a"`) {
		t.Errorf("https link was not rendered: %s", got)
	}
	if strings.Contains(strings.ToLower(got), "javascript:") {
		t.Errorf("javascript: URL survived: %s", got)
	}
	if strings.Contains(strings.ToLower(got), "href=\"data:") {
		t.Errorf("data: URL survived as an href: %s", got)
	}
	// Refused links degrade to their label rather than vanishing.
	if !strings.Contains(got, "<li>xss</li>") {
		t.Errorf("refused link lost its label: %s", got)
	}
}

// A bullet wrapped across lines is one list item, not two.
func TestRenderHTMLJoinsWrappedBullets(t *testing.T) {
	report := "# R\n\n## Gaps\n- first part\n  second part\n- another\n"

	got := RenderHTML(report, "otel.md")

	if !strings.Contains(got, "<li>first part second part</li>") {
		t.Errorf("wrapped bullet was not joined: %s", got)
	}
	if strings.Count(got, "<li>") != 2 {
		t.Errorf("expected 2 list items, got: %s", got)
	}
}

func TestRenderHTMLTableSeparatorIsNotARow(t *testing.T) {
	report := "# R\n\n| A | B |\n|---|---|\n| 1 | 2 |\n"

	got := RenderHTML(report, "otel.md")

	if strings.Contains(got, "<td>---</td>") {
		t.Errorf("separator row was rendered as data: %s", got)
	}
	if strings.Count(got, "<tr>") != 2 {
		t.Errorf("expected a header row and one body row, got: %s", got)
	}
}

func TestRenderHTMLHandlesEmptyDocument(t *testing.T) {
	got := RenderHTML("", "otel.md")

	if !strings.Contains(got, "<main>") || !strings.Contains(got, "</html>") {
		t.Errorf("empty document did not produce a valid page: %s", got)
	}
}
