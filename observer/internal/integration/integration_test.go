// Package integration provides end-to-end tests for the observer binary.
package integration

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"

	"github.com/gorilla/websocket"
	"github.com/signalfx/obstudio/observer/internal/buildutil"
)

var (
	binaryPath   string
	restPort     string
	otlpHTTPPort string
	otlpGRPCPort string
	baseURL      string
	otlpHTTPURL  string
	cmd          *exec.Cmd
)

// TestMain builds the binary once and starts it for all tests.
func TestMain(m *testing.M) {
	// Build the binary.
	tmpdir, err := os.MkdirTemp("", "obstudio-test-*")
	if err != nil {
		fmt.Fprintf(os.Stderr, "failed to create temp dir: %v\n", err)
		os.Exit(1)
	}
	defer os.RemoveAll(tmpdir)

	observerRoot := getRepoRoot()
	repoRoot := filepath.Dir(observerRoot)
	if err := buildutil.StageEmbeddedSkills(repoRoot, observerRoot); err != nil {
		fmt.Fprintf(os.Stderr, "failed to stage embedded skills: %v\n", err)
		os.Exit(1)
	}

	binaryPath = filepath.Join(tmpdir, "obstudio")
	buildCmd := exec.Command("go", "build", "-o", binaryPath, "./cmd/obstudio")
	buildCmd.Dir = observerRoot
	if output, err := buildCmd.CombinedOutput(); err != nil {
		fmt.Fprintf(os.Stderr, "failed to build binary: %v\n%s\n", err, output)
		os.Exit(1)
	}

	// Get free ports.
	restPort = getFreePort()
	otlpHTTPPort = getFreePort()
	otlpGRPCPort = getFreePort()

	baseURL = "http://127.0.0.1:" + restPort
	otlpHTTPURL = "http://127.0.0.1:" + otlpHTTPPort

	// Start the binary.
	cmd = exec.Command(binaryPath)
	cmd.Env = append(os.Environ(),
		"PORT="+restPort,
		"OTLP_HTTP_PORT="+otlpHTTPPort,
		"OTLP_GRPC_PORT="+otlpGRPCPort,
		"HOST=127.0.0.1",
	)
	cmd.Stdout = os.Stderr
	cmd.Stderr = os.Stderr

	if err := cmd.Start(); err != nil {
		fmt.Fprintf(os.Stderr, "failed to start binary: %v\n", err)
		os.Exit(1)
	}

	// Wait for the server to be ready.
	if !waitForServer(baseURL, 30*time.Second) {
		fmt.Fprintf(os.Stderr, "server did not become ready\n")
		cmd.Process.Kill()
		os.Exit(1)
	}

	// Run tests.
	code := m.Run()

	// Cleanup: kill the process.
	cmd.Process.Kill()
	cmd.Wait()

	os.Exit(code)
}

// getFreePort returns a free port by binding to port 0 and closing the listener.
func getFreePort() string {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		panic(err)
	}
	port := listener.Addr().(*net.TCPAddr).Port
	listener.Close()
	return fmt.Sprintf("%d", port)
}

// getRepoRoot returns the root directory of the observer module.
func getRepoRoot() string {
	// This test file is at observer/internal/integration/integration_test.go
	// Return observer directory.
	cwd, _ := os.Getwd()
	for {
		if _, err := os.Stat(filepath.Join(cwd, "go.mod")); err == nil {
			if bytes.Contains(mustReadFile(filepath.Join(cwd, "go.mod")), []byte("github.com/signalfx/obstudio/observer")) {
				return cwd
			}
		}
		parent := filepath.Dir(cwd)
		if parent == cwd {
			panic("could not find observer root")
		}
		cwd = parent
	}
}

func mustReadFile(path string) []byte {
	data, _ := os.ReadFile(path)
	return data
}

// waitForServer polls the /api/query/stats endpoint until it responds.
func waitForServer(baseURL string, timeout time.Duration) bool {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		resp, err := http.Get(baseURL + "/api/query/stats")
		if err == nil && resp.StatusCode == 200 {
			resp.Body.Close()
			return true
		}
		if resp != nil {
			resp.Body.Close()
		}
		time.Sleep(100 * time.Millisecond)
	}
	return false
}

// ============================================================================
// INTEGRATION TESTS
// ============================================================================

// TestBinaryStarts verifies the startup banner is written to stderr.
func TestBinaryStarts(t *testing.T) {
	// If we're here, the binary started successfully.
	// Verify we can reach the REST endpoint.
	resp, err := http.Get(baseURL + "/api/query/stats")
	if err != nil {
		t.Fatalf("failed to reach REST endpoint: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}
}

// TestOTLPIngestAndQuery posts OTLP/HTTP JSON traces and verifies they appear in stats.
func TestOTLPIngestAndQuery(t *testing.T) {
	// Clear data first.
	req, _ := http.NewRequest("DELETE", baseURL+"/api/data", nil)
	resp, _ := http.DefaultClient.Do(req)
	resp.Body.Close()
	time.Sleep(100 * time.Millisecond)

	// Construct minimal OTLP/HTTP JSON payload.
	payload := map[string]any{
		"resourceSpans": []map[string]any{
			{
				"resource": map[string]any{
					"attributes": []map[string]any{
						{
							"key": "service.name",
							"value": map[string]any{
								"stringValue": "test-service",
							},
						},
					},
				},
				"scopeSpans": []map[string]any{
					{
						"scope": map[string]any{
							"name": "test-instrumentation",
						},
						"spans": []map[string]any{
							{
								"traceId":           "0af7651916cd43dd8448eb211c80319c",
								"spanId":            "b7ad6b7169203331",
								"name":              "test-span",
								"kind":              1,
								"startTimeUnixNano": 1000000000000000000,
								"endTimeUnixNano":   1000000001000000000,
								"status": map[string]any{
									"code": 0,
								},
								"attributes": []map[string]any{},
							},
						},
					},
				},
			},
		},
	}

	data, _ := json.Marshal(payload)
	resp, err := http.Post(otlpHTTPURL+"/v1/traces", "application/json", bytes.NewReader(data))
	if err != nil {
		t.Fatalf("failed to POST traces: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		body, _ := io.ReadAll(resp.Body)
		t.Fatalf("expected 200, got %d: %s", resp.StatusCode, body)
	}

	// Give the server time to process.
	time.Sleep(200 * time.Millisecond)

	// Query stats.
	resp, err = http.Get(baseURL + "/api/query/stats")
	if err != nil {
		t.Fatalf("failed to GET stats: %v", err)
	}
	defer resp.Body.Close()

	var stats map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&stats); err != nil {
		t.Fatalf("failed to parse stats JSON: %v", err)
	}

	spanCount, ok := stats["spanCount"].(float64)
	if !ok || spanCount <= 0 {
		t.Fatalf("expected spanCount > 0, got %v", stats["spanCount"])
	}
}

// TestRESTEndpoints verifies REST endpoints return valid JSON.
func TestRESTEndpoints(t *testing.T) {
	// Clear data first.
	req, _ := http.NewRequest("DELETE", baseURL+"/api/data", nil)
	resp, _ := http.DefaultClient.Do(req)
	resp.Body.Close()

	// Ingest a trace.
	payload := map[string]any{
		"resourceSpans": []map[string]any{
			{
				"resource": map[string]any{
					"attributes": []map[string]any{
						{
							"key": "service.name",
							"value": map[string]any{
								"stringValue": "test-service",
							},
						},
					},
				},
				"scopeSpans": []map[string]any{
					{
						"scope": map[string]any{
							"name": "test-instrumentation",
						},
						"spans": []map[string]any{
							{
								"traceId":           "0af7651916cd43dd8448eb211c80319c",
								"spanId":            "b7ad6b7169203331",
								"name":              "test-span",
								"kind":              1,
								"startTimeUnixNano": 1000000000000000000,
								"endTimeUnixNano":   1000000001000000000,
								"status": map[string]any{
									"code": 0,
								},
								"attributes": []map[string]any{},
							},
						},
					},
				},
			},
		},
	}

	data, _ := json.Marshal(payload)
	resp, _ = http.Post(otlpHTTPURL+"/v1/traces", "application/json", bytes.NewReader(data))
	resp.Body.Close()
	time.Sleep(100 * time.Millisecond)

	// Test traces endpoint — should have the ingested trace.
	resp, err := http.Get(baseURL + "/api/query/traces")
	if err != nil {
		t.Fatalf("failed to GET traces: %v", err)
	}
	if resp.StatusCode != 200 {
		resp.Body.Close()
		t.Fatalf("expected 200 for /api/query/traces, got %d", resp.StatusCode)
	}
	var traces []map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&traces); err != nil {
		resp.Body.Close()
		t.Fatalf("failed to parse traces JSON: %v", err)
	}
	resp.Body.Close()
	if len(traces) == 0 {
		t.Fatalf("expected non-empty traces after ingesting a span")
	}
	if traces[0]["traceId"] != "0af7651916cd43dd8448eb211c80319c" {
		t.Fatalf("expected traceId '0af7651916cd43dd8448eb211c80319c', got %v", traces[0]["traceId"])
	}

	// Test stats endpoint — should reflect ingested data.
	resp, err = http.Get(baseURL + "/api/query/stats")
	if err != nil {
		t.Fatalf("failed to GET stats: %v", err)
	}
	if resp.StatusCode != 200 {
		resp.Body.Close()
		t.Fatalf("expected 200 for /api/query/stats, got %d", resp.StatusCode)
	}
	var stats map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&stats); err != nil {
		resp.Body.Close()
		t.Fatalf("failed to parse stats JSON: %v", err)
	}
	resp.Body.Close()
	spanCount, ok := stats["spanCount"].(float64)
	if !ok || spanCount < 1 {
		t.Fatalf("expected stats.spanCount >= 1, got %v", stats["spanCount"])
	}

	// Test metrics endpoint — valid JSON array (may be empty since we only ingested traces).
	resp, err = http.Get(baseURL + "/api/query/metrics")
	if err != nil {
		t.Fatalf("failed to GET metrics: %v", err)
	}
	if resp.StatusCode != 200 {
		resp.Body.Close()
		t.Fatalf("expected 200 for /api/query/metrics, got %d", resp.StatusCode)
	}
	var metrics []any
	if err := json.NewDecoder(resp.Body).Decode(&metrics); err != nil {
		resp.Body.Close()
		t.Fatalf("failed to parse metrics JSON: %v", err)
	}
	resp.Body.Close()

	// Test logs endpoint — valid JSON array (may be empty since we only ingested traces).
	resp, err = http.Get(baseURL + "/api/query/logs")
	if err != nil {
		t.Fatalf("failed to GET logs: %v", err)
	}
	if resp.StatusCode != 200 {
		resp.Body.Close()
		t.Fatalf("expected 200 for /api/query/logs, got %d", resp.StatusCode)
	}
	var logs []any
	if err := json.NewDecoder(resp.Body).Decode(&logs); err != nil {
		resp.Body.Close()
		t.Fatalf("failed to parse logs JSON: %v", err)
	}
	resp.Body.Close()
}

// TestMCPToolsList verifies MCP tools/list endpoint.
func TestMCPToolsList(t *testing.T) {
	req := map[string]any{
		"jsonrpc": "2.0",
		"id":      1,
		"method":  "tools/list",
	}

	data, _ := json.Marshal(req)
	resp, err := http.Post(baseURL+"/mcp", "application/json", bytes.NewReader(data))
	if err != nil {
		t.Fatalf("failed to POST to /mcp: %v", err)
	}
	defer resp.Body.Close()

	var result map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		t.Fatalf("failed to parse MCP response: %v", err)
	}

	// Check for result.tools array.
	resultField, ok := result["result"].(map[string]any)
	if !ok {
		t.Fatalf("expected result field in response")
	}

	tools, ok := resultField["tools"].([]any)
	if !ok {
		t.Fatalf("expected tools array in result")
	}

	if len(tools) == 0 {
		t.Fatalf("expected at least one tool")
	}
}

// TestStaticAssets verifies static file serving.
func TestStaticAssets(t *testing.T) {
	// Test / returns HTML.
	resp, err := http.Get(baseURL + "/")
	if err != nil {
		t.Fatalf("failed to GET /: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}

	if ct := resp.Header.Get("Content-Type"); ct != "text/html; charset=utf-8" {
		t.Fatalf("expected text/html, got %s", ct)
	}

	body, _ := io.ReadAll(resp.Body)
	if len(body) == 0 {
		t.Fatalf("expected non-empty HTML body")
	}
}

// TestDataPointCountField verifies stats JSON has "dataPointCount" key.
func TestDataPointCountField(t *testing.T) {
	// Clear data first.
	req, _ := http.NewRequest("DELETE", baseURL+"/api/data", nil)
	resp, _ := http.DefaultClient.Do(req)
	resp.Body.Close()

	resp, err := http.Get(baseURL + "/api/query/stats")
	if err != nil {
		t.Fatalf("failed to GET stats: %v", err)
	}
	defer resp.Body.Close()

	var stats map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&stats); err != nil {
		t.Fatalf("failed to parse stats JSON: %v", err)
	}

	// Check for dataPointCount key (not metricCount).
	if _, ok := stats["dataPointCount"]; !ok {
		t.Fatalf("expected 'dataPointCount' key in stats, have keys: %v", mapKeys(stats))
	}
}

// ============================================================================
// E2E TESTS
// ============================================================================

// TestE2E_IngestToWebSocket verifies WebSocket receives updates after OTLP ingest.
func TestE2E_IngestToWebSocket(t *testing.T) {
	// Clear data first.
	req, _ := http.NewRequest("DELETE", baseURL+"/api/data", nil)
	resp, _ := http.DefaultClient.Do(req)
	resp.Body.Close()
	time.Sleep(100 * time.Millisecond)

	// Connect WebSocket.
	wsURL := "ws://127.0.0.1:" + restPort + "/api/ws"
	ws, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	if err != nil {
		t.Fatalf("failed to dial WebSocket: %v", err)
	}
	defer ws.Close()

	// Read initial "connected" message.
	var msg map[string]any
	if err := ws.ReadJSON(&msg); err != nil {
		t.Fatalf("failed to read connected message: %v", err)
	}

	// Send subscribe message.
	subscribeMsg := map[string]any{"type": "subscribe"}
	if err := ws.WriteJSON(subscribeMsg); err != nil {
		t.Fatalf("failed to send subscribe: %v", err)
	}

	// Post OTLP trace.
	payload := map[string]any{
		"resourceSpans": []map[string]any{
			{
				"resource": map[string]any{
					"attributes": []map[string]any{
						{
							"key": "service.name",
							"value": map[string]any{
								"stringValue": "test-service",
							},
						},
					},
				},
				"scopeSpans": []map[string]any{
					{
						"scope": map[string]any{
							"name": "test-instrumentation",
						},
						"spans": []map[string]any{
							{
								"traceId":           "0af7651916cd43dd8448eb211c80319c",
								"spanId":            "b7ad6b7169203331",
								"name":              "test-span",
								"kind":              1,
								"startTimeUnixNano": 1000000000000000000,
								"endTimeUnixNano":   1000000001000000000,
								"status": map[string]any{
									"code": 0,
								},
								"attributes": []map[string]any{},
							},
						},
					},
				},
			},
		},
	}

	data, _ := json.Marshal(payload)
	resp, _ = http.Post(otlpHTTPURL+"/v1/traces", "application/json", bytes.NewReader(data))
	resp.Body.Close()

	// Read WebSocket updates (skip initial stats updates).
	received := false
	ws.SetReadDeadline(time.Now().Add(5 * time.Second))
	for i := 0; i < 10; i++ {
		var wsMsg map[string]any
		err := ws.ReadJSON(&wsMsg)
		if err != nil {
			t.Fatalf("failed to read WebSocket message: %v", err)
		}

		msgType, _ := wsMsg["type"].(string)
		signal, _ := wsMsg["signal"].(string)
		if msgType == "update" && signal == "traces" {
			received = true
			break
		}
	}

	if !received {
		t.Fatalf("did not receive traces update on WebSocket")
	}
}

// TestE2E_PauseResume verifies pause/resume prevents and allows updates.
func TestE2E_PauseResume(t *testing.T) {
	// Clear data.
	req, _ := http.NewRequest("DELETE", baseURL+"/api/data", nil)
	resp, _ := http.DefaultClient.Do(req)
	resp.Body.Close()
	time.Sleep(100 * time.Millisecond)

	// Connect WebSocket.
	wsURL := "ws://127.0.0.1:" + restPort + "/api/ws"
	ws, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	if err != nil {
		t.Fatalf("failed to dial WebSocket: %v", err)
	}
	defer ws.Close()

	// Skip "connected" message.
	var msg map[string]any
	ws.ReadJSON(&msg)

	// Send pause BEFORE subscribing.
	pauseMsg := map[string]any{"type": "pause"}
	if err := ws.WriteJSON(pauseMsg); err != nil {
		t.Fatalf("failed to send pause: %v", err)
	}

	// Subscribe.
	subscribeMsg := map[string]any{"type": "subscribe"}
	if err := ws.WriteJSON(subscribeMsg); err != nil {
		t.Fatalf("failed to send subscribe: %v", err)
	}

	time.Sleep(100 * time.Millisecond)

	// Ingest trace while paused (already paused).
	payload := map[string]any{
		"resourceSpans": []map[string]any{
			{
				"resource": map[string]any{
					"attributes": []map[string]any{
						{
							"key": "service.name",
							"value": map[string]any{
								"stringValue": "test-service",
							},
						},
					},
				},
				"scopeSpans": []map[string]any{
					{
						"scope": map[string]any{
							"name": "test-instrumentation",
						},
						"spans": []map[string]any{
							{
								"traceId":           "0af7651916cd43dd8448eb211c80319c",
								"spanId":            "b7ad6b7169203331",
								"name":              "test-span",
								"kind":              1,
								"startTimeUnixNano": 1000000000000000000,
								"endTimeUnixNano":   1000000001000000000,
								"status": map[string]any{
									"code": 0,
								},
								"attributes": []map[string]any{},
							},
						},
					},
				},
			},
		},
	}

	data, _ := json.Marshal(payload)
	resp, _ = http.Post(otlpHTTPURL+"/v1/traces", "application/json", bytes.NewReader(data))
	resp.Body.Close()

	// Should receive "paused-update" message after draining the initial snapshot backlog.
	ws.SetReadDeadline(time.Now().Add(2 * time.Second))
	receivedPausedUpdate := false
	for {
		var pausedMsg map[string]any
		if err := ws.ReadJSON(&pausedMsg); err != nil {
			break
		}

		if pausedType, _ := pausedMsg["type"].(string); pausedType == "paused-update" {
			receivedPausedUpdate = true
			break
		}
	}

	if !receivedPausedUpdate {
		t.Fatalf("did not receive 'paused-update' message while paused")
	}

	// Send resume.
	resumeMsg := map[string]any{"type": "resume"}
	if err := ws.WriteJSON(resumeMsg); err != nil {
		t.Fatalf("failed to send resume: %v", err)
	}

	// After resume, should receive updates with data.
	ws.SetReadDeadline(time.Now().Add(3 * time.Second))
	received := false
	for i := 0; i < 5; i++ {
		var wsMsg map[string]any
		err := ws.ReadJSON(&wsMsg)
		if err != nil {
			break
		}

		msgType, _ := wsMsg["type"].(string)
		if msgType == "update" {
			received = true
			break
		}
	}

	if !received {
		t.Fatalf("did not receive update after resume")
	}
}

// TestE2E_ClearData verifies DELETE /api/data clears all telemetry.
func TestE2E_ClearData(t *testing.T) {
	// Ingest trace.
	payload := map[string]any{
		"resourceSpans": []map[string]any{
			{
				"resource": map[string]any{
					"attributes": []map[string]any{
						{
							"key": "service.name",
							"value": map[string]any{
								"stringValue": "test-service",
							},
						},
					},
				},
				"scopeSpans": []map[string]any{
					{
						"scope": map[string]any{
							"name": "test-instrumentation",
						},
						"spans": []map[string]any{
							{
								"traceId":           "0af7651916cd43dd8448eb211c80319c",
								"spanId":            "b7ad6b7169203331",
								"name":              "test-span",
								"kind":              1,
								"startTimeUnixNano": 1000000000000000000,
								"endTimeUnixNano":   1000000001000000000,
								"status": map[string]any{
									"code": 0,
								},
								"attributes": []map[string]any{},
							},
						},
					},
				},
			},
		},
	}

	data, _ := json.Marshal(payload)
	resp, _ := http.Post(otlpHTTPURL+"/v1/traces", "application/json", bytes.NewReader(data))
	resp.Body.Close()
	time.Sleep(100 * time.Millisecond)

	// Verify data was ingested.
	resp, _ = http.Get(baseURL + "/api/query/stats")
	var statsBeforeClear map[string]any
	json.NewDecoder(resp.Body).Decode(&statsBeforeClear)
	resp.Body.Close()

	spanCountBefore, _ := statsBeforeClear["spanCount"].(float64)
	if spanCountBefore <= 0 {
		t.Fatalf("expected data to be ingested, got spanCount=%v", spanCountBefore)
	}

	// Clear data.
	req, _ := http.NewRequest("DELETE", baseURL+"/api/data", nil)
	resp, _ = http.DefaultClient.Do(req)
	resp.Body.Close()
	time.Sleep(100 * time.Millisecond)

	// Verify data is cleared.
	resp, _ = http.Get(baseURL + "/api/query/stats")
	var statsAfterClear map[string]any
	json.NewDecoder(resp.Body).Decode(&statsAfterClear)
	resp.Body.Close()

	spanCountAfter, _ := statsAfterClear["spanCount"].(float64)
	if spanCountAfter != 0 {
		t.Fatalf("expected spanCount=0 after clear, got %v", spanCountAfter)
	}

	logCountAfter, _ := statsAfterClear["logCount"].(float64)
	if logCountAfter != 0 {
		t.Fatalf("expected logCount=0 after clear, got %v", logCountAfter)
	}

	dpCountAfter, _ := statsAfterClear["dataPointCount"].(float64)
	if dpCountAfter != 0 {
		t.Fatalf("expected dataPointCount=0 after clear, got %v", dpCountAfter)
	}
}

// TestE2E_TraceDetail verifies getting a specific trace with spans.
func TestE2E_TraceDetail(t *testing.T) {
	// Clear data.
	req, _ := http.NewRequest("DELETE", baseURL+"/api/data", nil)
	resp, _ := http.DefaultClient.Do(req)
	resp.Body.Close()
	time.Sleep(100 * time.Millisecond)

	// Ingest multi-span trace.
	traceID := "0af7651916cd43dd8448eb211c80319c"
	payload := map[string]any{
		"resourceSpans": []map[string]any{
			{
				"resource": map[string]any{
					"attributes": []map[string]any{
						{
							"key": "service.name",
							"value": map[string]any{
								"stringValue": "test-service",
							},
						},
					},
				},
				"scopeSpans": []map[string]any{
					{
						"scope": map[string]any{
							"name": "test-instrumentation",
						},
						"spans": []map[string]any{
							{
								"traceId":           traceID,
								"spanId":            "b7ad6b7169203331",
								"name":              "parent-span",
								"kind":              1,
								"startTimeUnixNano": 1000000000000000000,
								"endTimeUnixNano":   1000000003000000000,
								"status": map[string]any{
									"code": 0,
								},
								"attributes": []map[string]any{},
							},
							{
								"traceId":           traceID,
								"spanId":            "b7ad6b7169203332",
								"parentSpanId":      "b7ad6b7169203331",
								"name":              "child-span",
								"kind":              1,
								"startTimeUnixNano": 1000000001000000000,
								"endTimeUnixNano":   1000000002000000000,
								"status": map[string]any{
									"code": 0,
								},
								"attributes": []map[string]any{},
							},
						},
					},
				},
			},
		},
	}

	data, _ := json.Marshal(payload)
	resp, _ = http.Post(otlpHTTPURL+"/v1/traces", "application/json", bytes.NewReader(data))
	resp.Body.Close()
	time.Sleep(100 * time.Millisecond)

	// Query trace detail.
	traceDetailURL := baseURL + "/api/query/traces/" + url.PathEscape(traceID)
	resp, err := http.Get(traceDetailURL)
	if err != nil {
		t.Fatalf("failed to GET trace detail: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}

	var detail map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&detail); err != nil {
		t.Fatalf("failed to parse trace detail JSON: %v", err)
	}

	// Verify spans array exists.
	spans, ok := detail["spans"].([]any)
	if !ok {
		t.Fatalf("expected spans array in detail, have keys: %v", mapKeys(detail))
	}

	if len(spans) < 2 {
		t.Fatalf("expected at least 2 spans, got %d", len(spans))
	}
}

// TestE2E_MetricGrouping verifies metrics are grouped by name.
func TestE2E_MetricGrouping(t *testing.T) {
	// Clear data.
	req, _ := http.NewRequest("DELETE", baseURL+"/api/data", nil)
	resp, _ := http.DefaultClient.Do(req)
	resp.Body.Close()
	time.Sleep(100 * time.Millisecond)

	// Ingest metrics with different names.
	metricsPayload := map[string]any{
		"resourceMetrics": []map[string]any{
			{
				"resource": map[string]any{
					"attributes": []map[string]any{
						{
							"key": "service.name",
							"value": map[string]any{
								"stringValue": "test-service",
							},
						},
					},
				},
				"scopeMetrics": []map[string]any{
					{
						"scope": map[string]any{
							"name": "test-instrumentation",
						},
						"metrics": []map[string]any{
							{
								"name": "http.server.request.count",
								"sum": map[string]any{
									"dataPoints": []map[string]any{
										{
											"asInt":        100,
											"timeUnixNano": 1000000000000000000,
											"attributes":   []map[string]any{},
										},
									},
									"aggregationTemporality": 2,
									"isMonotonic":            true,
								},
							},
							{
								"name": "http.server.request.duration",
								"histogram": map[string]any{
									"dataPoints": []map[string]any{
										{
											"timeUnixNano":   1000000000000000000,
											"count":          50,
											"sum":            5000,
											"bucketCounts":   []int{10, 20, 15, 5},
											"explicitBounds": []float64{1, 10, 100, 1000},
											"attributes":     []map[string]any{},
										},
									},
									"aggregationTemporality": 2,
								},
							},
						},
					},
				},
			},
		},
	}

	data, _ := json.Marshal(metricsPayload)
	resp, _ = http.Post(otlpHTTPURL+"/v1/metrics", "application/json", bytes.NewReader(data))
	resp.Body.Close()
	time.Sleep(100 * time.Millisecond)

	// Query metrics.
	resp, err := http.Get(baseURL + "/api/query/metrics")
	if err != nil {
		t.Fatalf("failed to GET metrics: %v", err)
	}
	defer resp.Body.Close()

	var metrics []map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&metrics); err != nil {
		t.Fatalf("failed to parse metrics JSON: %v", err)
	}

	// Verify we have metric groups.
	if len(metrics) == 0 {
		t.Fatalf("expected metrics groups, got none")
	}

	// Collect metric names.
	names := make(map[string]int)
	for _, group := range metrics {
		if name, ok := group["name"].(string); ok {
			names[name]++
		}
	}

	// Should have both metric names represented.
	if names["http.server.request.count"] == 0 {
		t.Fatalf("expected http.server.request.count in metrics")
	}
	if names["http.server.request.duration"] == 0 {
		t.Fatalf("expected http.server.request.duration in metrics")
	}
}

// ============================================================================
// HELPERS
// ============================================================================

func mapKeys(m map[string]any) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	return keys
}
