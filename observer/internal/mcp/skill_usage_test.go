package mcp

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/signalfx/obstudio/observer/internal/otlp"
	"github.com/signalfx/obstudio/observer/internal/store"
)

func TestSkillTokenFilterUsesOnlyRequestOwnedMarkers(t *testing.T) {
	s := store.New()
	now := time.Now()
	s.AddSpansForConnection("host", []store.Span{{TraceID: "trace", SpanID: "root", Name: "claude_code.interaction", StartTime: now, EndTime: now.Add(time.Second), Resource: store.Resource{ServiceName: "claude-code"}, Attributes: map[string]any{"prompt.id": "prompt", "session.id": "session", "skill.name": []string{"alpha", "beta"}}}})
	for i, skill := range []string{"alpha", "beta", ""} {
		attrs := map[string]any{"event.name": "api_request", "request_id": skill + "-request", "prompt.id": "prompt", "session.id": "session", "input_tokens": int64(i + 1), "output_tokens": int64(0), "cache_read_tokens": int64(0), "cache_creation_tokens": int64(0)}
		if skill != "" {
			attrs["skill.name"] = skill
		}
		s.AddLogsForConnection("host", []store.LogRecord{{Timestamp: now.Add(time.Duration(i) * time.Millisecond), TraceID: "trace", Body: "claude_code.api_request", Resource: store.Resource{ServiceName: "claude-code"}, Attributes: attrs}})
	}
	for i, skill := range []string{"alpha", "beta"} {
		got := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"skillName": skill})
		usage := toMapAny(got["usage"])
		if usage["inputTokens"] != float64(i+1) {
			t.Fatalf("task total attributed to %s: %+v", skill, got)
		}
		if got["skillAttribution"] != "request_or_metric_series_only" {
			t.Fatal("missing measurement scope")
		}
	}
	got := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"skillName": "absent"})
	if len(toSliceAny(got["tasks"])) != 0 {
		t.Fatal("invented skill association")
	}
	all := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{})
	if toMapAny(all["unattributedRequestUsage"])["inputTokens"] != float64(3) {
		t.Fatalf("unattributed request not disclosed: %+v", all)
	}
}

func TestSkillTokenFilterSupportsMetricOnlySeries(t *testing.T) {
	s := store.New()
	now := time.Now()
	for _, skill := range []string{"alpha", "beta"} {
		for _, kind := range []string{"input", "output", "cacheRead", "cacheCreation"} {
			value := float64(1)
			if skill == "beta" {
				value = 100
			}
			s.AddMetricsForConnection("host", []store.MetricDataPoint{{Name: "claude_code.token.usage", Type: "sum", Value: value, IsMonotonic: true, Temporality: "cumulative", StartTime: now, Timestamp: now.Add(time.Second), Attributes: map[string]any{"session.id": "session", "skill.name": skill, "type": kind}}})
		}
	}
	got := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"skillName": "alpha"})
	if usage := toMapAny(got["usage"]); usage["inputTokens"] != float64(3) || usage["outputTokens"] != float64(1) {
		t.Fatalf("cross-skill metric total: %+v", got)
	}
	rows := toSliceAny(got["tasks"])
	if len(rows) != 1 || toMapAny(rows[0])["skillAttribution"] != "metric_series" {
		t.Fatalf("missing series scope: %+v", got)
	}
}

func TestSkillTokenFilterExcludesConflictingRequestMarkers(t *testing.T) {
	s := store.New()
	now := time.Now()
	for _, skill := range []string{"alpha", "beta"} {
		s.AddLogsForConnection("host", []store.LogRecord{{Timestamp: now, Body: "claude_code.api_request", Attributes: map[string]any{"session.id": "session", "request_id": "same-request", "skill.name": skill, "input_tokens": int64(5), "output_tokens": int64(0), "cache_read_tokens": int64(0), "cache_creation_tokens": int64(0)}}})
	}
	for _, skill := range []string{"alpha", "beta"} {
		got := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"skillName": skill})
		if len(toSliceAny(got["tasks"])) != 0 {
			t.Fatalf("conflicting request attributed to %s: %+v", skill, got)
		}
	}
	got := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{})
	if toMapAny(got["sharedRequestUsage"])["inputTokens"] != float64(5) {
		t.Fatalf("shared request was lost or counted twice: %+v", got)
	}
}

func TestSkillActivationRemainsVisibleWithoutUsage(t *testing.T) {
	s := store.New()
	s.AddLogsForConnection("host", []store.LogRecord{{Timestamp: time.Now(), Body: "claude_code.skill_activated", Attributes: map[string]any{"skill.name": "alpha", "invocation_trigger": "nested-skill"}}})
	got := callTokenUsageOverview(t, NewDispatcher(s), map[string]any{"skillName": "alpha"})
	if len(toSliceAny(got["skillActivations"])) != 1 || toMapAny(got["usage"])["effectiveTotalTokens"] != nil {
		t.Fatalf("activation incorrectly requires token usage: %+v", got)
	}
}

func TestSkillActivationOTLPAndMCPTransports(t *testing.T) {
	s := store.New()
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	address := listener.Addr().String()
	listener.Close()
	receiver, err := otlp.StartReceiver(context.Background(), s, "127.0.0.1:0", address)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { receiver.Shutdown(context.Background()) })
	payload := `{"resourceLogs":[{"resource":{"attributes":[{"key":"service.name","value":{"stringValue":"claude-code"}}]},"scopeLogs":[{"logRecords":[{"timeUnixNano":"1780000000000000000","body":{"stringValue":"claude_code.skill_activated"},"attributes":[{"key":"skill.name","value":{"stringValue":"alpha"}},{"key":"session.id","value":{"stringValue":"session"}},{"key":"event.sequence","value":{"intValue":"1"}}]}]}]}]}`
	for i := 0; i < 2; i++ {
		resp, err := http.Post("http://"+address+"/v1/logs", "application/json", bytes.NewBufferString(payload))
		if err != nil {
			t.Fatal(err)
		}
		io.Copy(io.Discard, resp.Body)
		resp.Body.Close()
		if resp.StatusCode != 200 {
			t.Fatalf("OTLP response %d", resp.StatusCode)
		}
	}
	request := `{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"observer_token_usage_overview","arguments":{"skillName":"alpha"}}}`
	mux := http.NewServeMux()
	Register(mux, s)
	server := httptest.NewServer(mux)
	defer server.Close()
	resp, err := http.Post(server.URL+"/mcp", "application/json", bytes.NewBufferString(request))
	if err != nil {
		t.Fatal(err)
	}
	httpResult, err := io.ReadAll(resp.Body)
	resp.Body.Close()
	if err != nil {
		t.Fatal(err)
	}
	var stdioResult bytes.Buffer
	RunStdio(s, io.NopCloser(bytes.NewBufferString(request+"\n")), &stdioResult)
	for _, data := range [][]byte{httpResult, stdioResult.Bytes()} {
		var response struct {
			Result toolResult `json:"result"`
		}
		if err := json.Unmarshal(data, &response); err != nil {
			t.Fatal(err)
		}
		got := toMapAny(parseToolResult(t, response.Result))
		if len(toSliceAny(got["skillActivations"])) != 1 {
			t.Fatalf("transport activation lost or duplicated: %s", data)
		}
	}
}
