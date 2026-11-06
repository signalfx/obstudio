package mcp

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

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
