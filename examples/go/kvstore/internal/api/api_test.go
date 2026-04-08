package api

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"kvstore/internal/store"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/codes"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/metric/metricdata"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/sdk/trace/tracetest"
)

func TestAPISetGetListDelete(t *testing.T) {
	restore := installTestTelemetry()
	defer restore()

	h := New(store.New())

	status, body := doJSON(t, h, http.MethodPost, "/set", map[string]string{"key": "app:a", "value": "1"})
	if status != http.StatusOK {
		t.Fatalf("/set status = %d, want %d; body=%s", status, http.StatusOK, body)
	}

	status, body = doJSON(t, h, http.MethodPost, "/set", map[string]string{"key": "app:b", "value": "2"})
	if status != http.StatusOK {
		t.Fatalf("/set status = %d, want %d; body=%s", status, http.StatusOK, body)
	}

	status, body = doJSON(t, h, http.MethodPost, "/get", map[string]string{"key": "app:a"})
	if status != http.StatusOK {
		t.Fatalf("/get status = %d, want %d; body=%s", status, http.StatusOK, body)
	}
	var getResp map[string]string
	if err := json.Unmarshal([]byte(body), &getResp); err != nil {
		t.Fatalf("unmarshal /get response: %v", err)
	}
	if getResp["value"] != "1" {
		t.Fatalf("/get value = %q, want %q", getResp["value"], "1")
	}

	status, body = doJSON(t, h, http.MethodPost, "/list", map[string]string{"prefix": "app:"})
	if status != http.StatusOK {
		t.Fatalf("/list status = %d, want %d; body=%s", status, http.StatusOK, body)
	}
	var listResp struct {
		Keys []string `json:"keys"`
	}
	if err := json.Unmarshal([]byte(body), &listResp); err != nil {
		t.Fatalf("unmarshal /list response: %v", err)
	}
	if len(listResp.Keys) != 2 {
		t.Fatalf("/list keys len = %d, want 2", len(listResp.Keys))
	}

	status, body = doJSON(t, h, http.MethodPost, "/delete", map[string]string{"key": "app:a"})
	if status != http.StatusOK {
		t.Fatalf("/delete status = %d, want %d; body=%s", status, http.StatusOK, body)
	}

	status, _ = doJSON(t, h, http.MethodPost, "/get", map[string]string{"key": "app:a"})
	if status != http.StatusNotFound {
		t.Fatalf("/get after delete status = %d, want %d", status, http.StatusNotFound)
	}
}

func TestAPIKeyTooLarge(t *testing.T) {
	restore := installTestTelemetry()
	defer restore()

	h := New(store.New())
	largeKey := strings.Repeat("k", store.MaxKeySize+1)

	status, _ := doJSON(t, h, http.MethodPost, "/set", map[string]string{"key": largeKey, "value": "v"})
	if status != http.StatusBadRequest {
		t.Fatalf("/set status = %d, want %d", status, http.StatusBadRequest)
	}
}

func TestAPIValueTooLarge(t *testing.T) {
	restore := installTestTelemetry()
	defer restore()

	h := New(store.New())
	largeValue := strings.Repeat("v", store.MaxValueSize+1)

	status, _ := doJSON(t, h, http.MethodPost, "/set", map[string]string{"key": "k", "value": largeValue})
	if status != http.StatusBadRequest {
		t.Fatalf("/set status = %d, want %d", status, http.StatusBadRequest)
	}
}

func TestAPIMethodNotAllowed(t *testing.T) {
	restore := installTestTelemetry()
	defer restore()

	h := New(store.New())
	req := httptest.NewRequest(http.MethodGet, "/set", nil)
	rr := httptest.NewRecorder()

	h.ServeHTTP(rr, req)

	if rr.Code != http.StatusMethodNotAllowed {
		t.Fatalf("status = %d, want %d", rr.Code, http.StatusMethodNotAllowed)
	}
}

func TestAPIValidationTelemetry(t *testing.T) {
	reader, recorder, restore := installTestTelemetryWithState()
	defer restore()

	h := New(store.New())

	req := httptest.NewRequest(http.MethodPost, "/set", bytes.NewBufferString(`{"key":`))
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()
	h.ServeHTTP(rr, req)

	largeKey := strings.Repeat("k", store.MaxKeySize+1)
	doJSON(t, h, http.MethodPost, "/set", map[string]string{"key": largeKey, "value": "v"})
	req = httptest.NewRequest(http.MethodGet, "/set", nil)
	rr = httptest.NewRecorder()
	h.ServeHTTP(rr, req)

	metrics := collectMetrics(t, reader)
	if got := sumMetric(metrics, "kvstore.validation.failure.count"); got < 3 {
		t.Fatalf("validation failure count = %d, want at least 3", got)
	}

	if countSpanStatus(recorder.Ended(), codes.Error) == 0 {
		t.Fatal("expected at least one error span")
	}
}

func doJSON(t *testing.T, h http.Handler, method, path string, payload any) (int, string) {
	t.Helper()

	b, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("marshal request: %v", err)
	}

	req := httptest.NewRequest(method, path, bytes.NewReader(b))
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()

	h.ServeHTTP(rr, req)

	return rr.Code, rr.Body.String()
}

func installTestTelemetry() func() {
	_, _, restore := installTestTelemetryWithState()
	return restore
}

func installTestTelemetryWithState() (*sdkmetric.ManualReader, *tracetest.SpanRecorder, func()) {
	tpPrev := otel.GetTracerProvider()
	mpPrev := otel.GetMeterProvider()

	recorder := tracetest.NewSpanRecorder()
	tp := sdktrace.NewTracerProvider()
	tp.RegisterSpanProcessor(recorder)

	reader := sdkmetric.NewManualReader()
	mp := sdkmetric.NewMeterProvider(sdkmetric.WithReader(reader))

	otel.SetTracerProvider(tp)
	otel.SetMeterProvider(mp)

	return reader, recorder, func() {
		_ = tp.Shutdown(context.Background())
		_ = mp.Shutdown(context.Background())
		otel.SetTracerProvider(tpPrev)
		otel.SetMeterProvider(mpPrev)
	}
}

func collectMetrics(t *testing.T, reader *sdkmetric.ManualReader) metricdata.ResourceMetrics {
	t.Helper()

	var rm metricdata.ResourceMetrics
	if err := reader.Collect(context.Background(), &rm); err != nil {
		t.Fatalf("collect metrics: %v", err)
	}
	return rm
}

func sumMetric(rm metricdata.ResourceMetrics, name string) int64 {
	var total int64
	for _, sm := range rm.ScopeMetrics {
		for _, metric := range sm.Metrics {
			if metric.Name != name {
				continue
			}
			switch data := metric.Data.(type) {
			case metricdata.Sum[int64]:
				for _, dp := range data.DataPoints {
					total += dp.Value
				}
			}
		}
	}
	return total
}

func countSpanStatus(spans []sdktrace.ReadOnlySpan, code codes.Code) int {
	count := 0
	for _, span := range spans {
		if span.Status().Code == code {
			count++
		}
	}
	return count
}
