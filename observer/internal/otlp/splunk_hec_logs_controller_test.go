package otlp

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func waitForHECDelivery(t *testing.T, check func() bool) {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if check() {
			return
		}
		time.Sleep(time.Millisecond)
	}
	t.Fatal("native HEC delivery did not settle")
}

func TestHECNativeQueueCountsAcceptedResponses(t *testing.T) {
	entered, release := make(chan struct{}), make(chan struct{})
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		close(entered)
		select {
		case <-release:
			_, _ = w.Write([]byte(`{"code":0}`))
		case <-r.Context().Done():
		}
	}))
	defer remote.Close()
	c := NewSplunkHECLogsExportController(SplunkHECLogsExporterConfig{Endpoint: remote.URL, Token: "test", Index: "studio", Enabled: true})
	defer c.Shutdown(context.Background())
	if err := c.ExportLogs(context.Background(), logsWithRecord(nil, nil, "accepted after response")); err != nil {
		t.Fatal(err)
	}
	select {
	case <-entered:
	case <-time.After(3 * time.Second):
		t.Fatal("native queue did not send")
	}
	if got := c.Status(); got.ExportedRecords != 0 || got.ExportedBatches != 0 {
		t.Fatal("enqueue counted as export", got)
	}
	close(release)
	waitForHECDelivery(t, func() bool { return c.Status().ExportedRecords == 1 })
	if got := c.Status(); got.ExportedBatches != 1 || got.FailedBatches != 0 {
		t.Fatal(got)
	}
}

func TestHECNativeQueueRetriesTransientFailures(t *testing.T) {
	for _, status := range []int{503, 200} {
		t.Run(http.StatusText(status), func(t *testing.T) {
			var requests atomic.Int32
			remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				_, _ = io.Copy(io.Discard, r.Body)
				if requests.Add(1) == 1 {
					w.Header().Set("Retry-After", "1")
					w.WriteHeader(status)
					_, _ = w.Write([]byte(`{"code":9,"invalid-event-number":0}`))
					return
				}
				_, _ = w.Write([]byte(`{"code":0}`))
			}))
			defer remote.Close()
			c := NewSplunkHECLogsExportController(SplunkHECLogsExporterConfig{Endpoint: remote.URL, Token: "test", Enabled: true})
			defer c.Shutdown(context.Background())
			c.QueueLogs(logsWithRecord(nil, nil, "native retry"))
			deadline := time.Now().Add(12 * time.Second)
			for c.Status().ExportedRecords != 1 && time.Now().Before(deadline) {
				time.Sleep(time.Millisecond)
			}
			if got := c.Status(); got.ExportedRecords != 1 || got.ExportedBatches != 1 || got.FailedBatches != 1 || requests.Load() != 2 {
				t.Fatal("native retry", got, requests.Load())
			}
		})
	}
}

func TestHECDestinationLifecycleStopsPreviousNativeQueue(t *testing.T) {
	var acceptFirst atomic.Bool
	var mu sync.Mutex
	firstReceived, secondReceived := map[string]int{}, map[string]int{}
	sink := func(received map[string]int, reject bool) http.HandlerFunc {
		return func(w http.ResponseWriter, r *http.Request) {
			if reject && !acceptFirst.Load() {
				w.Header().Set("Retry-After", "60")
				w.WriteHeader(503)
				_, _ = w.Write([]byte(`{"code":9}`))
				return
			}
			decoder := json.NewDecoder(hecRequestBody(t, r))
			for {
				var event hecEvent
				if err := decoder.Decode(&event); err == io.EOF {
					break
				} else if err != nil {
					t.Error(err)
					return
				}
				mu.Lock()
				received[event.Event.(string)]++
				mu.Unlock()
			}
			_, _ = w.Write([]byte(`{"code":0}`))
		}
	}
	first, second := httptest.NewServer(sink(firstReceived, true)), httptest.NewServer(sink(secondReceived, false))
	defer first.Close()
	defer second.Close()
	c := NewSplunkHECLogsExportController(SplunkHECLogsExporterConfig{})
	defer c.Shutdown(context.Background())
	for _, body := range []string{"before connection one", "before connection two"} {
		c.QueueLogs(logsWithRecord(nil, nil, body))
	}
	apply := func(endpoint, index string) {
		t.Helper()
		config := SplunkHECLogsExporterConfig{Endpoint: endpoint, Token: "test", Index: index, Enabled: true, ConnectionVerified: true}
		exp, err := NewSplunkHECLogsExporter(config)
		if err != nil {
			t.Fatal(err)
		}
		c.ApplyKeepingActivity(config, exp)
	}
	apply(first.URL, "a")
	c.QueueLogs(logsWithRecord(nil, nil, "old destination"))
	waitForHECDelivery(t, func() bool { return c.Status().LastHTTPStatus == 503 })
	started := time.Now()
	apply(second.URL, "b")
	if time.Since(started) > 2*time.Second {
		t.Fatal("old retry delay blocked destination change")
	}
	c.QueueLogs(logsWithRecord(nil, nil, "new destination"))
	waitForHECDelivery(t, func() bool { return c.Status().ExportedRecords == 1 })
	acceptFirst.Store(true)
	apply(first.URL, "a")
	c.QueueLogs(logsWithRecord(nil, nil, "returned destination"))
	waitForHECDelivery(t, func() bool { return c.Status().ExportedRecords == 2 })
	mu.Lock()
	defer mu.Unlock()
	if len(firstReceived) != 1 || firstReceived["returned destination"] != 1 || len(secondReceived) != 1 || secondReceived["new destination"] != 1 {
		t.Fatal("destination lifecycle leaked backlog", firstReceived, secondReceived)
	}
}

func TestHECPauseStopsInFlightDeliveryAndResumesNewLogs(t *testing.T) {
	entered := make(chan struct{})
	var accepted atomic.Int32
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var event hecEvent
		if err := json.NewDecoder(hecRequestBody(t, r)).Decode(&event); err != nil {
			t.Error(err)
			return
		}
		if event.Event == "in flight" {
			close(entered)
			<-r.Context().Done()
			return
		}
		accepted.Add(1)
		_, _ = w.Write([]byte(`{"code":0}`))
	}))
	defer remote.Close()
	c := NewSplunkHECLogsExportController(SplunkHECLogsExporterConfig{Endpoint: remote.URL, Token: "test", Enabled: true})
	defer c.Shutdown(context.Background())
	c.QueueLogs(logsWithRecord(nil, nil, "in flight"))
	select {
	case <-entered:
	case <-time.After(3 * time.Second):
		t.Fatal("native delivery did not start")
	}
	paused := make(chan error, 1)
	go func() { paused <- c.SetEnabled(false) }()
	select {
	case err := <-paused:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("pause did not cancel in-flight delivery")
	}
	c.QueueLogs(logsWithRecord(nil, nil, "while paused"))
	if err := c.SetEnabled(true); err != nil {
		t.Fatal(err)
	}
	c.QueueLogs(logsWithRecord(nil, nil, "after resume"))
	waitForHECDelivery(t, func() bool { return c.Status().ExportedRecords == 1 })
	if accepted.Load() != 1 || c.Status().FailedBatches != 0 {
		t.Fatal("paused logs were replayed or cancellation reported as failure", accepted.Load(), c.Status())
	}
}

type hecCompletedBody struct {
	io.Reader
	complete func()
}

func (b hecCompletedBody) Read(data []byte) (int, error) {
	n, err := b.Reader.Read(data)
	if err == io.EOF {
		b.complete()
	}
	return n, err
}
func (hecCompletedBody) Close() error { return nil }

func TestHECNativeDeliveryCountsResponseCompletedDuringStop(t *testing.T) {
	exp, err := NewSplunkHECLogsExporter(SplunkHECLogsExporterConfig{Endpoint: "http://127.0.0.1/services/collector", Token: "test", Enabled: true})
	if err != nil {
		t.Fatal(err)
	}
	defer exp.Shutdown(context.Background())
	exp.transport.RegisterProtocol("http", hecRoundTripperFunc(func(req *http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: 200, Header: make(http.Header), Body: hecCompletedBody{Reader: strings.NewReader(`{"code":0}`), complete: exp.stop}}, nil
	}))
	if err := exp.ExportLogs(context.Background(), logsWithRecord(nil, nil, "completed response")); err != nil {
		t.Fatal(err)
	}
	waitForHECDelivery(t, func() bool { return exp.Status().ExportedRecords == 1 })
	if got := exp.Status(); got.ExportedBatches != 1 || got.FailedBatches != 0 {
		t.Fatal("completed acceptance was lost during stop", got)
	}
}
