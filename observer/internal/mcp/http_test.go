package mcp

import (
	"bufio"
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/signalfx/obstudio/observer/internal/store"
)

func newHTTPTestServer(t *testing.T) *httptest.Server {
	t.Helper()

	mux := http.NewServeMux()
	Register(mux, store.New())
	return httptest.NewServer(mux)
}

func TestHTTPGetStreamReturnsEventStream(t *testing.T) {
	server := newHTTPTestServer(t)
	defer server.Close()

	req, err := http.NewRequest(http.MethodGet, server.URL+"/mcp", nil)
	if err != nil {
		t.Fatalf("new request: %v", err)
	}
	req.Header.Set("Accept", "text/event-stream")

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("get /mcp: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}
	if got := resp.Header.Get("Content-Type"); !strings.HasPrefix(got, "text/event-stream") {
		t.Fatalf("expected text/event-stream, got %q", got)
	}

	line, err := bufio.NewReader(resp.Body).ReadString('\n')
	if err != nil {
		t.Fatalf("read first SSE line: %v", err)
	}
	if strings.TrimSpace(line) != ": connected" {
		t.Fatalf("expected initial SSE comment, got %q", line)
	}
}

func TestHTTPInitializeReturnsSessionIDAndSupportsSessionRequests(t *testing.T) {
	server := newHTTPTestServer(t)
	defer server.Close()

	initialize := map[string]any{
		"jsonrpc": "2.0",
		"id":      1,
		"method":  "initialize",
		"params": map[string]any{
			"protocolVersion": "2025-06-18",
		},
	}
	body, _ := json.Marshal(initialize)

	req, err := http.NewRequest(http.MethodPost, server.URL+"/mcp", bytes.NewReader(body))
	if err != nil {
		t.Fatalf("new initialize request: %v", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json, text/event-stream")

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("initialize /mcp: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}

	sessionID := resp.Header.Get("Mcp-Session-Id")
	if sessionID == "" {
		t.Fatalf("expected Mcp-Session-Id header")
	}

	var initResp map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&initResp); err != nil {
		t.Fatalf("decode initialize response: %v", err)
	}
	if initResp["result"] == nil {
		t.Fatalf("expected initialize result")
	}

	toolsList := map[string]any{
		"jsonrpc": "2.0",
		"id":      2,
		"method":  "tools/list",
	}
	toolsBody, _ := json.Marshal(toolsList)

	req, err = http.NewRequest(http.MethodPost, server.URL+"/mcp", bytes.NewReader(toolsBody))
	if err != nil {
		t.Fatalf("new tools/list request: %v", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json, text/event-stream")
	req.Header.Set("Mcp-Session-Id", sessionID)

	resp, err = http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("tools/list /mcp: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}

	var toolsResp map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&toolsResp); err != nil {
		t.Fatalf("decode tools/list response: %v", err)
	}

	result, ok := toolsResp["result"].(map[string]any)
	if !ok {
		t.Fatalf("expected result object, got %T", toolsResp["result"])
	}
	tools, ok := result["tools"].([]any)
	if !ok || len(tools) == 0 {
		t.Fatalf("expected non-empty tools array")
	}
}

func TestHTTPDeleteTerminatesSession(t *testing.T) {
	server := newHTTPTestServer(t)
	defer server.Close()

	initialize := map[string]any{
		"jsonrpc": "2.0",
		"id":      1,
		"method":  "initialize",
		"params": map[string]any{
			"protocolVersion": "2025-06-18",
		},
	}
	body, _ := json.Marshal(initialize)

	req, err := http.NewRequest(http.MethodPost, server.URL+"/mcp", bytes.NewReader(body))
	if err != nil {
		t.Fatalf("new initialize request: %v", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("initialize /mcp: %v", err)
	}
	sessionID := resp.Header.Get("Mcp-Session-Id")
	resp.Body.Close()
	if sessionID == "" {
		t.Fatalf("expected Mcp-Session-Id header")
	}

	req, err = http.NewRequest(http.MethodDelete, server.URL+"/mcp", nil)
	if err != nil {
		t.Fatalf("new delete request: %v", err)
	}
	req.Header.Set("Mcp-Session-Id", sessionID)

	resp, err = http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("delete /mcp: %v", err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusNoContent {
		t.Fatalf("expected 204, got %d", resp.StatusCode)
	}

	toolsList := map[string]any{
		"jsonrpc": "2.0",
		"id":      2,
		"method":  "tools/list",
	}
	toolsBody, _ := json.Marshal(toolsList)

	req, err = http.NewRequest(http.MethodPost, server.URL+"/mcp", bytes.NewReader(toolsBody))
	if err != nil {
		t.Fatalf("new tools/list request: %v", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Mcp-Session-Id", sessionID)

	resp, err = http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("tools/list /mcp after delete: %v", err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusNotFound {
		t.Fatalf("expected 404 after deleting session, got %d", resp.StatusCode)
	}
}

func TestHTTPAllowsPostWithoutSessionForExistingClients(t *testing.T) {
	server := newHTTPTestServer(t)
	defer server.Close()

	toolsList := map[string]any{
		"jsonrpc": "2.0",
		"id":      1,
		"method":  "tools/list",
	}
	body, _ := json.Marshal(toolsList)

	req, err := http.NewRequest(http.MethodPost, server.URL+"/mcp", bytes.NewReader(body))
	if err != nil {
		t.Fatalf("new tools/list request: %v", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("tools/list /mcp: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}

	var toolsResp map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&toolsResp); err != nil {
		t.Fatalf("decode tools/list response: %v", err)
	}
	if toolsResp["result"] == nil {
		t.Fatalf("expected tools/list result, got %#v", toolsResp)
	}
}

func TestHTTPRejectsMalformedJSONWithRPCParseError(t *testing.T) {
	server := newHTTPTestServer(t)
	defer server.Close()

	req, err := http.NewRequest(http.MethodPost, server.URL+"/mcp", strings.NewReader("{"))
	if err != nil {
		t.Fatalf("new malformed request: %v", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("post malformed json: %v", err)
	}
	defer resp.Body.Close()

	if got := resp.Header.Get("Content-Type"); !strings.HasPrefix(got, "application/json") {
		t.Fatalf("expected application/json, got %q", got)
	}

	var payload map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&payload); err != nil {
		t.Fatalf("decode parse error response: %v", err)
	}

	errPayload, ok := payload["error"].(map[string]any)
	if !ok {
		t.Fatalf("expected error object, got %#v", payload)
	}
	if code, ok := errPayload["code"].(float64); !ok || code != -32700 {
		t.Fatalf("expected parse error code -32700, got %#v", errPayload["code"])
	}
}

func TestHTTPDeleteRequiresSessionHeader(t *testing.T) {
	server := newHTTPTestServer(t)
	defer server.Close()

	req, err := http.NewRequest(http.MethodDelete, server.URL+"/mcp", nil)
	if err != nil {
		t.Fatalf("new delete request: %v", err)
	}

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("delete /mcp: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", resp.StatusCode)
	}
}

func TestHTTPLocalhostOriginIsAccepted(t *testing.T) {
	server := newHTTPTestServer(t)
	defer server.Close()

	req, err := http.NewRequest(http.MethodGet, server.URL+"/mcp", nil)
	if err != nil {
		t.Fatalf("new request: %v", err)
	}
	req.Header.Set("Origin", "http://localhost:3000")

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("get /mcp: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected 200 for localhost origin, got %d", resp.StatusCode)
	}
}

func TestHTTPRejectsRemoteOrigins(t *testing.T) {
	server := newHTTPTestServer(t)
	defer server.Close()

	req, err := http.NewRequest(http.MethodGet, server.URL+"/mcp", nil)
	if err != nil {
		t.Fatalf("new request: %v", err)
	}
	req.Header.Set("Origin", "https://example.com")

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("get /mcp: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusForbidden {
		t.Fatalf("expected 403 for remote origin, got %d", resp.StatusCode)
	}
}
