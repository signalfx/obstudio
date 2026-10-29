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
	"testing/iotest"
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

func TestHECQueueDrainsAcceptedCapacityWarningsWithoutRetry(t *testing.T) {
	for _, code := range []int{24, 25} {
		t.Run(fmt.Sprint(code), func(t *testing.T) {
			var requests atomic.Int32
			remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if requests.Add(1) == 1 {
					fmt.Fprintf(w, `{"code":%d}`, code)
					return
				}
				_, _ = w.Write([]byte(`{"code":0}`))
			}))
			defer remote.Close()
			c := NewSplunkHECLogsExportController(SplunkHECLogsExporterConfig{Endpoint: remote.URL, Token: "test", Enabled: true})
			defer c.Shutdown(context.Background())
			c.QueueLogs(logsWithRecord(nil, nil, "capacity warning"))
			c.QueueLogs(logsWithRecord(nil, nil, "following batch"))
			waitForHECQueue(t, c, func(s SplunkHECLogsExportStatus) bool { return s.QueuedRecords == 0 })
			status := c.Status()
			if requests.Load() != 2 || status.ExportedRecords != 2 || status.ExportedBatches != 2 || status.FailedBatches != 0 || status.LastExportError != "" {
				t.Fatalf("accepted warning was retried or blocked delivery: requests=%d status=%+v", requests.Load(), status)
			}
		})
	}
}

type heldHECSubmission struct {
	exporter.Logs
	entered, release chan struct{}
}

func (p heldHECSubmission) ConsumeLogs(ctx context.Context, logs plog.Logs) error {
	close(p.entered)
	<-p.release
	return fmt.Errorf("submission rejected during shutdown")
}

func TestHECQueueShutdownAccountsForAdmittedSubmissionOnce(t *testing.T) {
	c := NewSplunkHECLogsExportController(SplunkHECLogsExporterConfig{})
	pipeline := heldHECSubmission{Logs: c.pipeline, entered: make(chan struct{}), release: make(chan struct{})}
	c.pipeline = pipeline
	submitted := make(chan struct{})
	go func() { c.QueueLogs(logsWithRecord(nil, nil, "admitted before shutdown")); close(submitted) }()
	<-pipeline.entered
	c.Shutdown(context.Background())
	close(pipeline.release)
	select {
	case <-submitted:
	case <-time.After(3 * time.Second):
		t.Fatal("admitted submission did not finish")
	}
	if status := c.Status(); status.QueuedRecords != 0 || status.DroppedRecords != 1 {
		t.Fatalf("shutdown counted the same reservation twice: %+v", status)
	}
	c.mu.RLock()
	defer c.mu.RUnlock()
	if c.pendingBytes != 0 || c.pendingBatches != 0 {
		t.Fatal("retired queue bookkeeping became negative")
	}
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
			var requests, accepted atomic.Int32
			remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				requests.Add(1)
				decoder := json.NewDecoder(hecRequestBody(t, r))
				for number := 0; ; number++ {
					var event struct{ Index string }
					if err := decoder.Decode(&event); err == io.EOF {
						break
					} else if err != nil {
						t.Error(err)
						return
					}
					if event.Index == "invalid-record-index" {
						w.WriteHeader(test.status)
						_, _ = fmt.Fprintf(w, `{"code":%d,"invalid-event-number":%d}`, test.code, number)
						return
					}
					accepted.Add(1)
				}
				_, _ = w.Write([]byte(`{"code":0}`))
			}))
			defer remote.Close()
			config := SplunkHECLogsExporterConfig{Endpoint: remote.URL, Token: "test", Index: "studio", ConnectionVerified: true}
			c := NewSplunkHECLogsExportController(config)
			defer c.Shutdown(context.Background())
			logs := logsWithRecord(nil, nil, "valid prefix")
			invalid := logs.ResourceLogs().At(0).ScopeLogs().At(0).LogRecords().AppendEmpty()
			invalid.Body().SetStr("invalid")
			invalid.Attributes().PutStr("com.splunk.index", "invalid-record-index")
			c.QueueLogs(logs)
			if err := c.SetEnabled(true); err != nil {
				t.Fatal(err)
			}
			waitForHECQueue(t, c, func(s SplunkHECLogsExportStatus) bool { return s.QueuedRecords == 0 && s.ExportedRecords == 1 })
			if s := c.Status(); s.DroppedRecords != 1 || s.FailedBatches != 1 || requests.Load() != 2 || accepted.Load() != 1 {
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
		extra := logsWithRecord(nil, nil, "new")
		attempts := 0
		allocations := testing.AllocsPerRun(1, func() { attempts++; c.QueueLogs(extra) })
		if allocations > 8 {
			t.Fatalf("full queue performed payload preparation: %.0f allocations", allocations)
		}
		if s := c.Status(); s.QueuedRecords != maxQueuedHECRecords || s.DroppedRecords != uint64(attempts) {
			t.Fatalf("%+v", s)
		}
		records.AppendEmpty()
		c.QueueLogs(logs)
		if c.Status().DroppedRecords != uint64(maxQueuedHECRecords+1+attempts) {
			t.Fatal("oversized batch was not reported")
		}
	})
	t.Run("bytes", func(t *testing.T) {
		for _, normalize := range []bool{false, true} {
			t.Run(fmt.Sprint(normalize), func(t *testing.T) {
				c := NewSplunkHECLogsExportController(SplunkHECLogsExporterConfig{})
				defer c.Shutdown(context.Background())
				logs := logsWithRecord(nil, nil, strings.Repeat("x", maxQueuedHECBytes))
				if normalize {
					logs.ResourceLogs().At(0).ScopeLogs().At(0).LogRecords().At(0).Body().SetEmptySlice().AppendEmpty().SetStr(strings.Repeat("\x00", maxQueuedHECBytes/6+1))
				}
				c.QueueLogs(logs)
				if s := c.Status(); s.QueuedRecords != 0 || s.DroppedRecords != 1 {
					t.Fatalf("%+v", s)
				}
				c.QueueLogs(logsWithRecord(nil, nil, "next valid batch"))
				if s := c.Status(); s.QueuedRecords != 1 || s.DroppedRecords != 1 {
					t.Fatal("byte limit failure retained its reservation", s)
				}
			})
		}
	})
}

func TestHECQueueBoundsIndexMetadataExpansion(t *testing.T) {
	for _, scopeMetadata := range []bool{false, true} {
		t.Run(fmt.Sprint(scopeMetadata), func(t *testing.T) {
			var requests atomic.Int32
			remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				requests.Add(1)
				_, _ = w.Write([]byte(`{"code":0}`))
			}))
			defer remote.Close()
			c := NewSplunkHECLogsExportController(SplunkHECLogsExporterConfig{Endpoint: remote.URL, Token: "test", Enabled: true})
			defer c.Shutdown(context.Background())
			logs := logsWithRecord(nil, nil, "indexed")
			resource := logs.ResourceLogs().At(0)
			scope := resource.ScopeLogs().At(0)
			attributes := resource.Resource().Attributes()
			if scopeMetadata {
				attributes = scope.Scope().Attributes()
			}
			for i := 0; i < 1000; i++ {
				attributes.PutStr(fmt.Sprint(i), strings.Repeat("x", 1024))
			}
			records := scope.LogRecords()
			for i := 0; i < 1000; i++ {
				if i > 0 {
					records.AppendEmpty().Body().SetStr("indexed")
				}
				records.At(i).Attributes().PutStr("com.splunk.index", fmt.Sprint(i))
			}
			attempts := 0
			allocations := testing.AllocsPerRun(1, func() {
				attempts++
				if err := c.ExportLogs(context.Background(), logs); err == nil {
					t.Error("index metadata expansion exceeded the preparation budget")
				}
			})
			if allocations > 100_000 {
				t.Fatalf("preparation expanded unbounded metadata: %.0f allocations", allocations)
			}
			if s := c.Status(); s.QueuedRecords != 0 || s.ExportedRecords != 0 || s.DroppedRecords != uint64(attempts*records.Len()) || requests.Load() != 0 || attributes.Len() != 1000 || logs.ResourceLogs().Len() != 1 {
				t.Fatal("over-budget preparation changed delivery or caller data", s)
			}
			if err := c.ExportLogs(context.Background(), logsWithRecord(nil, nil, "next valid batch")); err != nil || c.Status().ExportedRecords != 1 || requests.Load() != 1 {
				t.Fatal("preparation failure blocked later delivery", err, c.Status())
			}
		})
	}
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
	result := make(chan error, 1)
	go func() { result <- c.ExportLogs(context.Background(), logsWithRecord(nil, nil, "in flight")) }()
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
	case err := <-result:
		if err == nil {
			t.Fatal("pending export reported success during shutdown")
		}
	case <-ctx.Done():
		t.Fatal("synchronous export remained blocked after shutdown")
	}
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
	for _, recordIndex := range []bool{false, true} {
		t.Run(fmt.Sprint(recordIndex), func(t *testing.T) {
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
			logs := logsWithRecord(map[string]string{"com.splunk.index": "a", "com.splunk.hec.token": "attribute-token"}, nil, "first resource")
			other := logsWithRecord(map[string]string{"com.splunk.index": "b"}, nil, "second resource")
			if recordIndex {
				record := logs.ResourceLogs().At(0).ScopeLogs().At(0).LogRecords().AppendEmpty()
				record.Body().SetStr("second record")
				record.Attributes().PutStr("com.splunk.index", "b")
			} else {
				other.ResourceLogs().At(0).CopyTo(logs.ResourceLogs().AppendEmpty())
			}
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
		})
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
				resource := logsWithRecord(map[string]string{"com.splunk.index": index}, nil, index)
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

func TestHECQueueRetriesOnlyTheUnsentSuffix(t *testing.T) {
	for _, test := range []struct {
		code                      int
		oversized, sharedResource bool
	}{{6, false, false}, {12, false, false}, {13, false, false}, {6, true, false}, {6, false, true}} {
		t.Run(fmt.Sprintf("%d/oversized=%t/shared=%t", test.code, test.oversized, test.sharedResource), func(t *testing.T) {
			code := test.code
			dropped := uint64(1)
			if test.oversized {
				dropped++
			}
			var acceptedFirst, acceptedLast, requests atomic.Int32
			remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				requests.Add(1)
				decoder := json.NewDecoder(hecRequestBody(t, r))
				for position := 0; ; position++ {
					var event hecEvent
					if err := decoder.Decode(&event); err == io.EOF {
						break
					} else if err != nil {
						t.Error(err)
						return
					}
					switch event.Event {
					case "first":
						acceptedFirst.Add(1)
					case "bad":
						status := http.StatusBadRequest
						if code == 13 {
							status = http.StatusOK
						}
						w.WriteHeader(status)
						_, _ = fmt.Fprintf(w, `{"code":%d,"invalid-event-number":%d}`, code, position)
						return
					case "last":
						acceptedLast.Add(1)
					default:
						t.Error("unexpected event body")
					}
				}
				_, _ = w.Write([]byte(`{"code":0}`))
			}))
			defer remote.Close()
			c := NewSplunkHECLogsExportController(SplunkHECLogsExporterConfig{Endpoint: remote.URL, Token: "test", Index: "studio", Enabled: true})
			defer c.Shutdown(context.Background())
			logs := logsWithRecord(nil, nil, "first")
			if test.sharedResource {
				logs.ResourceLogs().At(0).Resource().Attributes().PutStr("padding", strings.Repeat("x", 6<<20))
			}
			records := logs.ResourceLogs().At(0).ScopeLogs().At(0).LogRecords()
			if test.oversized {
				records.At(0).Body().SetStr(strings.Repeat("\x00", maxQueuedHECBytes/6+1))
				records.AppendEmpty().Body().SetStr("first")
			}
			records.AppendEmpty().Body().SetStr("bad")
			records.AppendEmpty().Body().SetStr("last")
			if err := c.ExportLogs(context.Background(), logs); err == nil {
				t.Fatal("expected rejection of one event")
			}
			if s := c.Status(); s.ExportedRecords != 1 || s.DroppedRecords != dropped || s.QueuedRecords != 1 {
				t.Fatal("partial delivery was not accounted", s)
			}
			waitForHECQueue(t, c, func(s SplunkHECLogsExportStatus) bool { return s.ExportedRecords == 2 && s.QueuedRecords == 0 })
			if acceptedFirst.Load() != 1 || acceptedLast.Load() != 1 || requests.Load() != 2 || c.Status().DroppedRecords != dropped {
				t.Fatal("accepted prefix replayed or valid suffix lost", c.Status())
			}
		})
	}
}

type hecCancelAfterResponse struct {
	reader   io.Reader
	complete func()
}

func (b *hecCancelAfterResponse) Read(data []byte) (int, error) {
	n, err := b.reader.Read(data)
	if err == io.EOF {
		b.complete()
	}
	return n, err
}
func (b *hecCancelAfterResponse) Close() error { b.complete(); return nil }

func TestHECQueueCompletedSendIsNotRetriedWhenPaused(t *testing.T) {
	for _, oversized := range []bool{false, true} {
		t.Run(fmt.Sprint(oversized), func(t *testing.T) {
			c := NewSplunkHECLogsExportController(SplunkHECLogsExporterConfig{Endpoint: "http://hec.test/services/collector", Token: "test", Index: "studio", Enabled: true})
			defer c.Shutdown(context.Background())
			var requests atomic.Int32
			paused := make(chan error, 1)
			var once sync.Once
			c.exporter.transport.RegisterProtocol("http", hecRoundTripperFunc(func(request *http.Request) (*http.Response, error) {
				requests.Add(1)
				return &http.Response{StatusCode: 200, Header: make(http.Header), Body: &hecCancelAfterResponse{reader: strings.NewReader(`{"code":0}`), complete: func() {
					once.Do(func() {
						go func() { paused <- c.SetEnabled(false) }()
						select {
						case <-request.Context().Done():
						case <-time.After(2 * time.Second):
							t.Error("pause did not cancel the send")
						}
					})
				}}}, nil
			}))
			ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
			defer cancel()
			logs := logsWithRecord(nil, nil, "accepted")
			var dropped uint64
			if oversized {
				logs.ResourceLogs().At(0).ScopeLogs().At(0).LogRecords().AppendEmpty().Body().SetStr(strings.Repeat("\x00", maxQueuedHECBytes/6+1))
				dropped = 1
			}
			if err := c.ExportLogs(ctx, logs); (err != nil) != oversized {
				t.Fatal("unexpected completion result", err)
			}
			select {
			case err := <-paused:
				if err != nil {
					t.Fatal(err)
				}
			case <-ctx.Done():
				t.Fatal("pause did not finish")
			}
			if s := c.Status(); s.QueuedRecords != 0 || s.ExportedRecords != 1 || s.DroppedRecords != dropped {
				t.Fatal("received acknowledgement was lost", s)
			}
			if err := c.SetEnabled(true); err != nil {
				t.Fatal(err)
			}
			if requests.Load() != 1 || c.Status().ExportedRecords != 1 {
				t.Fatal("resume replayed an accepted event")
			}
			if err := c.ExportLogs(ctx, logsWithRecord(nil, nil, "new log after resume")); err != nil {
				t.Fatal(err)
			}
			if requests.Load() != 2 || c.Status().ExportedRecords != 2 {
				t.Fatal("export did not continue after resume")
			}
		})
	}
}

func TestHECQueueCompletedRejectionIsNotRetriedWhenPaused(t *testing.T) {
	c := NewSplunkHECLogsExportController(SplunkHECLogsExporterConfig{Endpoint: "http://hec.test/services/collector", Token: "test", Enabled: true})
	defer c.Shutdown(context.Background())
	var requests atomic.Int32
	paused := make(chan error, 1)
	var once sync.Once
	c.exporter.transport.RegisterProtocol("http", hecRoundTripperFunc(func(request *http.Request) (*http.Response, error) {
		number := requests.Add(1)
		var event hecEvent
		if err := json.NewDecoder(hecRequestBody(t, request)).Decode(&event); err != nil {
			t.Error(err)
		}
		code := 0
		if event.Index == "bad" {
			code = 6
		}
		return &http.Response{StatusCode: 200, Header: make(http.Header), Body: &hecCancelAfterResponse{reader: strings.NewReader(fmt.Sprintf(`{"code":%d}`, code)), complete: func() {
			if number != 2 {
				return
			}
			once.Do(func() {
				go func() { paused <- c.SetEnabled(false) }()
				select {
				case <-request.Context().Done():
				case <-time.After(2 * time.Second):
					t.Error("pause did not cancel the send")
				}
			})
		}}}, nil
	}))
	logs := logsWithRecord(map[string]string{"com.splunk.index": "good"}, nil, "accepted")
	logsWithRecord(map[string]string{"com.splunk.index": "bad"}, nil, "rejected").ResourceLogs().At(0).CopyTo(logs.ResourceLogs().AppendEmpty())
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	if err := c.ExportLogs(ctx, logs); err == nil {
		t.Fatal("permanent rejection was hidden")
	}
	select {
	case err := <-paused:
		if err != nil {
			t.Fatal(err)
		}
	case <-ctx.Done():
		t.Fatal("pause did not finish")
	}
	if status := c.Status(); status.ExportedRecords != 1 || status.DroppedRecords != 1 || status.QueuedRecords != 0 {
		t.Fatal("completed rejection was retried or miscounted", status)
	}
	if err := c.SetEnabled(true); err != nil {
		t.Fatal(err)
	}
	if requests.Load() != 2 {
		t.Fatal("resume replayed a completed batch")
	}
	if err := c.ExportLogs(ctx, logsWithRecord(nil, nil, "new log")); err != nil {
		t.Fatal(err)
	}
	if status := c.Status(); status.ExportedRecords != 2 || status.DroppedRecords != 1 || status.QueuedRecords != 0 || requests.Load() != 3 {
		t.Fatal("subsequent delivery was miscounted", status)
	}
}

func TestHECQueuePauseAfterThrottleHonorsRetryAfter(t *testing.T) {
	for _, test := range []struct {
		statusCode int
		body       string
		readError  bool
	}{{429, `{"code":9}`, false}, {503, `{"code":9}`, false}, {503, strings.Repeat("x", 4097), false}, {429, "", true}} {
		t.Run(fmt.Sprintf("%d/body=%d/readError=%t", test.statusCode, len(test.body), test.readError), func(t *testing.T) {
			statusCode := test.statusCode
			c := NewSplunkHECLogsExportController(SplunkHECLogsExporterConfig{Endpoint: "http://hec.test/services/collector", Token: "test", Enabled: true})
			defer c.Shutdown(context.Background())
			var requests atomic.Int32
			paused := make(chan error, 1)
			retried := make(chan time.Time, 1)
			deadline := time.Now()
			var once sync.Once
			c.exporter.transport.RegisterProtocol("http", hecRoundTripperFunc(func(request *http.Request) (*http.Response, error) {
				if requests.Add(1) != 1 {
					retried <- time.Now()
					return &http.Response{StatusCode: 200, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(`{"code":0}`))}, nil
				}
				deadline = time.Now().Add(2 * time.Second)
				var reader io.Reader = strings.NewReader(test.body)
				if test.readError {
					reader = iotest.ErrReader(io.ErrUnexpectedEOF)
				}
				return &http.Response{StatusCode: statusCode, Header: http.Header{"Retry-After": []string{"2"}}, Body: &hecCancelAfterResponse{reader: reader, complete: func() {
					once.Do(func() {
						go func() { paused <- c.SetEnabled(false) }()
						select {
						case <-request.Context().Done():
						case <-time.After(2 * time.Second):
							t.Error("pause did not cancel the send")
						}
					})
				}}}, nil
			}))
			ctx, cancel := context.WithTimeout(context.Background(), 6*time.Second)
			defer cancel()
			if err := c.ExportLogs(ctx, logsWithRecord(nil, nil, "throttled")); err == nil {
				t.Fatal("throttle was hidden")
			}
			select {
			case err := <-paused:
				if err != nil {
					t.Fatal(err)
				}
			case <-ctx.Done():
				t.Fatal("pause did not finish")
			}
			if err := c.SetEnabled(true); err != nil {
				t.Fatal(err)
			}
			select {
			case sent := <-retried:
				if sent.Before(deadline) {
					t.Fatal("resume bypassed Retry-After")
				}
			case <-ctx.Done():
				t.Fatal("throttled event was not retried")
			}
			waitForHECQueue(t, c, func(s SplunkHECLogsExportStatus) bool { return s.ExportedRecords == 1 && s.QueuedRecords == 0 })
			if s := c.Status(); s.DroppedRecords != 0 || requests.Load() != 2 {
				t.Fatal("throttle recovery was miscounted", s)
			}
		})
	}
}
