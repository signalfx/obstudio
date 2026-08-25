package mcp

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/signalfx/obstudio/observer/internal/freeaccount"
	"github.com/signalfx/obstudio/observer/internal/store"
)

const httpTestControlToken = "observer-http-control-secret"

func newHTTPTestServer(t *testing.T) *httptest.Server {
	t.Helper()
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", httpTestControlToken)

	mux := http.NewServeMux()
	Register(mux, store.New())
	return httptest.NewServer(mux)
}

func authorizeHTTPRequest(request *http.Request) {
	request.Header.Set("Authorization", "Bearer "+httpTestControlToken)
}

func assertHTTPUnauthorized(t *testing.T, response *httptest.ResponseRecorder) {
	t.Helper()
	if response.Code != http.StatusUnauthorized {
		t.Fatalf("status = %d, want %d", response.Code, http.StatusUnauthorized)
	}
	if got := response.Header().Get("WWW-Authenticate"); got != `Bearer realm="obstudio"` {
		t.Fatalf("WWW-Authenticate = %q, want bearer challenge", got)
	}
}

func TestHTTPGetStreamReturnsEventStream(t *testing.T) {
	server := newHTTPTestServer(t)
	defer server.Close()

	req, err := http.NewRequest(http.MethodGet, server.URL+"/mcp", nil)
	if err != nil {
		t.Fatalf("new request: %v", err)
	}
	req.Header.Set("Accept", "text/event-stream")
	authorizeHTTPRequest(req)

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
	authorizeHTTPRequest(req)

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
	authorizeHTTPRequest(req)

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
	authorizeHTTPRequest(req)

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("initialize /mcp: %v", err)
	}
	sessionID := resp.Header.Get("Mcp-Session-Id")
	resp.Body.Close()
	if sessionID == "" {
		t.Fatalf("expected Mcp-Session-Id header")
	}

	unauthorizedDelete, err := http.NewRequest(http.MethodDelete, server.URL+"/mcp", nil)
	if err != nil {
		t.Fatalf("new unauthorized delete request: %v", err)
	}
	unauthorizedDelete.Header.Set("Mcp-Session-Id", sessionID)
	unauthorizedDeleteResponse, err := http.DefaultClient.Do(unauthorizedDelete)
	if err != nil {
		t.Fatalf("unauthorized delete /mcp: %v", err)
	}
	unauthorizedDeleteResponse.Body.Close()
	if unauthorizedDeleteResponse.StatusCode != http.StatusUnauthorized {
		t.Fatalf("unauthorized delete status = %d, want %d", unauthorizedDeleteResponse.StatusCode, http.StatusUnauthorized)
	}

	toolsList := map[string]any{
		"jsonrpc": "2.0",
		"id":      2,
		"method":  "tools/list",
	}
	toolsBody, _ := json.Marshal(toolsList)
	requestAfterUnauthorizedDelete, err := http.NewRequest(http.MethodPost, server.URL+"/mcp", bytes.NewReader(toolsBody))
	if err != nil {
		t.Fatalf("new tools/list request after unauthorized delete: %v", err)
	}
	requestAfterUnauthorizedDelete.Header.Set("Content-Type", "application/json")
	requestAfterUnauthorizedDelete.Header.Set("Mcp-Session-Id", sessionID)
	authorizeHTTPRequest(requestAfterUnauthorizedDelete)
	responseAfterUnauthorizedDelete, err := http.DefaultClient.Do(requestAfterUnauthorizedDelete)
	if err != nil {
		t.Fatalf("tools/list after unauthorized delete: %v", err)
	}
	responseAfterUnauthorizedDelete.Body.Close()
	if responseAfterUnauthorizedDelete.StatusCode != http.StatusOK {
		t.Fatalf("status after unauthorized delete = %d, want %d", responseAfterUnauthorizedDelete.StatusCode, http.StatusOK)
	}

	req, err = http.NewRequest(http.MethodDelete, server.URL+"/mcp", nil)
	if err != nil {
		t.Fatalf("new delete request: %v", err)
	}
	req.Header.Set("Mcp-Session-Id", sessionID)
	authorizeHTTPRequest(req)

	resp, err = http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("delete /mcp: %v", err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusNoContent {
		t.Fatalf("expected 204, got %d", resp.StatusCode)
	}

	req, err = http.NewRequest(http.MethodPost, server.URL+"/mcp", bytes.NewReader(toolsBody))
	if err != nil {
		t.Fatalf("new tools/list request: %v", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Mcp-Session-Id", sessionID)
	authorizeHTTPRequest(req)

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
	authorizeHTTPRequest(req)

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

func TestHTTPRequiresControlTokenBeforeDispatch(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", httpTestControlToken)
	s := store.New()
	s.AddLogsForConnection("test", []store.LogRecord{{Body: "must remain"}})
	mux := http.NewServeMux()
	Register(mux, s)

	toolsListBody := []byte(`{"jsonrpc":"2.0","id":1,"method":"tools/list"}`)
	toolsListRequest := httptest.NewRequest(http.MethodPost, "/mcp", bytes.NewReader(toolsListBody))
	toolsListResponse := httptest.NewRecorder()
	mux.ServeHTTP(toolsListResponse, toolsListRequest)
	assertHTTPUnauthorized(t, toolsListResponse)

	clearBody := []byte(`{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"observer_clear","arguments":{}}}`)
	clearRequest := httptest.NewRequest(http.MethodPost, "/mcp", bytes.NewReader(clearBody))
	clearRequest.Header.Set("Authorization", "Bearer wrong-token")
	clearResponse := httptest.NewRecorder()
	mux.ServeHTTP(clearResponse, clearRequest)
	assertHTTPUnauthorized(t, clearResponse)
	if got := s.Stats().LogCount; got != 1 {
		t.Fatalf("log count = %d after unauthorized clear, want 1", got)
	}

	streamRequest := httptest.NewRequest(http.MethodGet, "/mcp", nil)
	streamResponse := httptest.NewRecorder()
	mux.ServeHTTP(streamResponse, streamRequest)
	assertHTTPUnauthorized(t, streamResponse)
}

func TestHTTPFailsClosedWithoutConfiguredControlToken(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", "")
	mux := http.NewServeMux()
	Register(mux, store.New())
	request := httptest.NewRequest(
		http.MethodPost,
		"/mcp",
		strings.NewReader(`{"jsonrpc":"2.0","id":1,"method":"tools/list"}`),
	)
	request.Header.Set("Authorization", "Bearer any-token")
	response := httptest.NewRecorder()
	mux.ServeHTTP(response, request)
	assertHTTPUnauthorized(t, response)
}

func TestHTTPOptionsDoesNotRequireControlToken(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", httpTestControlToken)
	mux := http.NewServeMux()
	Register(mux, store.New())
	request := httptest.NewRequest(http.MethodOptions, "/mcp", nil)
	response := httptest.NewRecorder()
	mux.ServeHTTP(response, request)
	if response.Code != http.StatusNoContent {
		t.Fatalf("status = %d, want %d", response.Code, http.StatusNoContent)
	}
}

func TestHTTPFreeAccountToolRequiresControlTokenEvenFromLoopback(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", "observer-control-secret")
	submitter := &fakeMCPFreeAccountSubmitter{result: freeaccount.Result{
		IntakeAcknowledged: true,
		Realm:              "au0",
		Region:             "apac-au",
		Message:            "Thank you for registering. Your free edition account is on its way!",
	}}
	mux := http.NewServeMux()
	Register(mux, store.New(), submitter)
	body := []byte(`{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"observer_splunk_free_account_create","arguments":{"firstName":"Ada","lastName":"Lovelace","email":"ada@example.com","termsAccepted":true}}}`)

	remoteRequest := httptest.NewRequest(http.MethodPost, "/mcp", bytes.NewReader(body))
	remoteRequest.RemoteAddr = "198.51.100.20:41234"
	remoteResponse := httptest.NewRecorder()
	mux.ServeHTTP(remoteResponse, remoteRequest)
	assertHTTPUnauthorized(t, remoteResponse)

	localBrowserRequest := httptest.NewRequest(http.MethodPost, "/mcp", bytes.NewReader(body))
	localBrowserRequest.RemoteAddr = "127.0.0.1:41235"
	localBrowserRequest.Header.Set("Origin", "http://127.0.0.1:5173")
	localBrowserResponse := httptest.NewRecorder()
	mux.ServeHTTP(localBrowserResponse, localBrowserRequest)
	assertHTTPUnauthorized(t, localBrowserResponse)
	if submitter.calls != 0 {
		t.Fatalf("loopback browser submitter calls = %d, want 0 without control token", submitter.calls)
	}

	forwardedRequest := httptest.NewRequest(http.MethodPost, "/mcp", bytes.NewReader(body))
	forwardedRequest.RemoteAddr = "127.0.0.1:41236"
	forwardedRequest.Header.Set("X-Forwarded-For", "198.51.100.20")
	forwardedResponse := httptest.NewRecorder()
	mux.ServeHTTP(forwardedResponse, forwardedRequest)
	assertHTTPUnauthorized(t, forwardedResponse)
	if submitter.calls != 0 {
		t.Fatalf("forwarded loopback submitter calls = %d, want 0 without control token", submitter.calls)
	}

	localRequest := httptest.NewRequest(http.MethodPost, "/mcp", bytes.NewReader(body))
	localRequest.RemoteAddr = "127.0.0.1:41237"
	localResponse := httptest.NewRecorder()
	mux.ServeHTTP(localResponse, localRequest)
	assertHTTPUnauthorized(t, localResponse)
	if submitter.calls != 0 {
		t.Fatalf("loopback submitter calls = %d, want 0 without control token", submitter.calls)
	}

	authorizedRequest := httptest.NewRequest(http.MethodPost, "/mcp", bytes.NewReader(body))
	authorizedRequest.RemoteAddr = "198.51.100.20:41238"
	authorizedRequest.Header.Set("Authorization", "Bearer observer-control-secret")
	authorizedResponse := httptest.NewRecorder()
	mux.ServeHTTP(authorizedResponse, authorizedRequest)
	if submitter.calls != 1 {
		t.Fatalf("authorized remote submitter calls = %d, want 1", submitter.calls)
	}

	detectBody := []byte(`{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"observer_splunk_free_account_region_detect","arguments":{}}}`)
	unauthorizedDetect := httptest.NewRequest(http.MethodPost, "/mcp", bytes.NewReader(detectBody))
	unauthorizedDetectResponse := httptest.NewRecorder()
	mux.ServeHTTP(unauthorizedDetectResponse, unauthorizedDetect)
	assertHTTPUnauthorized(t, unauthorizedDetectResponse)
	if submitter.detectionCalls != 0 {
		t.Fatalf("unauthenticated detection calls = %d, want 0", submitter.detectionCalls)
	}

	authorizedDetect := httptest.NewRequest(http.MethodPost, "/mcp", bytes.NewReader(detectBody))
	authorizedDetect.Header.Set("Authorization", "Bearer observer-control-secret")
	authorizedDetectResponse := httptest.NewRecorder()
	mux.ServeHTTP(authorizedDetectResponse, authorizedDetect)
	if submitter.detectionCalls != 1 {
		t.Fatalf("authorized detection calls = %d, want 1", submitter.detectionCalls)
	}
}

func TestHTTPFreeAccountToolPropagatesCanceledRequestContext(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", "observer-control-secret")
	submitter := &fakeMCPFreeAccountSubmitter{
		err: &freeaccount.Error{
			Code:      freeaccount.ErrorCodeCanceled,
			Message:   "The signup request was canceled before it was sent.",
			RetrySafe: true,
		},
	}
	mux := http.NewServeMux()
	Register(mux, store.New(), submitter)
	body := []byte(`{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"observer_splunk_free_account_create","arguments":{"firstName":"Ada","lastName":"Lovelace","email":"ada@example.com","termsAccepted":true}}}`)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	request := httptest.NewRequest(http.MethodPost, "/mcp", bytes.NewReader(body)).WithContext(ctx)
	request.RemoteAddr = "127.0.0.1:43123"
	request.Header.Set("Authorization", "Bearer observer-control-secret")
	response := httptest.NewRecorder()

	mux.ServeHTTP(response, request)

	if submitter.calls != 1 || !errors.Is(submitter.ctxErr, context.Canceled) {
		t.Fatalf("submitter calls=%d context error=%v, want one canceled call", submitter.calls, submitter.ctxErr)
	}
	if !strings.Contains(response.Body.String(), `request_canceled`) {
		t.Fatalf("response did not return safe canceled result: %s", response.Body.String())
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
	authorizeHTTPRequest(req)

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

func TestHTTPPreservesLargeNumericRequestID(t *testing.T) {
	server := newHTTPTestServer(t)
	defer server.Close()

	request, err := http.NewRequest(
		http.MethodPost,
		server.URL+"/mcp",
		strings.NewReader(`{"jsonrpc":"2.0","id":9007199254740993,"method":"tools/list"}`),
	)
	if err != nil {
		t.Fatalf("new request: %v", err)
	}
	request.Header.Set("Content-Type", "application/json")
	authorizeHTTPRequest(request)

	response, err := http.DefaultClient.Do(request)
	if err != nil {
		t.Fatalf("post large-ID request: %v", err)
	}
	defer response.Body.Close()

	var payload struct {
		ID json.RawMessage `json:"id"`
	}
	if err := json.NewDecoder(response.Body).Decode(&payload); err != nil {
		t.Fatalf("decode large-ID response: %v", err)
	}
	if string(payload.ID) != "9007199254740993" {
		t.Fatalf("response ID = %s, want 9007199254740993", payload.ID)
	}
}

func TestHTTPRejectsInvalidRequestIDTypes(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", httpTestControlToken)

	for name, id := range map[string]string{
		"boolean": "true",
		"object":  `{}`,
		"array":   `[]`,
	} {
		t.Run(name, func(t *testing.T) {
			mux := http.NewServeMux()
			Register(mux, store.New())
			request := httptest.NewRequest(
				http.MethodPost,
				"/mcp",
				strings.NewReader(`{"jsonrpc":"2.0","id":`+id+`,"method":"tools/list"}`),
			)
			authorizeHTTPRequest(request)
			response := httptest.NewRecorder()
			mux.ServeHTTP(response, request)

			var payload struct {
				ID    json.RawMessage `json:"id"`
				Error *jsonRPCError   `json:"error"`
			}
			if err := json.Unmarshal(response.Body.Bytes(), &payload); err != nil {
				t.Fatalf("unmarshal invalid-ID response %q: %v", response.Body.String(), err)
			}
			if string(payload.ID) != "null" || payload.Error == nil || payload.Error.Code != -32600 {
				t.Fatalf("invalid-ID response = %#v, want null ID and -32600", payload)
			}
		})
	}
}

func TestHTTPDeleteRequiresSessionHeader(t *testing.T) {
	server := newHTTPTestServer(t)
	defer server.Close()

	req, err := http.NewRequest(http.MethodDelete, server.URL+"/mcp", nil)
	if err != nil {
		t.Fatalf("new delete request: %v", err)
	}
	authorizeHTTPRequest(req)

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
	authorizeHTTPRequest(req)

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
	authorizeHTTPRequest(req)

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("get /mcp: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusForbidden {
		t.Fatalf("expected 403 for remote origin, got %d", resp.StatusCode)
	}
}
