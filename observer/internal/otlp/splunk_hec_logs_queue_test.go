package otlp

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"go.opentelemetry.io/collector/exporter"
	"go.opentelemetry.io/collector/pdata/pcommon"
	"go.opentelemetry.io/collector/pdata/plog"
)

func TestHECQueueExportsNonFiniteAttributesWithoutLosingNeighborLogs(t *testing.T) {
	received := make(chan []hecEvent, 2)
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		decoder := json.NewDecoder(hecRequestBody(t, r))
		var events []hecEvent
		for {
			var event hecEvent
			if err := decoder.Decode(&event); err == io.EOF {
				break
			} else if err != nil {
				t.Error(err)
				return
			}
			events = append(events, event)
		}
		received <- events
		_, _ = w.Write([]byte(`{"code":0}`))
	}))
	defer remote.Close()
	c := NewSplunkHECLogsExportController(SplunkHECLogsExporterConfig{Endpoint: remote.URL, Token: "test", Enabled: true})
	defer c.Shutdown(context.Background())
	logs := logsWithRecord(nil, nil, "")
	records := logs.ResourceLogs().At(0).ScopeLogs().At(0).LogRecords()
	attrs := records.At(0).Attributes()
	attrs.PutDouble("non-finite", math.NaN())
	attrs.PutDouble("negative", math.Inf(-1))
	attrs.PutDouble("finite", 42)
	attrs.PutEmptyMap("nested").PutEmptySlice("values").AppendEmpty().SetDouble(math.Inf(1))
	records.AppendEmpty().Body().SetStr("valid neighbor")
	c.QueueLogs(logs)
	c.QueueLogs(logsWithRecord(nil, nil, "valid later batch"))
	waitForHECQueue(t, c, func(s SplunkHECLogsExportStatus) bool { return s.QueuedRecords == 0 && s.ExportedRecords == 3 })
	first, second := <-received, <-received
	if len(first) != 2 || first[1].Event != "valid neighbor" || len(second) != 1 || second[0].Event != "valid later batch" {
		t.Fatalf("lost neighboring logs: first=%+v second=%+v", first, second)
	}
	values := first[0].Event.(map[string]any)["attributes"].(map[string]any)
	if values["non-finite"] != "NaN" || values["negative"] != "-Inf" || values["finite"] != float64(42) || fmt.Sprint(values["nested"].(map[string]any)["values"]) != "[+Inf]" {
		t.Fatalf("invalid attribute conversion: %#v", values)
	}
	original, _ := attrs.Get("non-finite")
	if !math.IsNaN(original.Double()) {
		t.Fatal("conversion mutated the caller's attributes")
	}
	if status := c.Status(); status.DroppedRecords != 0 || status.FailedBatches != 0 {
		t.Fatalf("valid OTLP attributes caused data loss: %+v", status)
	}
}

func waitForHECQueue(t *testing.T, c *SplunkHECLogsExportController, check func(SplunkHECLogsExportStatus) bool) {
	t.Helper()
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		if check(c.Status()) {
			return
		}
		time.Sleep(time.Millisecond)
	}
	t.Fatalf("queue did not settle: %+v", c.Status())
}

func TestHECQueueBuffersImmutableLogsUntilEnabledAndDrainsInOrder(t *testing.T) {
	var mu sync.Mutex
	var received []string
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var event struct {
			Event string `json:"event"`
		}
		if err := json.NewDecoder(hecRequestBody(t, r)).Decode(&event); err != nil {
			t.Error(err)
		}
		mu.Lock()
		received = append(received, event.Event)
		mu.Unlock()
		_, _ = w.Write([]byte(`{"code":0}`))
	}))
	defer remote.Close()
	c := NewSplunkHECLogsExportController(SplunkHECLogsExporterConfig{})
	defer c.Shutdown(context.Background())
	logs := logsWithRecord(nil, nil, "before connection")
	exportLogsAsync(c, logs)
	logs.ResourceLogs().At(0).ScopeLogs().At(0).LogRecords().At(0).Body().SetStr("mutated")
	config := SplunkHECLogsExporterConfig{Endpoint: remote.URL, Token: "test-token", Index: "studio", ConnectionVerified: true}
	c.Apply(config, newTestHECExporter(t, remote.URL, config))
	exportLogsAsync(c, logsWithRecord(nil, nil, "paused"))
	if got := c.Status(); got.QueuedRecords != 2 || got.ExportedRecords != 0 {
		t.Fatalf("paused status: %+v", got)
	}
	if err := c.SetEnabled(true); err != nil {
		t.Fatal(err)
	}
	waitForHECQueue(t, c, func(s SplunkHECLogsExportStatus) bool { return s.ExportedRecords == 2 && s.QueuedRecords == 0 })
	mu.Lock()
	defer mu.Unlock()
	if fmt.Sprint(received) != "[before connection paused]" {
		t.Fatalf("received %v", received)
	}
}

func TestHECQueuePreservesObservationTimeAcrossPauseAndRetry(t *testing.T) {
	var reject atomic.Bool
	reject.Store(true)
	received := make(chan []float64, 2)
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		decoder := json.NewDecoder(hecRequestBody(t, r))
		var times []float64
		for {
			var event struct{ Time float64 }
			if err := decoder.Decode(&event); err == io.EOF {
				break
			} else if err != nil {
				t.Error(err)
				return
			}
			times = append(times, event.Time)
		}
		received <- times
		if reject.Load() {
			w.WriteHeader(http.StatusUnauthorized)
			_, _ = w.Write([]byte(`{"code":4}`))
			return
		}
		_, _ = w.Write([]byte(`{"code":0}`))
	}))
	defer remote.Close()
	c := NewSplunkHECLogsExportController(SplunkHECLogsExporterConfig{Endpoint: remote.URL, Token: "test"})
	defer c.Shutdown(context.Background())
	logs := logsWithRecord(nil, nil, "untimed")
	records := logs.ResourceLogs().At(0).ScopeLogs().At(0).LogRecords()
	records.At(0).SetTimestamp(0)
	existing := pcommon.NewTimestampFromTime(time.Unix(1761000000, 0))
	records.AppendEmpty().SetObservedTimestamp(existing)
	records.At(1).Body().SetStr("already observed")
	records.AppendEmpty().SetTimestamp(existing)
	records.At(2).SetObservedTimestamp(pcommon.NewTimestampFromTime(time.Now()))
	records.At(2).Body().SetStr("source timestamp wins")
	before := time.Now()
	c.QueueLogs(logs)
	after := time.Now()
	if records.At(0).ObservedTimestamp() != 0 || records.At(0).Timestamp() != 0 {
		t.Fatal("queueing mutated the caller's logs")
	}
	if err := c.SetEnabled(true); err != nil {
		t.Fatal(err)
	}
	waitForHECQueue(t, c, func(s SplunkHECLogsExportStatus) bool { return s.FailedBatches == 1 })
	if err := c.SetEnabled(false); err != nil {
		t.Fatal(err)
	}
	first := <-received
	observed := time.Unix(0, int64(first[0]*float64(time.Second)))
	if observed.Before(before.Add(-time.Microsecond)) || observed.After(after.Add(time.Microsecond)) {
		t.Fatalf("receipt time outside enqueue: %s", observed)
	}
	reject.Store(false)
	if err := c.SetEnabled(true); err != nil {
		t.Fatal(err)
	}
	waitForHECQueue(t, c, func(s SplunkHECLogsExportStatus) bool { return s.QueuedRecords == 0 && s.ExportedRecords == 3 })
	second := <-received
	want := []float64{first[0], float64(existing.AsTime().Unix()), float64(existing.AsTime().Unix())}
	if fmt.Sprint(first) != fmt.Sprint(want) || fmt.Sprint(second) != fmt.Sprint(want) {
		t.Fatalf("event times changed during buffering/retry: first=%v second=%v want=%v", first, second, want)
	}
}

func TestHECQueueRetainsRejectedBatchAndReplaysAfterTokenUpdate(t *testing.T) {
	var requests atomic.Int32
	var accepted atomic.Int32
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests.Add(1)
		if r.Header.Get("Authorization") != "Splunk replacement" {
			w.WriteHeader(401)
			_, _ = w.Write([]byte(`{"code":4}`))
			return
		}
		accepted.Add(1)
		_, _ = w.Write([]byte(`{"code":0}`))
	}))
	defer remote.Close()
	config := SplunkHECLogsExporterConfig{Endpoint: remote.URL, Token: "rejected", Enabled: true, ConnectionVerified: true}
	c := NewSplunkHECLogsExportController(config)
	defer c.Shutdown(context.Background())
	if err := c.ExportLogs(context.Background(), logsWithRecord(nil, nil, "retained")); err == nil {
		t.Fatal("expected rejection")
	}
	if got := c.Status(); got.QueuedRecords != 1 || got.LastHTTPStatus != 401 || got.ExportedRecords != 0 {
		t.Fatalf("rejected status %+v", got)
	}
	c.QueueLogs(logsWithRecord(nil, nil, "during failure"))
	if requests.Load() != 1 {
		t.Fatal("new batches must respect retry backoff")
	}
	config.Token = "replacement"
	c.ApplyKeepingActivity(config, newTestHECExporter(t, remote.URL, config))
	waitForHECQueue(t, c, func(s SplunkHECLogsExportStatus) bool { return s.ExportedRecords == 2 && s.QueuedRecords == 0 })
	if got := c.Status(); got.FailedBatches != 1 || got.LastExportError != "" || got.LastHTTPStatus != 0 || accepted.Load() != 2 {
		t.Fatalf("recovery status %+v", got)
	}
}

func TestHECQueueDropsPermanentPayloadRejectionsAndContinues(t *testing.T) {
	for _, test := range []struct {
		name   string
		status int
		code   int
	}{
		{"invalid record index", 400, 7},
		{"invalid format", 400, 6},
		{"missing event", 400, 12},
		{"blank event", 200, 13},
		{"oversized payload", 413, 0},
	} {
		t.Run(test.name, func(t *testing.T) {
			var requests atomic.Int32
			remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				var event struct{ Index string }
				if err := json.NewDecoder(hecRequestBody(t, r)).Decode(&event); err != nil {
					t.Error(err)
				}
				requests.Add(1)
				if event.Index == "invalid-record-index" {
					w.WriteHeader(test.status)
					_, _ = fmt.Fprintf(w, `{"code":%d}`, test.code)
					return
				}
				_, _ = w.Write([]byte(`{"code":0}`))
			}))
			defer remote.Close()
			config := SplunkHECLogsExporterConfig{Endpoint: remote.URL, Token: "test", Index: "studio", ConnectionVerified: true}
			c := NewSplunkHECLogsExportController(config)
			defer c.Shutdown(context.Background())
			c.QueueLogs(logsWithRecord(nil, map[string]string{splunkIndexAttribute: "invalid-record-index"}, "invalid"))
			c.QueueLogs(logsWithRecord(nil, nil, "valid afterward"))
			if err := c.SetEnabled(true); err != nil {
				t.Fatal(err)
			}
			waitForHECQueue(t, c, func(s SplunkHECLogsExportStatus) bool { return s.QueuedRecords == 0 && s.ExportedRecords == 1 })
			if s := c.Status(); s.DroppedRecords != 1 || s.FailedBatches != 1 || requests.Load() != 2 {
				t.Fatalf("permanent rejection blocked following batch: %+v", s)
			}
		})
	}
}

func TestHECQueueRetainsRecoverableConfigurationAndTransientErrors(t *testing.T) {
	for _, test := range []struct{ status, code int }{{400, 7}, {401, 4}, {403, 4}, {429, 9}, {503, 9}, {400, 99}} {
		t.Run(fmt.Sprint(test), func(t *testing.T) {
			remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.WriteHeader(test.status)
				_, _ = fmt.Fprintf(w, `{"code":%d}`, test.code)
			}))
			defer remote.Close()
			c := NewSplunkHECLogsExportController(SplunkHECLogsExporterConfig{Endpoint: remote.URL, Token: "test", Index: "studio", Enabled: true})
			defer c.Shutdown(context.Background())
			if err := c.ExportLogs(context.Background(), logsWithRecord(nil, nil, "retained")); err == nil {
				t.Fatal("expected rejection")
			}
			if s := c.Status(); s.QueuedRecords != 1 || s.DroppedRecords != 0 || s.LastHECCode != test.code {
				t.Fatalf("recoverable rejection lost its batch: %+v", s)
			}
		})
	}
}

func TestHECQueueBoundsRecordsBytesAndBatches(t *testing.T) {
	t.Run("batches", func(t *testing.T) {
		c := NewSplunkHECLogsExportController(SplunkHECLogsExporterConfig{})
		defer c.Shutdown(context.Background())
		for i := 0; i < maxQueuedHECBatches+1; i++ {
			c.QueueLogs(logsWithRecord(nil, nil, fmt.Sprint(i)))
		}
		if s := c.Status(); s.QueuedRecords != maxQueuedHECBatches || s.DroppedRecords != 1 {
			t.Fatalf("%+v", s)
		}
		remote, captured := hecTestServer(t, 200, `{"code":0}`)
		config := SplunkHECLogsExporterConfig{Endpoint: remote.URL, Token: "test", Enabled: true}
		c.Apply(config, newTestHECExporter(t, remote.URL, config))
		waitForHECQueue(t, c, func(s SplunkHECLogsExportStatus) bool {
			return s.QueuedRecords == 0 && s.ExportedRecords == maxQueuedHECBatches
		})
		if len(*captured) != maxQueuedHECBatches || (*captured)[0].events[0]["event"] != "0" || (*captured)[maxQueuedHECBatches-1].events[0]["event"] != fmt.Sprint(maxQueuedHECBatches-1) {
			t.Fatal("overflow evicted accepted data or admitted the new batch")
		}
	})
	t.Run("records", func(t *testing.T) {
		c := NewSplunkHECLogsExportController(SplunkHECLogsExporterConfig{})
		defer c.Shutdown(context.Background())
		logs := plog.NewLogs()
		records := logs.ResourceLogs().AppendEmpty().ScopeLogs().AppendEmpty().LogRecords()
		for i := 0; i < maxQueuedHECRecords; i++ {
			records.AppendEmpty().Body().SetStr("record")
		}
		c.QueueLogs(logs)
		c.QueueLogs(logsWithRecord(nil, nil, "new"))
		if s := c.Status(); s.QueuedRecords != maxQueuedHECRecords || s.DroppedRecords != 1 {
			t.Fatalf("%+v", s)
		}
		records.AppendEmpty()
		c.QueueLogs(logs)
		if c.Status().DroppedRecords != maxQueuedHECRecords+2 {
			t.Fatal("oversized batch was not reported")
		}
	})
	t.Run("bytes", func(t *testing.T) {
		c := NewSplunkHECLogsExportController(SplunkHECLogsExporterConfig{})
		defer c.Shutdown(context.Background())
		c.QueueLogs(logsWithRecord(nil, nil, strings.Repeat("x", maxQueuedHECBytes)))
		if s := c.Status(); s.QueuedRecords != 0 || s.DroppedRecords != 1 {
			t.Fatalf("%+v", s)
		}
	})
}

func TestHECQueueProtectsInflightBatchAndCancelsOnShutdown(t *testing.T) {
	started, canceled, release := make(chan struct{}), make(chan struct{}), make(chan struct{})
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		close(started)
		select {
		case <-r.Context().Done():
		case <-release:
		}
		close(canceled)
	}))
	defer remote.Close()
	defer close(release)
	c := NewSplunkHECLogsExportController(SplunkHECLogsExporterConfig{Endpoint: remote.URL, Token: "test", Enabled: true})
	c.QueueLogs(logsWithRecord(nil, nil, "in flight"))
	<-started
	for i := 0; i < maxQueuedHECBatches; i++ {
		c.QueueLogs(logsWithRecord(nil, nil, "queued"))
	}
	if s := c.Status(); s.QueuedRecords != maxQueuedHECBatches || s.DroppedRecords != 1 {
		t.Fatalf("%+v", s)
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	c.Shutdown(ctx)
	select {
	case <-canceled:
	case <-ctx.Done():
		t.Fatal("shutdown did not cancel active request")
	}
	c.mu.RLock()
	active := c.flushCancel != nil
	c.mu.RUnlock()
	if active {
		t.Fatal("worker or timer survived shutdown")
	}
	version := c.Status().Version
	config := c.Config()
	config.Token = "replacement"
	c.ApplyKeepingActivity(config, newTestHECExporter(t, remote.URL, config))
	if c.Status().Version != version || c.Config().Token == "replacement" {
		t.Fatal("a late configuration change revived the closed exporter")
	}
	if err := c.SetEnabled(true); err == nil {
		t.Fatal("enabling a closed exporter succeeded")
	}
}

func TestHECQueueConcurrentIngestionAndConfiguration(t *testing.T) {
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = w.Write([]byte(`{"code":0}`)) }))
	defer remote.Close()
	config := SplunkHECLogsExporterConfig{Endpoint: remote.URL, Token: "test", Enabled: true}
	c := NewSplunkHECLogsExportController(config)
	defer c.Shutdown(context.Background())
	var wg sync.WaitGroup
	for i := 0; i < 4; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for j := 0; j < 20; j++ {
				c.QueueLogs(logsWithRecord(nil, nil, "concurrent"))
				_ = c.Status()
			}
		}()
	}
	wg.Add(1)
	go func() {
		defer wg.Done()
		for i := 0; i < 10; i++ {
			_ = c.SetEnabled(false)
			c.ApplyKeepingActivity(config, newTestHECExporter(t, remote.URL, config))
		}
	}()
	wg.Wait()
	_ = c.SetEnabled(true)
	waitForHECQueue(t, c, func(s SplunkHECLogsExportStatus) bool { return s.ExportedRecords == 80 && s.QueuedRecords == 0 })
}

func TestHECQueuePauseCancelsResponseBodyWithoutFailureOrLoss(t *testing.T) {
	started, release := make(chan struct{}), make(chan struct{})
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		w.WriteHeader(http.StatusOK)
		w.(http.Flusher).Flush()
		close(started)
		select {
		case <-r.Context().Done():
		case <-release:
		}
	}))
	defer remote.Close()
	defer close(release)
	c := NewSplunkHECLogsExportController(SplunkHECLogsExporterConfig{Endpoint: remote.URL, Token: "test", Enabled: true, Timeout: time.Minute})
	defer c.Shutdown(context.Background())
	c.QueueLogs(logsWithRecord(nil, nil, "held response body"))
	<-started
	done := make(chan error, 1)
	go func() { done <- c.SetEnabled(false) }()
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		t.Fatal("pause waited for the old response body")
	}
	if s := c.Status(); s.Enabled || s.QueuedRecords != 1 || s.DroppedRecords != 0 || s.FailedBatches != 0 || s.LastExportError != "" {
		t.Fatalf("pause lost logs or reported intentional cancellation as a failure: %+v", s)
	}
}

func TestHECQueueRetriesWithoutNewTelemetryAndCancelsRetryWhenPaused(t *testing.T) {
	var reject atomic.Bool
	reject.Store(true)
	var requests atomic.Int32
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests.Add(1)
		if reject.Load() {
			w.WriteHeader(401)
			_, _ = w.Write([]byte(`{"code":4}`))
			return
		}
		_, _ = w.Write([]byte(`{"code":0}`))
	}))
	defer remote.Close()
	c := NewSplunkHECLogsExportController(SplunkHECLogsExporterConfig{Endpoint: remote.URL, Token: "test", Enabled: true})
	defer c.Shutdown(context.Background())
	if err := c.ExportLogs(context.Background(), logsWithRecord(nil, nil, "retry without new input")); err == nil {
		t.Fatal("expected rejection")
	}
	reject.Store(false)
	waitForHECQueue(t, c, func(s SplunkHECLogsExportStatus) bool { return s.ExportedRecords == 1 && s.QueuedRecords == 0 })
	reject.Store(true)
	if err := c.ExportLogs(context.Background(), logsWithRecord(nil, nil, "pause during retry")); err == nil {
		t.Fatal("expected rejection")
	}
	if err := c.SetEnabled(false); err != nil {
		t.Fatal(err)
	}
	before := requests.Load()
	reject.Store(false)
	time.Sleep(1100 * time.Millisecond)
	if requests.Load() != before || c.Status().QueuedRecords != 1 {
		t.Fatal("paused retry sent a queued log")
	}
	if err := c.SetEnabled(true); err != nil {
		t.Fatal(err)
	}
	waitForHECQueue(t, c, func(s SplunkHECLogsExportStatus) bool { return s.ExportedRecords == 2 && s.QueuedRecords == 0 })
}

func TestHECQueueCountsCompletedUpstreamSendsNotEnqueue(t *testing.T) {
	started, release := make(chan struct{}), make(chan struct{})
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var event hecEvent
		if err := json.NewDecoder(hecRequestBody(t, r)).Decode(&event); err != nil {
			t.Error(err)
		}
		if event.Event != "held send" {
			t.Errorf("unexpected event: %v", event.Event)
		}
		close(started)
		select {
		case <-release:
		case <-r.Context().Done():
			return
		}
		_, _ = w.Write([]byte(`{"code":0}`))
	}))
	defer remote.Close()
	c := NewSplunkHECLogsExportController(SplunkHECLogsExporterConfig{Endpoint: remote.URL, Token: "test", Enabled: true})
	defer c.Shutdown(context.Background())
	c.QueueLogs(logsWithRecord(nil, nil, "held send"))
	<-started
	if s := c.Status(); s.ExportedRecords != 0 || s.QueuedRecords != 1 {
		t.Fatalf("enqueued logs counted as exported: %+v", s)
	}
	close(release)
	waitForHECQueue(t, c, func(s SplunkHECLogsExportStatus) bool {
		return s.ExportedRecords == 1 && s.ExportedBatches == 1 && s.QueuedRecords == 0
	})
}

func TestHECQueueHonorsRetryAfter(t *testing.T) {
	for _, statusCode := range []int{http.StatusTooManyRequests, http.StatusServiceUnavailable} {
		for _, format := range []string{"seconds", "date"} {
			t.Run(fmt.Sprintf("%d/%s", statusCode, format), func(t *testing.T) {
				var requests atomic.Int32
				first, retried := make(chan time.Time, 1), make(chan time.Time, 1)
				remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
					if requests.Add(1) == 1 {
						now := time.Now()
						deadline := now.Add(2 * time.Second)
						header := "2"
						if format == "date" {
							deadline = now.Add(3 * time.Second).UTC().Truncate(time.Second)
							header = deadline.Format(http.TimeFormat)
						}
						first <- deadline
						w.Header().Set("Retry-After", header)
						w.WriteHeader(statusCode)
						_, _ = w.Write([]byte(`{"code":9}`))
						return
					}
					retried <- time.Now()
					_, _ = w.Write([]byte(`{"code":0}`))
				}))
				defer remote.Close()
				c := NewSplunkHECLogsExportController(SplunkHECLogsExporterConfig{Endpoint: remote.URL, Token: "test", Enabled: true})
				defer c.Shutdown(context.Background())
				if err := c.ExportLogs(context.Background(), logsWithRecord(nil, nil, "throttled log")); err == nil {
					t.Fatal("expected initial throttle error")
				}
				deadline := <-first
				select {
				case sent := <-retried:
					if sent.Before(deadline) {
						t.Fatalf("retried %v before the endpoint's Retry-After deadline", deadline.Sub(sent))
					}
				case <-time.After(5 * time.Second):
					t.Fatal("queued log was not retried")
				}
				waitForHECQueue(t, c, func(s SplunkHECLogsExportStatus) bool { return s.ExportedRecords == 1 && s.QueuedRecords == 0 })
			})
		}
	}
}

func TestHECQueueUpstreamRetriesOnlyUnsentResourceGroups(t *testing.T) {
	var acceptedA, acceptedB atomic.Int32
	var rejectB atomic.Bool
	rejectB.Store(true)
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Splunk configured-token" {
			t.Error("telemetry overrode configured credentials")
		}
		var event hecEvent
		if err := json.NewDecoder(hecRequestBody(t, r)).Decode(&event); err != nil {
			t.Error(err)
		}
		if event.Index == "b" && rejectB.Load() {
			w.WriteHeader(503)
			_, _ = w.Write([]byte(`{"code":9}`))
			return
		}
		if event.Index == "a" {
			acceptedA.Add(1)
		} else if event.Index == "b" {
			acceptedB.Add(1)
		} else {
			t.Errorf("unexpected index: %s", event.Index)
		}
		_, _ = w.Write([]byte(`{"code":0}`))
	}))
	defer remote.Close()
	c := NewSplunkHECLogsExportController(SplunkHECLogsExporterConfig{Endpoint: remote.URL, Token: "configured-token", Index: "studio", Enabled: true})
	defer c.Shutdown(context.Background())
	logs := logsWithRecord(map[string]string{splunkIndexAttribute: "a", "com.splunk.hec.token": "attribute-token"}, nil, "first resource")
	other := logsWithRecord(map[string]string{splunkIndexAttribute: "b"}, nil, "second resource")
	other.ResourceLogs().At(0).CopyTo(logs.ResourceLogs().AppendEmpty())
	if err := c.ExportLogs(context.Background(), logs); err == nil {
		t.Fatal("expected partial failure")
	}
	if s := c.Status(); s.ExportedRecords != 1 || s.QueuedRecords != 1 || s.DroppedRecords != 0 {
		t.Fatalf("incorrect partial accounting: %+v", s)
	}
	rejectB.Store(false)
	waitForHECQueue(t, c, func(s SplunkHECLogsExportStatus) bool { return s.ExportedRecords == 2 && s.QueuedRecords == 0 })
	if acceptedA.Load() != 1 || acceptedB.Load() != 1 {
		t.Fatalf("successful resource replayed: a=%d b=%d", acceptedA.Load(), acceptedB.Load())
	}
}

func TestHECQueueRetainsEveryRetryableResourceGroup(t *testing.T) {
	for _, permanent := range []bool{false, true} {
		t.Run(fmt.Sprint(permanent), func(t *testing.T) {
			var reject atomic.Bool
			reject.Store(true)
			var acceptedA, acceptedB, acceptedHealthy atomic.Int32
			remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				var event hecEvent
				if err := json.NewDecoder(hecRequestBody(t, r)).Decode(&event); err != nil {
					t.Error(err)
				}
				if event.Index == "a" && permanent {
					w.WriteHeader(http.StatusBadRequest)
					_, _ = w.Write([]byte(`{"code":13}`))
					return
				}
				if event.Index != "healthy" && reject.Load() {
					w.WriteHeader(http.StatusServiceUnavailable)
					_, _ = w.Write([]byte(`{"code":9}`))
					return
				}
				switch event.Index {
				case "a":
					acceptedA.Add(1)
				case "b":
					acceptedB.Add(1)
				case "healthy":
					acceptedHealthy.Add(1)
				default:
					t.Errorf("unexpected index %q", event.Index)
				}
				_, _ = w.Write([]byte(`{"code":0}`))
			}))
			defer remote.Close()
			c := NewSplunkHECLogsExportController(SplunkHECLogsExporterConfig{Endpoint: remote.URL, Token: "test", Index: "studio", Enabled: true})
			defer c.Shutdown(context.Background())
			logs := plog.NewLogs()
			for _, index := range []string{"a", "b", "healthy"} {
				resource := logsWithRecord(map[string]string{splunkIndexAttribute: index}, nil, index)
				resource.ResourceLogs().At(0).CopyTo(logs.ResourceLogs().AppendEmpty())
			}
			if err := c.ExportLogs(context.Background(), logs); err == nil {
				t.Fatal("expected partial export error")
			}
			queued, dropped := 2, uint64(0)
			if permanent {
				queued, dropped = 1, 1
			}
			if status := c.Status(); status.ExportedRecords != 1 || status.QueuedRecords != queued || status.DroppedRecords != dropped {
				t.Fatalf("incorrect partial error accounting: %+v", status)
			}
			reject.Store(false)
			waitForHECQueue(t, c, func(s SplunkHECLogsExportStatus) bool { return s.QueuedRecords == 0 })
			wantA := int32(1)
			if permanent {
				wantA = 0
			}
			if acceptedA.Load() != wantA || acceptedB.Load() != 1 || acceptedHealthy.Load() != 1 || c.Status().DroppedRecords != dropped {
				t.Fatalf("retry lost or replayed resource groups: a=%d b=%d healthy=%d status=%+v", acceptedA.Load(), acceptedB.Load(), acceptedHealthy.Load(), c.Status())
			}
		})
	}
}

type pauseAfterSuccessfulHECSend struct {
	exporter.Logs
	completed chan struct{}
	calls     atomic.Int32
}

func (p *pauseAfterSuccessfulHECSend) ConsumeLogs(ctx context.Context, logs plog.Logs) error {
	err := p.Logs.ConsumeLogs(ctx, logs)
	if p.calls.Add(1) == 1 {
		close(p.completed)
		<-ctx.Done()
	}
	return err
}
func TestHECQueueCompletedSendIsNotRetriedWhenPaused(t *testing.T) {
	var requests atomic.Int32
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests.Add(1)
		_, _ = io.Copy(io.Discard, r.Body)
		_, _ = w.Write([]byte(`{"code":0}`))
	}))
	defer remote.Close()
	c := NewSplunkHECLogsExportController(SplunkHECLogsExporterConfig{Endpoint: remote.URL, Token: "test", Enabled: true})
	defer c.Shutdown(context.Background())
	wrapper := &pauseAfterSuccessfulHECSend{Logs: c.exporter.exp, completed: make(chan struct{})}
	c.exporter.exp = wrapper
	done := make(chan error, 1)
	go func() { done <- c.ExportLogs(context.Background(), logsWithRecord(nil, nil, "accepted before pause")) }()
	<-wrapper.completed
	if err := c.SetEnabled(false); err != nil {
		t.Fatal(err)
	}
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		t.Fatal("successful send stayed pending after pause")
	}
	if s := c.Status(); s.ExportedRecords != 1 || s.QueuedRecords != 0 {
		t.Fatalf("incorrect completed-send counters: %+v", s)
	}
	if err := c.SetEnabled(true); err != nil {
		t.Fatal(err)
	}
	if err := c.ExportLogs(context.Background(), logsWithRecord(nil, nil, "new log after resume")); err != nil {
		t.Fatal(err)
	}
	if requests.Load() != 2 || c.Status().ExportedRecords != 2 {
		t.Fatal("resume replayed a completed batch")
	}
}
