package otlp

import (
	"compress/gzip"
	"context"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"net/url"
	"strings"

	"github.com/signalfx/obstudio/observer/internal/store"
	"go.opentelemetry.io/collector/pdata/plog"
	"go.opentelemetry.io/collector/pdata/pmetric"
	"go.opentelemetry.io/collector/pdata/ptrace"
	"go.opentelemetry.io/collector/pdata/ptrace/ptraceotlp"
)

const maxOTLPHTTPBodyBytes = 16 << 20

// otlpHTTPHandler handles OTLP/HTTP requests directly (without proxying),
// so we can associate incoming data with the connection ID resolved by
// the ConnTracker.
type otlpHTTPHandler struct {
	store          *store.Store
	ct             *ConnTracker
	exporter       MetricsExporter
	tracesExporter TracesExporter
}

func (h *otlpHTTPHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var route AgentTraceRoute
	if r.URL.Path == "/v1/traces" || r.URL.Path == "/v2/trace/otlp" || r.URL.Path == "/otel/v1/traces" {
		var err error
		route, err = agentTraceRoute(r.Header.Values("projectid"), r.Header.Values("logstreamid"))
		if err != nil || (r.URL.Path == "/otel/v1/traces" && route.ProjectID == "") {
			http.Error(w, "valid projectid and logstreamid headers are required together", http.StatusBadRequest)
			return
		}
		if route.ProjectID != "" && !localAgentIngestRequest(r) {
			http.Error(w, "agent trace forwarding requires a native loopback request", http.StatusForbidden)
			return
		}
	}

	connID := ""
	if h.ct != nil {
		connID = h.ct.resolveHTTPConnectionFromRequest(r)
	}

	body, err := readBody(r, route.ProjectID != "")
	if err != nil {
		http.Error(w, fmt.Sprintf("read body: %v", err), http.StatusBadRequest)
		return
	}

	ct := r.Header.Get("Content-Type")
	isProto := ct == "application/x-protobuf"

	switch r.URL.Path {
	case "/v1/traces", "/v2/trace/otlp", "/otel/v1/traces":
		h.handleTraces(r.Context(), w, body, isProto, connID, route)
	case "/v1/metrics":
		h.handleMetrics(w, body, isProto, connID)
	case "/v1/logs":
		h.handleLogs(w, body, isProto, connID)
	default:
		http.Error(w, "not found", http.StatusNotFound)
	}
}

func (h *otlpHTTPHandler) handleTraces(ctx context.Context, w http.ResponseWriter, body []byte, isProto bool, connID string, route AgentTraceRoute) {
	var td ptrace.Traces
	var err error
	if isProto {
		td, err = (&ptrace.ProtoUnmarshaler{}).UnmarshalTraces(body)
	} else {
		td, err = (&ptrace.JSONUnmarshaler{}).UnmarshalTraces(body)
	}
	if err != nil {
		log.Printf("[otlp-http] failed to unmarshal traces: %v", err)
		http.Error(w, fmt.Sprintf("unmarshal: %v", err), http.StatusBadRequest)
		return
	}
	if route.ProjectID != "" {
		h.store.AddAgentSpansForConnection(connID, ConvertTraces(td))
		exporter, ok := h.tracesExporter.(AgentTracesExporter)
		if !ok {
			http.Error(w, "agent trace forwarding is unavailable or failed", http.StatusServiceUnavailable)
			return
		}
		response, err := exporter.ExportAgentTraces(ctx, td, route)
		if err != nil {
			http.Error(w, "agent trace forwarding is unavailable or failed", http.StatusServiceUnavailable)
			return
		}
		writeAgentTraceResponse(w, response, isProto)
		return
	} else {
		h.store.AddSpansForConnection(connID, ConvertTraces(td))
		exportTracesAsync(h.tracesExporter, td)
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte("{}"))
}

func writeAgentTraceResponse(w http.ResponseWriter, response ptraceotlp.ExportResponse, isProto bool) {
	var body []byte
	var err error
	contentType := "application/json"
	if isProto {
		body, err = response.MarshalProto()
		contentType = "application/x-protobuf"
	} else {
		body, err = response.MarshalJSON()
	}
	if err != nil {
		http.Error(w, "could not encode agent trace response", http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", contentType)
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(body)
}

func (h *otlpHTTPHandler) handleMetrics(w http.ResponseWriter, body []byte, isProto bool, connID string) {
	var md pmetric.Metrics
	var err error
	if isProto {
		md, err = (&pmetric.ProtoUnmarshaler{}).UnmarshalMetrics(body)
	} else {
		md, err = (&pmetric.JSONUnmarshaler{}).UnmarshalMetrics(body)
	}
	if err != nil {
		log.Printf("[otlp-http] failed to unmarshal metrics: %v", err)
		http.Error(w, fmt.Sprintf("unmarshal: %v", err), http.StatusBadRequest)
		return
	}
	h.store.AddMetricsForConnection(connID, ConvertMetrics(md))
	exportMetricsAsync(h.exporter, md)
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte("{}"))
}

func (h *otlpHTTPHandler) handleLogs(w http.ResponseWriter, body []byte, isProto bool, connID string) {
	var ld plog.Logs
	var err error
	if isProto {
		ld, err = (&plog.ProtoUnmarshaler{}).UnmarshalLogs(body)
	} else {
		ld, err = (&plog.JSONUnmarshaler{}).UnmarshalLogs(body)
	}
	if err != nil {
		log.Printf("[otlp-http] failed to unmarshal logs: %v", err)
		http.Error(w, fmt.Sprintf("unmarshal: %v", err), http.StatusBadRequest)
		return
	}
	h.store.AddLogsForConnection(connID, ConvertLogs(ld))
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte("{}"))
}

// readBody preserves the existing ordinary OTLP limit behavior while bounding
// decompressed payloads sent through the Agent Observability cloud gateway.
func readBody(r *http.Request, agentRouted bool) ([]byte, error) {
	var reader io.Reader = r.Body
	if r.Header.Get("Content-Encoding") == "gzip" {
		gz, err := gzip.NewReader(r.Body)
		if err != nil {
			return nil, fmt.Errorf("gzip reader: %w", err)
		}
		defer gz.Close()
		reader = gz
	}
	if !agentRouted {
		return io.ReadAll(reader)
	}
	body, err := io.ReadAll(io.LimitReader(reader, maxOTLPHTTPBodyBytes+1))
	if err != nil {
		return nil, err
	}
	if len(body) > maxOTLPHTTPBodyBytes {
		return nil, fmt.Errorf("body exceeds %d bytes", maxOTLPHTTPBodyBytes)
	}
	return body, nil
}

func localAgentIngestRequest(r *http.Request) bool {
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return false
	}
	ip := net.ParseIP(host)
	hostURL, err := url.Parse("//" + r.Host)
	if err != nil || hostURL.User != nil || hostURL.Path != "" || hostURL.RawQuery != "" || hostURL.Fragment != "" {
		return false
	}
	requestHost := strings.TrimSuffix(hostURL.Hostname(), ".")
	hostIP := net.ParseIP(requestHost)
	localHost := strings.EqualFold(requestHost, "localhost") || (hostIP != nil && hostIP.IsLoopback())
	for name := range r.Header {
		if strings.EqualFold(name, "Origin") || strings.HasPrefix(strings.ToLower(name), "sec-fetch-") {
			return false
		}
	}
	return ip != nil && ip.IsLoopback() && localHost
}
