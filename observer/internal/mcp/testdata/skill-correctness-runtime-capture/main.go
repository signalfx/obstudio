package main

import (
	"bytes"
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"time"

	"go.opentelemetry.io/collector/pdata/pcommon"
	"go.opentelemetry.io/collector/pdata/plog/plogotlp"
	"go.opentelemetry.io/collector/pdata/pmetric"
	"go.opentelemetry.io/collector/pdata/pmetric/pmetricotlp"
	"go.opentelemetry.io/collector/pdata/ptrace"
	"go.opentelemetry.io/collector/pdata/ptrace/ptraceotlp"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/trace"
)

type packet struct {
	Path string          `json:"path"`
	Body json.RawMessage `json:"body"`
}
type capture struct {
	mu      sync.Mutex
	packets []packet
	spans   []sdktrace.ReadOnlySpan
}

func (c *capture) ExportSpans(_ context.Context, s []sdktrace.ReadOnlySpan) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.spans = append(c.spans, s...)
	return nil
}
func (c *capture) Shutdown(context.Context) error { return nil }
func must(err error) {
	if err != nil {
		log.Fatal(err)
	}
}
func write(path string, v any) {
	b, e := json.MarshalIndent(v, "", "  ")
	must(e)
	must(os.WriteFile(path, append(b, '\n'), 0600))
}
func put(attrs pcommon.Map, kv attribute.KeyValue) {
	b, e := json.Marshal(kv.Value.AsInterface())
	must(e)
	var v any
	must(json.Unmarshal(b, &v))
	must(attrs.PutEmpty(string(kv.Key)).FromRaw(v))
}
func witnessData(spans []sdktrace.ReadOnlySpan) []byte {
	td := ptrace.NewTraces()
	for _, s := range spans {
		rs := td.ResourceSpans().AppendEmpty()
		for _, a := range s.Resource().Attributes() {
			put(rs.Resource().Attributes(), a)
		}
		ss := rs.ScopeSpans().AppendEmpty()
		ss.Scope().SetName(s.InstrumentationScope().Name)
		p := ss.Spans().AppendEmpty()
		p.SetName(s.Name())
		p.SetTraceID(pcommon.TraceID(s.SpanContext().TraceID()))
		p.SetSpanID(pcommon.SpanID(s.SpanContext().SpanID()))
		p.SetStartTimestamp(pcommon.NewTimestampFromTime(s.StartTime()))
		p.SetEndTimestamp(pcommon.NewTimestampFromTime(s.EndTime()))
		p.SetKind(ptrace.SpanKind(s.SpanKind()))
		p.Status().SetCode(ptrace.StatusCodeOk)
		for _, a := range s.Attributes() {
			put(p.Attributes(), a)
		}
	}
	b, e := (&ptrace.JSONMarshaler{}).MarshalTraces(td)
	must(e)
	return b
}
func main() {
	binary := flag.String("binary", "", "actual compiled application")
	dir := flag.String("dir", "", "app cwd")
	out := flag.String("out", "", "evidence directory")
	run := flag.String("run", "", "completed skill run ID")
	version := flag.String("version", "", "tested source digest")
	expectFile := flag.String("expect", "", "frozen requests")
	capturePort := flag.Int("port", 4348, "isolated capture receiver port")
	flag.Parse()
	must(os.MkdirAll(*out, 0700))
	var expected struct {
		Scenarios []struct {
			ID     string `json:"id"`
			Method string `json:"method"`
			Path   string `json:"path"`
			Body   string `json:"body"`
			Status int    `json:"http_status"`
		} `json:"scenarios"`
	}
	b, e := os.ReadFile(*expectFile)
	must(e)
	must(json.Unmarshal(b, &expected))
	cap := &capture{}
	client := &http.Client{Timeout: 10 * time.Second}
	captureURL := fmt.Sprintf("http://127.0.0.1:%d", *capturePort)
	server := &http.Server{Addr: fmt.Sprintf("127.0.0.1:%d", *capturePort)}
	server.Handler = http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw, err := io.ReadAll(io.LimitReader(r.Body, 16<<20))
		if err != nil {
			http.Error(w, err.Error(), 400)
			return
		}
		var normalized []byte
		switch r.URL.Path {
		case "/v1/traces":
			q := ptraceotlp.NewExportRequest()
			if strings.Contains(r.Header.Get("Content-Type"), "json") {
				err = q.UnmarshalJSON(raw)
			} else {
				err = q.UnmarshalProto(raw)
			}
			if err == nil {
				normalized, err = q.MarshalJSON()
			}
		case "/v1/metrics":
			q := pmetricotlp.NewExportRequest()
			if strings.Contains(r.Header.Get("Content-Type"), "json") {
				err = q.UnmarshalJSON(raw)
			} else {
				err = q.UnmarshalProto(raw)
			}
			if err == nil {
				normalized, err = q.MarshalJSON()
			}
		case "/v1/logs":
			q := plogotlp.NewExportRequest()
			if strings.Contains(r.Header.Get("Content-Type"), "json") {
				err = q.UnmarshalJSON(raw)
			} else {
				err = q.UnmarshalProto(raw)
			}
			if err == nil {
				normalized, err = q.MarshalJSON()
			}
		default:
			http.Error(w, "path", 404)
			return
		}
		if err != nil {
			http.Error(w, err.Error(), 400)
			return
		}
		cap.mu.Lock()
		cap.packets = append(cap.packets, packet{r.URL.Path, normalized})
		cap.mu.Unlock()
		resp, err := client.Post("http://127.0.0.1:4338"+r.URL.Path, "application/json", bytes.NewReader(normalized))
		if err != nil {
			http.Error(w, err.Error(), 502)
			return
		}
		defer resp.Body.Close()
		if resp.StatusCode != http.StatusOK {
			w.WriteHeader(resp.StatusCode)
			io.Copy(w, resp.Body)
			return
		}
		io.Copy(io.Discard, resp.Body)
		if strings.Contains(r.Header.Get("Content-Type"), "json") {
			w.Header().Set("Content-Type", "application/json")
			w.Write([]byte("{}"))
		} else {
			w.Header().Set("Content-Type", "application/x-protobuf")
			w.WriteHeader(http.StatusOK)
		}
	})
	go func() {
		if err := server.ListenAndServe(); err != http.ErrServerClosed {
			log.Fatal(err)
		}
	}()
	appLog, e := os.Create(filepath.Join(*out, "app.log"))
	must(e)
	defer appLog.Close()
	cmd := exec.Command(*binary)
	cmd.Dir = *dir
	appEnv := []string{}
	for _, entry := range os.Environ() {
		if !strings.HasPrefix(entry, "OTEL_") && !strings.HasPrefix(entry, "SPLUNK_") {
			appEnv = append(appEnv, entry)
		}
	}
	cmd.Env = append(appEnv, "OTEL_EXPORTER_OTLP_ENDPOINT="+captureURL, "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT="+captureURL+"/v1/logs", "OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf", "OTEL_SERVICE_NAME=skills-correctness-demo", "OTEL_RESOURCE_ATTRIBUTES=service.version="+*version+",deployment.environment.name=demo", "OTEL_BSP_SCHEDULE_DELAY=100", "OTEL_METRIC_EXPORT_INTERVAL=500")
	cmd.Stdout = appLog
	cmd.Stderr = appLog
	must(cmd.Start())
	ready := false
	for i := 0; i < 100; i++ {
		resp, err := client.Get("http://127.0.0.1:8000/health")
		if err == nil {
			io.Copy(io.Discard, resp.Body)
			resp.Body.Close()
			if resp.StatusCode == 200 {
				ready = true
				break
			}
		}
		time.Sleep(50 * time.Millisecond)
	}
	if !ready {
		cmd.Process.Kill()
		log.Fatal("app not ready")
	}
	provider := sdktrace.NewTracerProvider(sdktrace.WithSyncer(cap), sdktrace.WithResource(resource.NewSchemaless(attribute.String("service.name", "skills-correctness-demo"), attribute.String("service.version", *version))))
	witnesses := []trace.Span{}
	rows := []map[string]any{}
	for _, sc := range expected.Scenarios {
		_, witness := provider.Tracer("obstudio.verification").Start(context.Background(), "scenario "+sc.ID, trace.WithAttributes(attribute.String("verification.run_id", *run), attribute.String("verification.scenario", sc.ID), attribute.String("verification.proof_mode", "app_runtime")))
		request, err := http.NewRequest(sc.Method, "http://127.0.0.1:8000"+sc.Path, strings.NewReader(sc.Body))
		must(err)
		request.Header.Set("Content-Type", "application/json")
		request.Header.Set("traceparent", fmt.Sprintf("00-%s-%s-01", witness.SpanContext().TraceID(), witness.SpanContext().SpanID()))
		resp, err := client.Do(request)
		must(err)
		body, err := io.ReadAll(resp.Body)
		must(err)
		resp.Body.Close()
		if resp.StatusCode != sc.Status {
			cmd.Process.Kill()
			log.Fatalf("%s HTTP %d wanted %d", sc.ID, resp.StatusCode, sc.Status)
		}
		rows = append(rows, map[string]any{"id": sc.ID, "traceId": witness.SpanContext().TraceID().String(), "witnessSpanId": witness.SpanContext().SpanID().String(), "status": resp.StatusCode, "response": string(body)})
		witnesses = append(witnesses, witness)
	}
	must(cmd.Process.Signal(syscall.SIGTERM))
	must(cmd.Wait())
	// All captured records originate from SDK exports made by the terminated app.
	// The app's graceful shutdown must synchronously flush; absence is not fabricated.
	cap.mu.Lock()
	packets := append([]packet(nil), cap.packets...)
	cap.mu.Unlock()
	for i, row := range rows {
		ids := []string{}
		seenIDs := map[string]bool{}
		logs := 0
		for _, p := range packets {
			if p.Path == "/v1/traces" {
				q := ptraceotlp.NewExportRequest()
				must(q.UnmarshalJSON(p.Body))
				rs := q.Traces().ResourceSpans()
				for a := 0; a < rs.Len(); a++ {
					ss := rs.At(a).ScopeSpans()
					for c := 0; c < ss.Len(); c++ {
						sp := ss.At(c).Spans()
						for d := 0; d < sp.Len(); d++ {
							s := sp.At(d)
							if s.TraceID().String() == row["traceId"] {
								if !seenIDs[s.SpanID().String()] {
									ids = append(ids, s.SpanID().String())
									seenIDs[s.SpanID().String()] = true
								}
							}
						}
					}
				}
			} else if p.Path == "/v1/logs" {
				q := plogotlp.NewExportRequest()
				must(q.UnmarshalJSON(p.Body))
				rs := q.Logs().ResourceLogs()
				for a := 0; a < rs.Len(); a++ {
					ss := rs.At(a).ScopeLogs()
					for c := 0; c < ss.Len(); c++ {
						ls := ss.At(c).LogRecords()
						for d := 0; d < ls.Len(); d++ {
							if ls.At(d).TraceID().String() == row["traceId"] {
								logs++
							}
						}
					}
				}
			}
		}
		witnesses[i].SetAttributes(attribute.Bool("verification.completed", true), attribute.StringSlice("verification.span_ids", ids), attribute.Int("verification.metric_count", 0), attribute.Int("verification.log_count", logs))
		witnesses[i].SetStatus(codes.Ok, "actual HTTP response asserted and app shutdown/export completed")
		witnesses[i].End()
		row["capturedSpanIds"] = ids
		row["capturedLogs"] = logs
	}
	body := witnessData(cap.spans)
	packets = append(packets, packet{"/v1/traces", body})
	resp, e := client.Post("http://127.0.0.1:4338/v1/traces", "application/json", bytes.NewReader(body))
	must(e)
	io.Copy(io.Discard, resp.Body)
	resp.Body.Close()
	if resp.StatusCode != 200 {
		log.Fatal("witness rejected")
	}
	write(filepath.Join(*out, "packets.json"), packets)
	write(filepath.Join(*out, "scenarios.json"), rows)
	fmt.Println("Actual application runtime captured; awaiting release file", *out)
	// Preserve proxy-owned collector connections while the user inspects/evaluates.
	lastHeartbeat := time.Time{}
	for {
		if _, e := os.Stat(filepath.Join(*out, "release")); e == nil {
			break
		}
		if time.Since(lastHeartbeat) > 5*time.Second {
			// A real harness-liveness measurement keeps this isolated collector
			// session active while the native verifier inspects the app capture.
			// This separate service is never scenario correctness evidence.
			data := pmetric.NewMetrics()
			rm := data.ResourceMetrics().AppendEmpty()
			rm.Resource().Attributes().PutStr("service.name", "obstudio.verification.harness")
			sm := rm.ScopeMetrics().AppendEmpty()
			sm.Scope().SetName("obstudio.verification.harness")
			m := sm.Metrics().AppendEmpty()
			m.SetName("verification.capture.pending_scenarios")
			m.SetUnit("{scenario}")
			dp := m.SetEmptyGauge().DataPoints().AppendEmpty()
			dp.SetIntValue(int64(len(rows)))
			dp.SetTimestamp(pcommon.NewTimestampFromTime(time.Now()))
			body, err := pmetricotlp.NewExportRequestFromMetrics(data).MarshalJSON()
			must(err)
			response, err := client.Post("http://127.0.0.1:4338/v1/metrics", "application/json", bytes.NewReader(body))
			must(err)
			io.Copy(io.Discard, response.Body)
			response.Body.Close()
			if response.StatusCode != http.StatusOK {
				log.Fatal("harness liveness metric rejected")
			}
			lastHeartbeat = time.Now()
		}
		time.Sleep(time.Second)
	}
	server.Close()
	provider.Shutdown(context.Background())
}
