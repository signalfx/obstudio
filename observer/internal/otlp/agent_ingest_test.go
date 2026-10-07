package otlp

import (
	"bytes"
	"compress/gzip"
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/signalfx/obstudio/observer/internal/store"
	"go.opentelemetry.io/collector/pdata/ptrace"
	"go.opentelemetry.io/collector/pdata/ptrace/ptraceotlp"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
)

var testAgentRoute = AgentTraceRoute{
	ProjectID: "4dccc122-2f6d-44bb-9640-fdde5bca7b6e", AgentStreamID: "2d834bd5-04f3-4fd1-bd85-9d66066344a2",
}

type agentIngestRoundTripper func(*http.Request) (*http.Response, error)

func (f agentIngestRoundTripper) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func testAgentController(t *testing.T, realm, token, mockURL string) *SplunkTracesExportController {
	t.Helper()
	c, err := NewSplunkTracesExportController(SplunkTracesExporterConfig{Enabled: true, Realm: realm, AccessToken: token})
	if err != nil {
		t.Fatal(err)
	}
	_, generation, _ := c.AgentConnectionSnapshot()
	if !c.BindAgentTraceRoute(testAgentRoute, generation) {
		t.Fatal("could not bind test stream to cloud connection")
	}
	mock, err := url.Parse(mockURL)
	if err != nil {
		t.Fatal(err)
	}
	c.agentTracesTransport = agentIngestRoundTripper(func(r *http.Request) (*http.Response, error) {
		if r.URL.Scheme != "https" || r.URL.Host != "ingest."+realm+".observability.splunkcloud.com" || r.URL.Path != splunkTracesOTLPPath {
			t.Errorf("endpoint not derived from connection: %s", r.URL)
		}
		cloned := r.Clone(r.Context())
		copiedURL := *r.URL
		cloned.URL = &copiedURL
		cloned.URL.Scheme = mock.Scheme
		cloned.URL.Host = mock.Host
		return http.DefaultTransport.RoundTrip(cloned)
	})
	return c
}

type captureAgentExporter struct {
	mu         sync.Mutex
	routes     []AgentTraceRoute
	agentSpans int
	apmBatches int
	err        error
	rejected   int64
}

func (e *captureAgentExporter) ExportTraces(context.Context, ptrace.Traces) error {
	e.mu.Lock()
	defer e.mu.Unlock()
	e.apmBatches++
	return nil
}

func (e *captureAgentExporter) ExportAgentTraces(_ context.Context, td ptrace.Traces, route AgentTraceRoute) (ptraceotlp.ExportResponse, error) {
	e.mu.Lock()
	defer e.mu.Unlock()
	e.routes = append(e.routes, route)
	e.agentSpans += td.SpanCount()
	response := ptraceotlp.NewExportResponse()
	response.PartialSuccess().SetRejectedSpans(e.rejected)
	return response, e.err
}

func agentIngestRequest(t *testing.T, path string, proto bool) *http.Request {
	t.Helper()
	var body []byte
	var err error
	contentType := "application/json"
	if proto {
		body, err = (&ptrace.ProtoMarshaler{}).MarshalTraces(createTestSpan())
		contentType = "application/x-protobuf"
	} else {
		body, err = (&ptrace.JSONMarshaler{}).MarshalTraces(createTestSpan())
	}
	if err != nil {
		t.Fatal(err)
	}
	r := httptest.NewRequest(http.MethodPost, "http://127.0.0.1:3000"+path, bytes.NewReader(body))
	r.RemoteAddr = "127.0.0.1:54321"
	r.Header.Set("Content-Type", contentType)
	r.Header.Set("projectid", testAgentRoute.ProjectID)
	r.Header.Set("logstreamid", testAgentRoute.AgentStreamID)
	r.Header.Set("Authorization", "Bearer local-client-key")
	return r
}

func TestAgentIngestAliasesStoreAndForwardExactlyOnce(t *testing.T) {
	for _, path := range []string{"/v1/traces", "/v2/trace/otlp", "/otel/v1/traces"} {
		for _, proto := range []bool{false, true} {
			t.Run(path+map[bool]string{false: "/json", true: "/proto"}[proto], func(t *testing.T) {
				s := store.New()
				e := &captureAgentExporter{}
				h := &otlpHTTPHandler{store: s, tracesExporter: e}
				w := httptest.NewRecorder()
				h.ServeHTTP(w, agentIngestRequest(t, path, proto))
				if w.Code != http.StatusOK {
					t.Fatalf("status=%d body=%s", w.Code, w.Body.String())
				}
				if s.Stats().SpanCount != 1 || len(e.routes) != 1 || e.routes[0] != testAgentRoute || e.agentSpans != 1 || e.apmBatches != 0 {
					t.Fatalf("local/route/duplicate mismatch: stats=%+v exporter=%+v", s.Stats(), e)
				}
			})
		}
	}
}

func TestAgentHTTPRetriesRetainOneCopyButRetryUpstream(t *testing.T) {
	for _, path := range []string{"/v1/traces", "/v2/trace/otlp", "/otel/v1/traces"} {
		for _, proto := range []bool{false, true} {
			t.Run(path+map[bool]string{false: "/json", true: "/proto"}[proto], func(t *testing.T) {
				s := store.New()
				e := &captureAgentExporter{err: errors.New("upstream rejected")}
				h := &otlpHTTPHandler{store: s, tracesExporter: e}
				for attempt := range 4 {
					if attempt == 2 {
						e.err = nil
					}
					w := httptest.NewRecorder()
					h.ServeHTTP(w, agentIngestRequest(t, path, proto))
					want := http.StatusServiceUnavailable
					if attempt >= 2 {
						want = http.StatusOK
					}
					if w.Code != want || s.Stats().SpanCount != 1 || len(e.routes) != attempt+1 || e.apmBatches != 0 {
						t.Fatalf("attempt=%d status=%d spans=%d upstream=%d", attempt, w.Code, s.Stats().SpanCount, len(e.routes))
					}
				}
			})
		}
	}
}

func TestAgentIngestRejectsInvalidDestinationAndRemoteBrowserRequests(t *testing.T) {
	cases := map[string]func(*http.Request){
		"missing stream":    func(r *http.Request) { r.Header.Del("logstreamid") },
		"duplicate project": func(r *http.Request) { r.Header.Add("projectid", testAgentRoute.ProjectID) },
		"invalid UUID":      func(r *http.Request) { r.Header.Set("projectid", "project\r\nX-SF-Token: bad") },
		"no destination":    func(r *http.Request) { r.Header.Del("projectid"); r.Header.Del("logstreamid") },
		"network peer":      func(r *http.Request) { r.RemoteAddr = "192.0.2.1:1234" },
		"container bridge":  func(r *http.Request) { r.RemoteAddr = "172.18.0.2:1234" },
		"container service": func(r *http.Request) { r.Host = "obstudio:4318" },
		"browser origin":    func(r *http.Request) { r.Header.Set("Origin", "https://attacker.example") },
		"empty origin":      func(r *http.Request) { r.Header.Set("Origin", "") },
		"browser fetch":     func(r *http.Request) { r.Header.Set("Sec-Fetch-Site", "same-origin") },
		"fetch mode":        func(r *http.Request) { r.Header.Set("Sec-Fetch-Mode", "navigate") },
		"DNS rebind host":   func(r *http.Request) { r.Host = "attacker.example:3000" },
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			s := store.New()
			e := &captureAgentExporter{}
			h := &otlpHTTPHandler{store: s, tracesExporter: e}
			r := agentIngestRequest(t, "/otel/v1/traces", true)
			mutate(r)
			w := httptest.NewRecorder()
			h.ServeHTTP(w, r)
			if w.Code < 400 || s.Stats().SpanCount != 0 || len(e.routes) != 0 || e.apmBatches != 0 {
				t.Fatalf("unsafe ingest accepted: %d %+v", w.Code, e)
			}
		})
	}
}

func TestAgentIngestDoesNotAcknowledgeMissingOrFailedCloudForwarding(t *testing.T) {
	for name, exporter := range map[string]TracesExporter{"unconfigured": nil, "failed": &captureAgentExporter{err: errors.New("cloud secret-token echoed")}} {
		t.Run(name, func(t *testing.T) {
			s := store.New()
			h := &otlpHTTPHandler{store: s, tracesExporter: exporter}
			w := httptest.NewRecorder()
			h.ServeHTTP(w, agentIngestRequest(t, "/otel/v1/traces", true))
			if w.Code != http.StatusServiceUnavailable || s.Stats().SpanCount != 1 {
				t.Fatalf("status=%d stored=%d", w.Code, s.Stats().SpanCount)
			}
			if bytes.Contains(w.Body.Bytes(), []byte("secret-token")) {
				t.Fatal("cloud error leaked")
			}
		})
	}
}

func TestAgentIngestBridgeUsesReceiverPipeline(t *testing.T) {
	s := store.New()
	e := &captureAgentExporter{}
	r := &Receiver{connTracker: &ConnTracker{store: s, tracesExporter: e}}
	w := httptest.NewRecorder()
	r.HTTPHandler().ServeHTTP(w, agentIngestRequest(t, "/otel/v1/traces", true))
	if w.Code != http.StatusOK || s.Stats().SpanCount != 1 || len(e.routes) != 1 {
		t.Fatalf("bridge mismatch: status=%d exporter=%+v", w.Code, e)
	}
}

func TestAgentControllerForwardsPerRequestRoutingWithoutCallerCredentials(t *testing.T) {
	var mu sync.Mutex
	var got []AgentTraceRoute
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-SF-Token") != "studio-cloud-token" || r.Header.Get("Authorization") != "" {
			t.Errorf("auth not supplied solely by Studio")
		}
		body, _ := io.ReadAll(r.Body)
		td, err := (&ptrace.ProtoUnmarshaler{}).UnmarshalTraces(body)
		if err != nil || td.SpanCount() != 1 {
			t.Errorf("invalid forwarded OTLP: %v", err)
		}
		mu.Lock()
		got = append(got, AgentTraceRoute{r.Header.Get("projectid"), r.Header.Get("logstreamid")})
		mu.Unlock()
		w.WriteHeader(http.StatusAccepted)
	}))
	defer server.Close()
	c := testAgentController(t, "lab0", "studio-cloud-token", server.URL)
	defer c.Shutdown(context.Background())
	second := AgentTraceRoute{ProjectID: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", AgentStreamID: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"}
	_, generation, _ := c.AgentConnectionSnapshot()
	if !c.BindAgentTraceRoute(second, generation) {
		t.Fatal("could not bind second test stream")
	}
	var wg sync.WaitGroup
	for _, route := range []AgentTraceRoute{testAgentRoute, second} {
		wg.Add(1)
		go func(route AgentTraceRoute) {
			defer wg.Done()
			if _, err := c.ExportAgentTraces(context.Background(), createTestSpan(), route); err != nil {
				t.Error(err)
			}
		}(route)
	}
	wg.Wait()
	c.mu.Lock()
	oldExporter := c.exporter
	c.exporter = &stubTracesExporterRuntime{}
	c.mu.Unlock()
	oldExporter.Shutdown(context.Background())
	if err := c.ExportTraces(context.Background(), createTestSpan()); err != nil {
		t.Fatal(err)
	}
	mu.Lock()
	defer mu.Unlock()
	counts := map[AgentTraceRoute]int{}
	for _, route := range got {
		counts[route]++
	}
	if len(got) != 2 || counts[testAgentRoute] != 1 || counts[second] != 1 {
		t.Fatalf("routing/global leak: %+v", got)
	}
	if status := c.Status(); status.ExportedBatches != 3 || status.ExportedSpans != 3 {
		t.Fatalf("status=%+v", status)
	}
}

func TestAgentControllerConnectionReplacementWaitsForInflightBatch(t *testing.T) {
	entered := make(chan struct{})
	release := make(chan struct{})
	done := make(chan error, 1)
	old := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-SF-Token") != "old-token" {
			t.Error("mixed old endpoint and new credential")
		}
		close(entered)
		<-release
		w.WriteHeader(http.StatusAccepted)
	}))
	defer old.Close()
	var newCalls atomic.Int32
	next := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-SF-Token") != "new-token" {
			t.Error("mixed new endpoint and old credential")
		}
		newCalls.Add(1)
		w.WriteHeader(http.StatusAccepted)
	}))
	defer next.Close()
	c := testAgentController(t, "lab0", "old-token", old.URL)
	c.agentTracesTransport = agentIngestRoundTripper(func(r *http.Request) (*http.Response, error) {
		mockURL := old.URL
		if r.URL.Host == "ingest.us1.observability.splunkcloud.com" {
			mockURL = next.URL
		} else if r.URL.Host != "ingest.lab0.observability.splunkcloud.com" {
			t.Errorf("unexpected cloud host: %s", r.URL.Host)
		}
		mock, _ := url.Parse(mockURL)
		cloned := r.Clone(r.Context())
		copiedURL := *r.URL
		cloned.URL = &copiedURL
		cloned.URL.Scheme = mock.Scheme
		cloned.URL.Host = mock.Host
		return http.DefaultTransport.RoundTrip(cloned)
	})
	defer c.Shutdown(context.Background())
	go func() {
		_, err := c.ExportAgentTraces(context.Background(), createTestSpan(), testAgentRoute)
		done <- err
	}()
	<-entered
	reconfigured := make(chan error, 1)
	go func() {
		reconfigured <- c.Configure(SplunkTracesExporterConfig{Enabled: true, Realm: "us1", AccessToken: "new-token"})
	}()
	select {
	case err := <-reconfigured:
		t.Fatalf("connection replaced during export: %v", err)
	case <-time.After(50 * time.Millisecond):
	}
	close(release)
	if err := <-done; err != nil {
		t.Fatal(err)
	}
	if err := <-reconfigured; err != nil {
		t.Fatal(err)
	}
	if _, err := c.ExportAgentTraces(context.Background(), createTestSpan(), testAgentRoute); err == nil {
		t.Fatal("previous connection's stream was forwarded after switching realms")
	}
	_, generation, _ := c.AgentConnectionSnapshot()
	if !c.BindAgentTraceRoute(testAgentRoute, generation) {
		t.Fatal("new cloud connection could not resolve stream")
	}
	if _, err := c.ExportAgentTraces(context.Background(), createTestSpan(), testAgentRoute); err != nil {
		t.Fatal(err)
	}
	if newCalls.Load() != 1 {
		t.Fatalf("new calls=%d", newCalls.Load())
	}
	if err := c.Configure(SplunkTracesExporterConfig{}); err != nil {
		t.Fatal(err)
	}
	if _, err := c.ExportAgentTraces(context.Background(), createTestSpan(), testAgentRoute); err == nil {
		t.Fatal("disabled connection reported success")
	}
}

func TestAgentControllerDoesNotFollowCredentialLeakingRedirect(t *testing.T) {
	var targetCalls atomic.Int32
	target := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { targetCalls.Add(1); w.WriteHeader(http.StatusOK) }))
	defer target.Close()
	redirect := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, target.URL, http.StatusTemporaryRedirect)
	}))
	defer redirect.Close()
	c := testAgentController(t, "lab0", "cloud-token", redirect.URL)
	defer c.Shutdown(context.Background())
	if _, err := c.ExportAgentTraces(context.Background(), createTestSpan(), testAgentRoute); err == nil {
		t.Fatal("redirect was acknowledged")
	}
	if targetCalls.Load() != 0 {
		t.Fatal("redirect followed with cloud credentials")
	}
}

func TestAgentGRPCIngestPreservesRequestRouting(t *testing.T) {
	s := store.New()
	e := &captureAgentExporter{rejected: 1}
	r, err := StartReceiver(context.Background(), s, "127.0.0.1:0", "127.0.0.1:0", WithTracesExporter(e))
	if err != nil {
		t.Fatal(err)
	}
	defer r.Shutdown(context.Background())
	conn, err := grpc.NewClient(r.connTracker.grpcLn.Addr().String(), grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	ctx = metadata.AppendToOutgoingContext(ctx, "projectid", testAgentRoute.ProjectID, "logstreamid", testAgentRoute.AgentStreamID)
	response, err := ptraceotlp.NewGRPCClient(conn).Export(ctx, ptraceotlp.NewExportRequestFromTraces(createTestSpan()))
	if err != nil {
		t.Fatal(err)
	}
	if response.PartialSuccess().RejectedSpans() != 1 {
		t.Fatal("gRPC partial rejection was discarded")
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	if s.Stats().SpanCount != 1 || len(e.routes) != 1 || e.routes[0] != testAgentRoute || e.apmBatches != 0 {
		t.Fatalf("gRPC destination lost or duplicated: %+v", e)
	}
}

func TestAgentGRPCRetriesRetainOneCopyButRetryUpstream(t *testing.T) {
	s := store.New()
	e := &captureAgentExporter{err: errors.New("upstream rejected")}
	r, err := StartReceiver(context.Background(), s, "127.0.0.1:0", "127.0.0.1:0", WithTracesExporter(e))
	if err != nil {
		t.Fatal(err)
	}
	defer r.Shutdown(context.Background())
	conn, err := grpc.NewClient(r.connTracker.grpcLn.Addr().String(), grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	ctx = metadata.AppendToOutgoingContext(ctx, "projectid", testAgentRoute.ProjectID, "logstreamid", testAgentRoute.AgentStreamID)
	client := ptraceotlp.NewGRPCClient(conn)
	request := ptraceotlp.NewExportRequestFromTraces(createTestSpan())
	for attempt := range 4 {
		if attempt == 2 {
			e.mu.Lock()
			e.err = nil
			e.mu.Unlock()
		}
		_, err := client.Export(ctx, request)
		if attempt < 2 && status.Code(err) != codes.Unavailable || attempt >= 2 && err != nil {
			t.Fatalf("attempt=%d unexpected upstream outcome: %v", attempt, err)
		}
		e.mu.Lock()
		attempts, apm := len(e.routes), e.apmBatches
		e.mu.Unlock()
		if s.Stats().SpanCount != 1 || attempts != attempt+1 || apm != 0 {
			t.Fatalf("attempt=%d spans=%d upstream=%d", attempt, s.Stats().SpanCount, attempts)
		}
	}
}

func TestAgentIngestPreservesCloudPartialSuccessAndAcceptedSpanCounts(t *testing.T) {
	for _, cloudProto := range []bool{false, true} {
		for _, clientProto := range []bool{false, true} {
			t.Run(map[bool]string{false: "cloud-json", true: "cloud-proto"}[cloudProto]+map[bool]string{false: "/client-json", true: "/client-proto"}[clientProto], func(t *testing.T) {
				cloudResponse := ptraceotlp.NewExportResponse()
				cloudResponse.PartialSuccess().SetRejectedSpans(1)
				cloudResponse.PartialSuccess().SetErrorMessage("invalid span; secret-cloud-token")
				var cloudBody []byte
				var err error
				cloudType := "application/json"
				if cloudProto {
					cloudType = "application/x-protobuf"
					cloudBody, err = cloudResponse.MarshalProto()
				} else {
					cloudBody, err = cloudResponse.MarshalJSON()
				}
				if err != nil {
					t.Fatal(err)
				}
				server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
					w.Header().Set("Content-Type", cloudType)
					_, _ = w.Write(cloudBody)
				}))
				defer server.Close()
				controller := testAgentController(t, "lab0", "secret-cloud-token", server.URL)
				defer controller.Shutdown(context.Background())
				td := createTestSpan()
				spans := td.ResourceSpans().At(0).ScopeSpans().At(0).Spans()
				spans.At(0).CopyTo(spans.AppendEmpty())
				var requestBody []byte
				if clientProto {
					requestBody, err = (&ptrace.ProtoMarshaler{}).MarshalTraces(td)
				} else {
					requestBody, err = (&ptrace.JSONMarshaler{}).MarshalTraces(td)
				}
				if err != nil {
					t.Fatal(err)
				}
				r := agentIngestRequest(t, "/otel/v1/traces", clientProto)
				r.Body = io.NopCloser(bytes.NewReader(requestBody))
				h := &otlpHTTPHandler{store: store.New(), tracesExporter: controller}
				w := httptest.NewRecorder()
				h.ServeHTTP(w, r)
				if w.Code != http.StatusOK {
					t.Fatalf("partial success became retryable error: %d %s", w.Code, w.Body.String())
				}
				response := ptraceotlp.NewExportResponse()
				if clientProto {
					if w.Header().Get("Content-Type") != "application/x-protobuf" {
						t.Fatal("response encoding mismatch")
					}
					err = response.UnmarshalProto(w.Body.Bytes())
				} else {
					err = response.UnmarshalJSON(w.Body.Bytes())
				}
				if err != nil || response.PartialSuccess().RejectedSpans() != 1 || bytes.Contains(w.Body.Bytes(), []byte("secret-cloud-token")) {
					t.Fatalf("partial success lost/leaked: %+v %v", response, err)
				}
				status := controller.Status()
				if status.ExportedSpans != 1 || status.ExportedBatches != 0 || status.FailedBatches != 1 || status.LastExport == nil || status.LastExport.Success {
					t.Fatalf("full acceptance falsely recorded: %+v", status)
				}
			})
		}
	}
}

func TestAgentControllerRejectsUnexpectedSuccessfulCloudResponses(t *testing.T) {
	for name, response := range map[string]struct{ contentType, body string }{
		"HTML":               {"text/html", "<html>login</html>"},
		"non-OTLP JSON":      {"application/json", `{"success":true}`},
		"JSON null":          {"application/json", `null`},
		"AO rejection":       {"application/json", `{"valid":0,"invalid":{"bad_span":["private-content"]}}`},
		"AO mixed rejection": {"application/json", `{"valid":1,"invalid":{"bad_span":["private-content"]}}`},
		"AO excess count":    {"application/json", `{"valid":2,"invalid":{}}`},
		"AO null count":      {"application/json", `{"valid":null,"invalid":{}}`},
		"AO boolean count":   {"application/json", `{"valid":true,"invalid":{}}`},
		"AO missing count":   {"application/json", `{"invalid":{}}`},
		"AO invalid array":   {"application/json", `{"valid":1,"invalid":[]}`},
		"AO extra field":     {"application/json", `{"valid":1,"invalid":{},"success":true}`},
		"invalid protobuf":   {"application/x-protobuf", "not protobuf"},
		"negative rejected":  {"application/json", `{"partialSuccess":{"rejectedSpans":"-1"}}`},
		"excess rejected":    {"application/json", `{"partialSuccess":{"rejectedSpans":"2"}}`},
	} {
		t.Run(name, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
				w.Header().Set("Content-Type", response.contentType)
				_, _ = io.WriteString(w, response.body)
			}))
			defer server.Close()
			controller := testAgentController(t, "lab0", "cloud-token", server.URL)
			defer controller.Shutdown(context.Background())
			if _, err := controller.ExportAgentTraces(context.Background(), createTestSpan(), testAgentRoute); err == nil {
				t.Fatal("unexpected response reported full acceptance")
			}
			status := controller.Status()
			if status.ExportedSpans != 0 || status.ExportedBatches != 0 || status.FailedBatches != 1 || status.LastExport.Success {
				t.Fatalf("false success status: %+v", status)
			}
		})
	}
}

func TestAgentControllerAcceptsCompleteSplunkJSONAcknowledgement(t *testing.T) {
	for _, body := range []string{`{"valid":1}`, `{"valid":1,"invalid":{}}`, `{"valid":1,"invalid":null}`} {
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
			w.Header().Set("Content-Type", "application/json; charset=utf-8")
			_, _ = io.WriteString(w, body)
		}))
		controller := testAgentController(t, "lab0", "cloud-token", server.URL)
		response, err := controller.ExportAgentTraces(context.Background(), createTestSpan(), testAgentRoute)
		if err != nil || response.PartialSuccess().RejectedSpans() != 0 {
			t.Fatalf("complete Splunk acknowledgement rejected: %v", err)
		}
		status := controller.Status()
		if status.ExportedSpans != 1 || status.ExportedBatches != 1 || status.FailedBatches != 0 || !status.LastExport.Success {
			t.Fatalf("complete acknowledgement not recorded: %+v", status)
		}
		controller.Shutdown(context.Background())
		server.Close()
	}
}

func TestAgentControllerRejectsCustomUpstreamWithoutChangingOrdinaryAPM(t *testing.T) {
	var calls atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		if r.Header.Get("projectid") != "" || r.Header.Get("logstreamid") != "" {
			t.Error("AO sent to custom endpoint")
		}
		w.WriteHeader(http.StatusAccepted)
	}))
	defer server.Close()
	c, err := NewSplunkTracesExportController(SplunkTracesExporterConfig{Enabled: true, Realm: "lab0", Endpoint: server.URL, AccessToken: "secret-token"})
	if err != nil {
		t.Fatal(err)
	}
	defer c.Shutdown(context.Background())
	c.agentTracesTransport = agentIngestRoundTripper(func(*http.Request) (*http.Response, error) {
		t.Fatal("custom AO endpoint was contacted")
		return nil, errors.New("unexpected call")
	})
	if err := c.ExportTraces(context.Background(), createTestSpan()); err != nil {
		t.Fatal("ordinary APM override stopped working", err)
	}
	if _, err := c.ExportAgentTraces(context.Background(), createTestSpan(), testAgentRoute); err == nil {
		t.Fatal("AO custom endpoint accepted")
	}
	if calls.Load() != 1 {
		t.Fatalf("cloud calls=%d", calls.Load())
	}
	status := c.Status()
	if status.ExportedSpans != 1 || status.FailedBatches != 1 || status.LastExport.Success || bytes.Contains([]byte(status.LastExport.Error), []byte("secret-token")) {
		t.Fatalf("false acceptance or leak: %+v", status)
	}
}

func TestAgentControllerRequiresRealmAndServerHeldToken(t *testing.T) {
	for name, config := range map[string]SplunkTracesExporterConfig{
		"missing realm": {Enabled: true, AccessToken: "secret-token"},
		"invalid realm": {Enabled: true, Realm: "lab0/attacker", AccessToken: "secret-token"},
		"missing token": {Enabled: true, Realm: "lab0"},
	} {
		t.Run(name, func(t *testing.T) {
			c := &SplunkTracesExportController{config: config, exporter: &stubTracesExporterRuntime{}, agentTracesTransport: agentIngestRoundTripper(func(*http.Request) (*http.Response, error) {
				t.Fatal("invalid connection reached transport")
				return nil, errors.New("unexpected call")
			})}
			if _, err := c.ExportAgentTraces(context.Background(), createTestSpan(), testAgentRoute); err == nil {
				t.Fatal("invalid cloud connection acknowledged")
			}
		})
	}
}

func TestAgentCloudErrorRetainsOnlyBoundedSanitizedStandardJSONDetails(t *testing.T) {
	response := &http.Response{StatusCode: http.StatusForbidden, Header: http.Header{"Content-Type": []string{"application/json"}}, Body: io.NopCloser(bytes.NewBufferString(`{"code":"AO_FORBIDDEN","message":"wrong scope secret-cloud-token","detail":"Bearer other.jwt.secret denied","headers":{"Authorization":"do-not-reflect"},"payload":"raw-private-content"}`))}
	err := agentTraceCloudError(response, "secret-cloud-token")
	message := err.Error()
	for _, secret := range []string{"secret-cloud-token", "other.jwt.secret", "do-not-reflect", "raw-private-content"} {
		if bytes.Contains([]byte(message), []byte(secret)) {
			t.Fatalf("diagnostic leaked %s", secret)
		}
	}
	for _, want := range []string{"HTTP 403", "code=AO_FORBIDDEN", "wrong scope [REDACTED]", "Bearer [REDACTED] denied"} {
		if !bytes.Contains([]byte(message), []byte(want)) {
			t.Fatalf("missing safe diagnostic %q: %s", want, message)
		}
	}
	for name, body := range map[string]string{"HTML": "<html>secret-cloud-token private</html>", "oversized": string(bytes.Repeat([]byte("x"), 4097)), "non-standard": `{"headers":"private"}`} {
		t.Run(name, func(t *testing.T) {
			contentType := "application/json"
			if name == "HTML" {
				contentType = "text/html"
			}
			response := &http.Response{StatusCode: http.StatusForbidden, Header: http.Header{"Content-Type": []string{contentType}}, Body: io.NopCloser(bytes.NewBufferString(body))}
			message := agentTraceCloudError(response, "secret-cloud-token").Error()
			if len(message) > 256 || bytes.Contains([]byte(message), []byte("private")) || bytes.Contains([]byte(message), []byte("secret-cloud-token")) {
				t.Fatalf("unsafe error response reflected: %s", message)
			}
		})
	}
}

func TestInvalidAgentTraceResponseDescribesShapeWithoutReflectingSecrets(t *testing.T) {
	for _, tc := range []struct{ name, contentType, body, want string }{
		{"literal", "text/plain; charset=utf-8", "OK\n", "shape literal-OK"},
		{"HTML", "text/html", "<html>secret-cloud-token private-content</html>", "shape unrecognized"},
		{"JSON", "application/json", `{"message":"secret-cloud-token Bearer private.jwt.secret denied","payload":"private-content"}`, "message=[REDACTED] Bearer [REDACTED] denied"},
		{"header", "private-content", "secret-cloud-token", `content-type "other"`},
	} {
		t.Run(tc.name, func(t *testing.T) {
			response := &http.Response{StatusCode: http.StatusOK, Header: http.Header{"Content-Type": {tc.contentType}}}
			message := invalidAgentTraceResponse(response, []byte(tc.body), "secret-cloud-token").Error()
			if !strings.Contains(message, tc.want) || !strings.Contains(message, "HTTP 200") {
				t.Fatalf("missing safe response shape: %s", message)
			}
			for _, secret := range []string{"secret-cloud-token", "private.jwt.secret", "private-content"} {
				if strings.Contains(message, secret) {
					t.Fatalf("response diagnostic leaked %q: %s", secret, message)
				}
			}
		})
	}
}

func TestAgentHTTPFailureReturnsGenericBodyButRecordsSafeCloudReason(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusForbidden)
		_, _ = io.WriteString(w, `{"code":"AO_FORBIDDEN","detail":"missing Agent Observability permission secret-cloud-token"}`)
	}))
	defer server.Close()
	c := testAgentController(t, "lab0", "secret-cloud-token", server.URL)
	defer c.Shutdown(context.Background())
	h := &otlpHTTPHandler{store: store.New(), tracesExporter: c}
	w := httptest.NewRecorder()
	h.ServeHTTP(w, agentIngestRequest(t, "/otel/v1/traces", true))
	if w.Code != http.StatusServiceUnavailable || bytes.Contains(w.Body.Bytes(), []byte("AO_FORBIDDEN")) || bytes.Contains(w.Body.Bytes(), []byte("secret-cloud-token")) {
		t.Fatal("cloud diagnostics escaped generic ingest error")
	}
	status := c.Status()
	if status.LastExport == nil || !bytes.Contains([]byte(status.LastExport.Error), []byte("code=AO_FORBIDDEN")) || bytes.Contains([]byte(status.LastExport.Error), []byte("secret-cloud-token")) {
		t.Fatalf("safe diagnosis missing: %+v", status)
	}
}

func TestReadBodyLimitsDecompressedOTLPRequests(t *testing.T) {
	var compressed bytes.Buffer
	z := gzip.NewWriter(&compressed)
	if _, err := z.Write(bytes.Repeat([]byte("x"), maxOTLPHTTPBodyBytes+1)); err != nil {
		t.Fatal(err)
	}
	if err := z.Close(); err != nil {
		t.Fatal(err)
	}
	r := httptest.NewRequest(http.MethodPost, "/v1/traces", &compressed)
	r.Header.Set("Content-Encoding", "gzip")
	if _, err := readBody(r, true); err == nil {
		t.Fatal("oversized decompressed body accepted")
	}
}

func TestReadBodyPreservesOrdinaryOTLPPayloadSize(t *testing.T) {
	payload := bytes.Repeat([]byte("x"), maxOTLPHTTPBodyBytes+1)
	r := httptest.NewRequest(http.MethodPost, "/v1/traces", bytes.NewReader(payload))
	body, err := readBody(r, false)
	if err != nil || !bytes.Equal(body, payload) {
		t.Fatalf("ordinary OTLP payload was capped: length=%d error=%v", len(body), err)
	}
}
