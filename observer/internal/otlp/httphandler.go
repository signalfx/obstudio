package otlp

import (
	"compress/gzip"
	"fmt"
	"io"
	"log"
	"net/http"

	"github.com/signalfx/obstudio/observer/internal/store"
	"go.opentelemetry.io/collector/pdata/plog"
	"go.opentelemetry.io/collector/pdata/pmetric"
	"go.opentelemetry.io/collector/pdata/ptrace"
)

// otlpHTTPHandler handles OTLP/HTTP requests directly (without proxying),
// so we can associate incoming data with the connection ID resolved by
// the ConnTracker.
type otlpHTTPHandler struct {
	store *store.Store
	ct    *ConnTracker
}

func (h *otlpHTTPHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	connID := h.ct.resolveHTTPConnectionFromRequest(r)

	body, err := readBody(r)
	if err != nil {
		http.Error(w, fmt.Sprintf("read body: %v", err), http.StatusBadRequest)
		return
	}

	ct := r.Header.Get("Content-Type")
	isProto := ct == "application/x-protobuf"

	switch r.URL.Path {
	case "/v1/traces":
		h.handleTraces(w, body, isProto, connID)
	case "/v1/metrics":
		h.handleMetrics(w, body, isProto, connID)
	case "/v1/logs":
		h.handleLogs(w, body, isProto, connID)
	default:
		http.Error(w, "not found", http.StatusNotFound)
	}
}

func (h *otlpHTTPHandler) handleTraces(w http.ResponseWriter, body []byte, isProto bool, connID string) {
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
	h.store.AddSpansForConnection(connID, ConvertTraces(td))
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte("{}"))
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

// readBody reads the request body, handling gzip decompression if needed.
func readBody(r *http.Request) ([]byte, error) {
	var reader io.Reader = r.Body
	if r.Header.Get("Content-Encoding") == "gzip" {
		gz, err := gzip.NewReader(r.Body)
		if err != nil {
			return nil, fmt.Errorf("gzip reader: %w", err)
		}
		defer gz.Close()
		reader = gz
	}
	return io.ReadAll(reader)
}
