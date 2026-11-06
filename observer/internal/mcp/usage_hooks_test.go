package mcp

import (
	"bytes"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"

	"github.com/signalfx/obstudio/observer/internal/otlp"
	"github.com/signalfx/obstudio/observer/internal/store"
)

func TestUsageHooksToolsCallOnly(t *testing.T) {
	calls := 0
	mux := http.NewServeMux()
	Register(mux, store.New(), UsageHooks{ToolsCall: func() { calls++ }})
	post := func(body string) {
		req := httptest.NewRequest(http.MethodPost, "/mcp", strings.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		req.RemoteAddr = "127.0.0.1:50000"
		mux.ServeHTTP(httptest.NewRecorder(), req)
	}
	post(`{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}`)
	post(`{"jsonrpc":"2.0","id":2,"method":"tools/list"}`)
	post(`{"jsonrpc":"2.0","id":3,"method":"ping"}`)
	if calls != 0 {
		t.Fatalf("non-tools/call methods fired the hook %d times", calls)
	}
	post(`{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"observer_status","arguments":{}}}`)
	if calls != 1 {
		t.Fatalf("tools/call fired the hook %d times", calls)
	}
}

func TestUsageHooksAbsentAreIgnored(t *testing.T) {
	mux := http.NewServeMux()
	Register(mux, store.New())
	req := httptest.NewRequest(http.MethodPost, "/mcp", strings.NewReader(`{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"observer_status"}}`))
	req.RemoteAddr = "127.0.0.1:50000"
	mux.ServeHTTP(httptest.NewRecorder(), req)
}

func TestUsageHooksToolsCallOnStdio(t *testing.T) {
	var calls atomic.Int32
	hooks := UsageHooks{ToolsCall: func() { calls.Add(1) }}
	run := func(lines ...string) {
		var out bytes.Buffer
		RunStdio(store.New(), io.NopCloser(strings.NewReader(strings.Join(lines, "\n")+"\n")), &out, hooks)
	}
	run(`{"jsonrpc":"2.0","id":1,"method":"tools/list"}`)
	if n := calls.Load(); n != 0 {
		t.Fatalf("stdio tools/list fired the hook %d times", n)
	}
	run(`{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"observer_status","arguments":{}}}`)
	if n := calls.Load(); n != 1 {
		t.Fatalf("stdio tools/call fired the hook %d times", n)
	}
}

func TestUsageHooksConnectOnHeldCloudCredential(t *testing.T) {
	metrics, err := otlp.NewSplunkMetricsExportController(otlp.SplunkMetricsExporterConfig{})
	if err != nil {
		t.Fatal(err)
	}
	connects := 0
	d := NewDispatcher(store.New(), metrics, UsageHooks{Connect: func() { connects++ }})
	configure := func(args map[string]any) {
		t.Helper()
		resp, _ := d.Dispatch(jsonRPCRequest{ID: 1, JSONRPC: "2.0", Method: "tools/call", Params: map[string]any{
			"name": "observer_splunk_metrics_export_configure", "arguments": args,
		}})
		if resp.Error != nil {
			t.Fatalf("configure %v: %v", args, resp.Error)
		}
	}
	configure(map[string]any{"enabled": false})
	configure(map[string]any{"enabled": true, "endpoint": "https://collector.example/v2/datapoint/otlp", "accessToken": "tok"})
	if connects != 0 {
		t.Fatalf("no cloud credential reported %d connects", connects)
	}
	// Export stays disabled: connecting and enabling are separate steps.
	configure(map[string]any{"enabled": false, "realm": "us1", "accessToken": "tok"})
	if connects != 1 {
		t.Fatalf("held cloud credential reported %d connects, want 1", connects)
	}
}
