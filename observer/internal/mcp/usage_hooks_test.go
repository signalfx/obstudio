package mcp

import (
	"bytes"
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/signalfx/obstudio/observer/internal/otlp"
	"github.com/signalfx/obstudio/observer/internal/store"
	"github.com/signalfx/obstudio/observer/internal/validator"
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

// A validation run counts only when the tool actually ran the validator.
// Analyses answered from a retained result and failed calls do not count.
func TestUsageHooksValidationRunOnMCPTools(t *testing.T) {
	cases := []struct {
		name       string
		tool       string
		args       map[string]any
		retained   bool
		noRunner   bool
		wantRuns   int
		wantRunner int
		wantError  bool
	}{
		{name: "analyze runs fresh", tool: "observer_validation_analyze", wantRuns: 1, wantRunner: 1},
		{name: "analyze answers from retained result", tool: "observer_validation_analyze", retained: true},
		{name: "refresh runs", tool: "observer_validation_refresh", retained: true, wantRuns: 1, wantRunner: 1},
		{name: "refresh without runner fails", tool: "observer_validation_refresh", noRunner: true, wantError: true},
		{name: "analyze latest_ok without result fails", tool: "observer_validation_analyze", args: map[string]any{"freshness": "latest_ok"}, wantError: true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			v := validator.NewStore()
			v.SetRuntimeStatus(validator.StatusIdle, "Validation has not been run yet")
			if tc.retained {
				v.StartRun("run-0", time.Unix(10, 0))
				v.CompleteRun("run-0", nil, validator.RunStats{}, time.Unix(20, 0))
			}
			runs := 0
			opts := []any{v, UsageHooks{ValidationRun: func() { runs++ }}}
			runner := &fakeValidationRunner{onRun: func(context.Context) validator.Summary {
				summary := v.StartRun("run-1", time.Unix(30, 0))
				go v.CompleteRun("run-1", nil, validator.RunStats{}, time.Unix(40, 0))
				return summary
			}}
			if !tc.noRunner {
				opts = append(opts, runner)
			}
			args := map[string]any{"timeoutSeconds": 5}
			for k, val := range tc.args {
				args[k] = val
			}
			resp, handled := NewDispatcher(store.New(), opts...).Dispatch(jsonRPCRequest{
				ID: 1, JSONRPC: "2.0", Method: "tools/call",
				Params: map[string]any{"name": tc.tool, "arguments": args},
			})
			if !handled || resp.Error != nil {
				t.Fatalf("unexpected response: %+v", resp)
			}
			if got := resp.Result.(toolResult).IsError; got != tc.wantError {
				t.Fatalf("tool error = %v, want %v", got, tc.wantError)
			}
			if runner.calls != tc.wantRunner {
				t.Fatalf("runner called %d times, want %d", runner.calls, tc.wantRunner)
			}
			if runs != tc.wantRuns {
				t.Fatalf("ValidationRun fired %d times, want %d", runs, tc.wantRuns)
			}
		})
	}
}
