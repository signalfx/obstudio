package store

import "testing"

func TestIsAgentOrigin(t *testing.T) {
	spans := []struct {
		name string
		span Span
		want bool
	}{
		{"app span", Span{Name: "GET /cart", Resource: Resource{ServiceName: "checkout"}}, false},
		{"claude classifier span", Span{Name: "claude_code.tool", Resource: Resource{ServiceName: "x"}, Scope: Scope{Name: "claude"}}, true},
		{"codex resource", Span{Name: "tool.execute", Resource: Resource{ServiceName: "codex-app-server"}, Scope: Scope{Name: "app"}}, true},
		{"codex underscore", Span{Name: "x", Resource: Resource{ServiceName: "codex_cli_rs"}}, true},
		{"claude-code desktop", Span{Name: "x", Resource: Resource{ServiceName: " Claude-Code-Desktop "}}, true},
		{"codex exact", Span{Name: "x", Resource: Resource{ServiceName: "codex"}}, true},
		{"codexy is an app", Span{Name: "x", Resource: Resource{ServiceName: "codexy"}}, false},
		{"codex. span name", Span{Name: "codex.turn", Resource: Resource{ServiceName: "app"}}, true},
	}
	for _, c := range spans {
		if got := IsAgentOrigin(c.span); got != c.want {
			t.Errorf("%s: %v, want %v", c.name, got, c.want)
		}
	}
	metrics := []struct {
		name string
		m    MetricDataPoint
		want bool
	}{
		{"app metric", MetricDataPoint{Name: "http.server.duration"}, false},
		{"token usage", MetricDataPoint{Name: "claude_code.token.usage"}, true},
		{"session count", MetricDataPoint{Name: "claude_code.session.count"}, true},
		{"codex metric", MetricDataPoint{Name: "codex.turns"}, true},
		{"agent resource", MetricDataPoint{Name: "x", Resource: Resource{ServiceName: "claude-code"}}, true},
	}
	for _, c := range metrics {
		if got := IsAgentOrigin(c.m); got != c.want {
			t.Errorf("%s: %v, want %v", c.name, got, c.want)
		}
	}
	logs := []struct {
		name string
		l    LogRecord
		want bool
	}{
		{"app log", LogRecord{Body: "hello", Resource: Resource{ServiceName: "checkout"}}, false},
		{"claude api_request", LogRecord{Attributes: map[string]any{"event.name": "api_request", "model": "claude-sonnet-4-5"}}, true},
		{"codex tool_result", LogRecord{Attributes: map[string]any{"event.name": "codex.tool_result"}}, true},
		{"claude_code body", LogRecord{Body: "claude_code.user_prompt"}, true},
		{"malformed hook event", LogRecord{Attributes: map[string]any{"event.name": "obstudio.repository_correlation"}, Resource: Resource{ServiceName: "obstudio-hook"}}, true},
		{"hook event in body", LogRecord{Body: "obstudio.repository_correlation"}, true},
	}
	for _, c := range logs {
		if got := IsAgentOrigin(c.l); got != c.want {
			t.Errorf("%s: %v, want %v", c.name, got, c.want)
		}
	}
}

func TestReceiptCallback(t *testing.T) {
	s := New()
	var got []Receipt
	s.SetReceiptCallback(func(r Receipt) { got = append(got, r) })
	s.AddSpansForConnection("", []Span{{Name: "a", TraceID: "t", SpanID: "s"}})
	s.AddMetricsForConnection("", []MetricDataPoint{{Name: "m"}})
	s.AddLogsForConnection("", []LogRecord{{Body: "l"}})
	s.AddInternalLogs([]LogRecord{{Body: "internal"}})
	s.AddAgentSpansForConnection("", AgentSpanRoute{}, []Span{{Name: "agent", TraceID: "t2", SpanID: "s2"}})
	s.AddMetricsForConnection("", nil)
	if len(got) != 3 || len(got[0].Spans) != 1 || len(got[1].Metrics) != 1 || len(got[2].Logs) != 1 {
		t.Fatalf("receipts = %+v", got)
	}
}
