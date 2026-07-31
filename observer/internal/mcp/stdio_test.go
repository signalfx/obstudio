package mcp

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"

	"github.com/signalfx/obstudio/observer/internal/otlp"
	"github.com/signalfx/obstudio/observer/internal/store"
)

func TestRunStdioSplunkConnectionRealmUsesMetricsAndTraces(t *testing.T) {
	s := store.New()
	metricsController, err := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{
		Realm:       "us0",
		AccessToken: "not-returned-by-realm-tool",
	})
	if err != nil {
		t.Fatalf("create metrics export controller: %v", err)
	}
	tracesController, err := otlp.NewSplunkTracesExportController(otlp.SplunkTracesExporterConfig{
		Realm:       "us0",
		AccessToken: "not-returned-by-realm-tool",
	})
	if err != nil {
		t.Fatalf("create traces export controller: %v", err)
	}

	req := `{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"observer_splunk_connection_realm","arguments":{}}}` + "\n"
	var out bytes.Buffer
	RunStdio(s, strings.NewReader(req), &out, metricsController, tracesController)

	var resp jsonRPCResponse
	if err := json.Unmarshal(bytes.TrimSpace(out.Bytes()), &resp); err != nil {
		t.Fatalf("unmarshal stdio response %q: %v", out.String(), err)
	}
	if resp.Error != nil {
		t.Fatalf("unexpected stdio error: %+v", resp.Error)
	}
	result := toMapAny(resp.Result)
	content := toSliceAny(result["content"])
	if len(content) != 1 {
		t.Fatalf("content = %#v, want one text result", content)
	}
	text, _ := toMapAny(content[0])["text"].(string)
	var payload map[string]any
	if err := json.Unmarshal([]byte(text), &payload); err != nil {
		t.Fatalf("unmarshal tool payload %q: %v", text, err)
	}
	if payload["realm"] != "us0" {
		t.Fatalf("realm = %v, want us0", payload["realm"])
	}
}
