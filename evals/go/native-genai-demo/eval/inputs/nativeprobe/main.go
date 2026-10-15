// nativeprobe is an external local-only test controller, not application runtime code.
package main

import (
	"bytes"
	"compress/gzip"
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	collectormetric "go.opentelemetry.io/proto/otlp/collector/metrics/v1"
	collectortrace "go.opentelemetry.io/proto/otlp/collector/trace/v1"
	common "go.opentelemetry.io/proto/otlp/common/v1"
	metricspb "go.opentelemetry.io/proto/otlp/metrics/v1"
	"google.golang.org/protobuf/proto"
)

type record = map[string]any
type server struct {
	mu                      sync.Mutex
	resources               string
	reject                  bool
	project, stream         record
	native, models, journal []record
	responseIDs             map[string]string
}

func uuid() string {
	var b [16]byte
	if _, e := rand.Read(b[:]); e != nil {
		panic(e)
	}
	b[6] = (b[6] & 15) | 64
	b[8] = (b[8] & 63) | 128
	v := hex.EncodeToString(b[:])
	return v[:8] + "-" + v[8:12] + "-" + v[12:16] + "-" + v[16:20] + "-" + v[20:]
}
func write(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}
func (s *server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	s.mu.Lock()
	defer s.mu.Unlock()
	body, e := io.ReadAll(io.LimitReader(r.Body, 8*1024*1024+1))
	if e != nil || len(body) > 8*1024*1024 {
		write(w, 400, record{"error": "body"})
		return
	}
	if r.URL.Path == "/model" {
		var input record
		if json.Unmarshal(body, &input) != nil {
			write(w, 400, record{})
			return
		}
		s.models = append(s.models, input)
		if input["scenario"] == "provider_error" {
			write(w, 503, record{"error": "provider_unavailable"})
			return
		}
		id := "fixture-response-" + uuid()
		s.responseIDs[fmt.Sprint(input["request_id"])] = id
		write(w, 200, record{"id": id, "model": input["model"], "finish_reason": "stop", "message": record{"role": "assistant", "content": "Your order is shipped; used 1 policy document."}, "usage": record{"input_tokens": 11, "output_tokens": 7}})
		return
	}
	if strings.HasPrefix(r.URL.Path, "/ao/api/projects") {
		var input any
		if len(body) > 0 {
			_ = json.Unmarshal(body, &input)
		}
		entry := record{"method": r.Method, "path": r.URL.Path, "query": r.URL.RawQuery, "body": input}
		s.journal = append(s.journal, entry)
		status, payload := s.resource(r, input)
		entry["status"] = status
		write(w, status, payload)
		return
	}
	if r.URL.Path == "/v1/traces" || r.URL.Path == "/v1/metrics" || r.URL.Path == "/v1/logs" {
		wire := body
		if r.Header.Get("Content-Encoding") == "gzip" {
			reader, e := gzip.NewReader(bytes.NewReader(body))
			if e != nil {
				write(w, 400, record{})
				return
			}
			wire, e = io.ReadAll(io.LimitReader(reader, 8*1024*1024+1))
			_ = reader.Close()
			if e != nil || len(wire) > 8*1024*1024 {
				write(w, 400, record{})
				return
			}
		}
		rows, e := decode(r.URL.Path, wire)
		status := 200
		if e != nil {
			status = 400
		}
		if s.reject && r.URL.Path == "/v1/traces" {
			status = 400
		}
		digest := sha256.Sum256(body)
		headers := record{}
		for key, values := range r.Header {
			headers[strings.ToLower(key)] = strings.Join(values, ",")
		}
		s.native = append(s.native, record{"path": r.URL.Path, "status": status, "headers": headers, "body_sha256": hex.EncodeToString(digest[:]), "body_base64": body, "records": rows})
		w.Header().Set("Content-Type", "application/x-protobuf")
		w.WriteHeader(status)
		return
	}
	write(w, 404, record{})
}
func (s *server) resource(r *http.Request, input any) (int, any) {
	if r.Header.Get("X-SF-Token") != "local-gateway" {
		return 401, record{"error": "public_marker_required"}
	}
	if s.resources == "auth" {
		return 403, record{"error": "fixture_forbidden"}
	}
	path := strings.TrimPrefix(r.URL.Path, "/ao/api/projects")
	p, _ := input.(map[string]any)
	if path == "/all" && r.Method == "GET" && r.URL.Query().Get("type") == "gen_ai" {
		rows := []record{}
		if s.project != nil {
			rows = append(rows, s.project)
		}
		return 200, rows
	}
	if path == "" && r.Method == "POST" {
		if p["name"] != "fixture-project" || p["type"] != "gen_ai" || p["create_example_templates"] != false {
			return 400, record{}
		}
		if s.project != nil {
			return 409, record{}
		}
		s.project = record{"id": uuid(), "name": "fixture-project", "type": "gen_ai"}
		return 201, s.project
	}
	if s.project == nil {
		return 404, record{}
	}
	prefix := "/" + fmt.Sprint(s.project["id"])
	if path == prefix && r.Method == "GET" {
		return 200, s.project
	}
	if path == prefix+"/log_streams/paginated" && r.Method == "GET" {
		if r.URL.Query().Get("include_counts") != "false" || r.URL.Query().Get("limit") != "100" || r.URL.Query().Get("starting_token") != "0" {
			return 400, record{}
		}
		rows := []record{}
		if s.stream != nil {
			rows = append(rows, s.stream)
		}
		return 200, record{"log_streams": rows, "paginated": false, "next_starting_token": nil}
	}
	if path == prefix+"/log_streams" && r.Method == "POST" {
		if p["name"] != "fixture-agent" {
			return 400, record{}
		}
		if s.stream != nil {
			return 409, record{}
		}
		s.stream = record{"id": uuid(), "name": "fixture-agent", "project_id": s.project["id"]}
		return 201, s.stream
	}
	if s.stream != nil && path == prefix+"/log_streams/"+fmt.Sprint(s.stream["id"]) && r.Method == "GET" {
		return 200, s.stream
	}
	return 404, record{}
}
func value(v *common.AnyValue) any {
	if v == nil {
		return nil
	}
	switch x := v.Value.(type) {
	case *common.AnyValue_StringValue:
		return x.StringValue
	case *common.AnyValue_BoolValue:
		return x.BoolValue
	case *common.AnyValue_IntValue:
		return x.IntValue
	case *common.AnyValue_DoubleValue:
		return x.DoubleValue
	case *common.AnyValue_ArrayValue:
		out := []any{}
		for _, item := range x.ArrayValue.Values {
			out = append(out, value(item))
		}
		return out
	case *common.AnyValue_KvlistValue:
		return attributes(x.KvlistValue.Values)
	case *common.AnyValue_BytesValue:
		return hex.EncodeToString(x.BytesValue)
	}
	return nil
}
func attributes(attrs []*common.KeyValue) record {
	out := record{}
	for _, a := range attrs {
		out[a.Key] = value(a.Value)
	}
	return out
}
func decode(path string, wire []byte) ([]record, error) {
	rows := []record{}
	if path == "/v1/traces" {
		request := &collectortrace.ExportTraceServiceRequest{}
		if e := proto.Unmarshal(wire, request); e != nil {
			return nil, e
		}
		for _, resource := range request.ResourceSpans {
			for _, scope := range resource.ScopeSpans {
				for _, span := range scope.Spans {
					events := []record{}
					for _, event := range span.Events {
						events = append(events, record{"name": event.Name, "attributes": attributes(event.Attributes), "time_unix_nano": strconv.FormatUint(event.TimeUnixNano, 10)})
					}
					links := []record{}
					for _, link := range span.Links {
						links = append(links, record{"trace_id": hex.EncodeToString(link.TraceId), "span_id": hex.EncodeToString(link.SpanId), "attributes": attributes(link.Attributes), "flags": link.Flags})
					}
					row := record{"name": span.Name, "trace_id": hex.EncodeToString(span.TraceId), "span_id": hex.EncodeToString(span.SpanId), "parent_span_id": hex.EncodeToString(span.ParentSpanId), "kind": int32(span.Kind), "attributes": attributes(span.Attributes), "resource": attributes(resource.Resource.GetAttributes()), "scope": scope.Scope.GetName(), "start_time_unix_nano": strconv.FormatUint(span.StartTimeUnixNano, 10), "end_time_unix_nano": strconv.FormatUint(span.EndTimeUnixNano, 10), "events": events, "links": links, "flags": span.Flags, "status": record{"code": int32(span.Status.GetCode()), "message": span.Status.GetMessage()}}
					rows = append(rows, row)
				}
			}
		}
		return rows, nil
	}
	if path == "/v1/metrics" {
		request := &collectormetric.ExportMetricsServiceRequest{}
		if e := proto.Unmarshal(wire, request); e != nil {
			return nil, e
		}
		for _, resource := range request.ResourceMetrics {
			for _, scope := range resource.ScopeMetrics {
				for _, metric := range scope.Metrics {
					base := func(attrs []*common.KeyValue) record {
						return record{"name": metric.Name, "unit": metric.Unit, "attributes": attributes(attrs), "resource": attributes(resource.Resource.GetAttributes()), "scope": scope.Scope.GetName()}
					}
					switch data := metric.Data.(type) {
					case *metricspb.Metric_Sum:
						for _, point := range data.Sum.DataPoints {
							row := base(point.Attributes)
							row["type"] = "sum"
							row["monotonic"] = data.Sum.IsMonotonic
							row["value"] = number(point)
							rows = append(rows, row)
						}
					case *metricspb.Metric_Gauge:
						for _, point := range data.Gauge.DataPoints {
							row := base(point.Attributes)
							row["type"] = "gauge"
							row["value"] = number(point)
							rows = append(rows, row)
						}
					case *metricspb.Metric_Histogram:
						for _, point := range data.Histogram.DataPoints {
							row := base(point.Attributes)
							row["type"] = "histogram"
							row["count"] = point.Count
							row["sum"] = point.GetSum()
							rows = append(rows, row)
						}
					case *metricspb.Metric_ExponentialHistogram:
						for _, point := range data.ExponentialHistogram.DataPoints {
							row := base(point.Attributes)
							row["type"] = "exponential_histogram"
							row["count"] = point.Count
							row["sum"] = point.GetSum()
							rows = append(rows, row)
						}
					}
				}
			}
		}
		return rows, nil
	}
	return nil, errors.New("no application logging stack; unexpected log export")
}
func number(point *metricspb.NumberDataPoint) any {
	switch n := point.Value.(type) {
	case *metricspb.NumberDataPoint_AsInt:
		return n.AsInt
	case *metricspb.NumberDataPoint_AsDouble:
		return n.AsDouble
	}
	return nil
}
func cleanEnvironment(origin string) []string {
	env := []string{}
	for _, item := range os.Environ() {
		key := strings.SplitN(item, "=", 2)[0]
		upper := strings.ToUpper(key)
		if strings.HasPrefix(upper, "OTEL_") || strings.HasPrefix(upper, "SPLUNK_") || strings.HasPrefix(upper, "GALILEO_") || upper == "STUDIO_API_ORIGIN" || strings.HasSuffix(upper, "_PROXY") {
			continue
		}
		env = append(env, item)
	}
	return append(env, "OTEL_EXPORTER_OTLP_ENDPOINT="+origin, "OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf", "OTEL_EXPORTER_OTLP_HEADERS=x-fixture-header=keep,x-precedence=generic,projectid=stale-global-project,logstreamid=stale-global-stream,agentstreamid=stale-global-public", "OTEL_EXPORTER_OTLP_TRACES_HEADERS=x-fixture-header=keep,x-precedence=trace,projectid=stale-project,logstreamid=stale-stream,agentstreamid=stale-public", "STUDIO_API_ORIGIN="+origin, "SPLUNK_AO_PROJECT=fixture-project", "SPLUNK_AO_AGENT_STREAM=fixture-agent")
}
func spansFrom(run record) []record {
	rows := []record{}
	for _, request := range run["native_requests"].([]record) {
		if request["path"] == "/v1/traces" {
			rows = append(rows, request["records"].([]record)...)
		}
	}
	return rows
}
func graph(rows []record) []string {
	failures := []string{}
	if len(rows) != 14 {
		failures = append(failures, fmt.Sprintf("expected14spans got%d", len(rows)))
	}
	expected := map[string]map[string]int{"turn-1": {"invoke_agent": 1, "retrieval": 1, "execute_tool": 1, "chat": 1}, "turn-2": {"invoke_agent": 1, "retrieval": 1, "execute_tool": 1}, "turn-3": {"invoke_agent": 1, "retrieval": 1, "execute_tool": 1, "chat": 1}, "turn-4": {"invoke_agent": 1, "retrieval": 1, "execute_tool": 1}}
	byID := map[string]record{}
	traces := map[string]string{}
	counts := map[string]map[string]int{}
	roots := map[string]int{}
	for _, row := range rows {
		attrs := row["attributes"].(record)
		request := fmt.Sprint(attrs["app.request_id"])
		operation := fmt.Sprint(attrs["gen_ai.operation.name"])
		key := fmt.Sprint(row["trace_id"]) + ":" + fmt.Sprint(row["span_id"])
		if len(fmt.Sprint(row["trace_id"])) != 32 || len(fmt.Sprint(row["span_id"])) != 16 || strings.Trim(fmt.Sprint(row["trace_id"]), "0") == "" || strings.Trim(fmt.Sprint(row["span_id"]), "0") == "" {
			failures = append(failures, "invalid trace/span identity")
		}
		if byID[key] != nil {
			failures = append(failures, "duplicate span identity")
		}
		byID[key] = row
		trace := fmt.Sprint(row["trace_id"])
		if prior, ok := traces[request]; ok && prior != trace {
			failures = append(failures, "split request trace")
		}
		traces[request] = trace
		if counts[request] == nil {
			counts[request] = map[string]int{}
		}
		counts[request][operation]++
		parent := fmt.Sprint(row["parent_span_id"])
		if parent == "" {
			roots[request]++
			if operation != "invoke_agent" {
				failures = append(failures, "nonagent root")
			}
		}
		start, _ := strconv.ParseUint(fmt.Sprint(row["start_time_unix_nano"]), 10, 64)
		end, _ := strconv.ParseUint(fmt.Sprint(row["end_time_unix_nano"]), 10, 64)
		if start == 0 || end <= start {
			failures = append(failures, "unclosed/nonpositive interval")
		}
		wantKind := int32(1)
		if operation == "chat" {
			wantKind = 3
		}
		if row["kind"] != wantKind {
			failures = append(failures, "wrong creation kind")
		}
	}
	distinct := map[string]bool{}
	for request, trace := range traces {
		if distinct[trace] {
			failures = append(failures, "crossrequest shared trace")
		}
		distinct[trace] = true
		if roots[request] != 1 {
			failures = append(failures, "request must have one root")
		}
	}
	for request, want := range expected {
		encoded, _ := json.Marshal(counts[request])
		desired, _ := json.Marshal(want)
		if string(encoded) != string(desired) {
			failures = append(failures, "missing/extra source operations for "+request)
		}
	}
	for _, row := range rows {
		parentID := fmt.Sprint(row["parent_span_id"])
		if parentID == "" {
			continue
		}
		parent := byID[fmt.Sprint(row["trace_id"])+":"+parentID]
		if parent == nil {
			failures = append(failures, "orphan parent")
			continue
		}
		attrs := row["attributes"].(record)
		pa := parent["attributes"].(record)
		if attrs["app.request_id"] != pa["app.request_id"] || pa["gen_ai.operation.name"] != "invoke_agent" {
			failures = append(failures, "incorrect source parent")
		}
		start, _ := strconv.ParseUint(fmt.Sprint(row["start_time_unix_nano"]), 10, 64)
		end, _ := strconv.ParseUint(fmt.Sprint(row["end_time_unix_nano"]), 10, 64)
		ps, _ := strconv.ParseUint(fmt.Sprint(parent["start_time_unix_nano"]), 10, 64)
		pe, _ := strconv.ParseUint(fmt.Sprint(parent["end_time_unix_nano"]), 10, 64)
		if start < ps || end > pe {
			failures = append(failures, "child outside synchronous parent")
		}
	}
	return failures
}
func validate(run record, expect string, project, stream record) []string {
	failures := []string{}
	outcomes, _ := run["business_outcomes"].([]record)
	if len(outcomes) != 4 {
		failures = append(failures, "missing business outcomes")
	}
	for i, want := range []string{"", "tool_unavailable", "provider_unavailable", "cancelled"} {
		if i >= len(outcomes) {
			break
		}
		got := fmt.Sprint(outcomes[i]["error_type"])
		if want == "" {
			if outcomes[i]["result"] != "Your order is shipped; used 1 policy document." {
				failures = append(failures, "business result changed")
			}
		} else if got != want {
			failures = append(failures, "business error changed")
		}
	}
	if len(run["model_requests"].([]record)) != 2 {
		failures = append(failures, "expected2 actualHTTP model calls")
	}
	requests := run["native_requests"].([]record)
	if expect == "baseline" {
		if len(requests) != 0 || len(run["resource_requests"].([]record)) != 0 {
			failures = append(failures, "baseline unexpectedly instrumented")
		}
		return failures
	}
	if expect != "native" {
		return failures
	}
	failures = append(failures, graph(spansFrom(run))...)
	for _, request := range requests {
		if request["status"] != 200 {
			failures = append(failures, "native export rejected")
		}
		headers := request["headers"].(record)
		if headers["x-sf-token"] != nil || headers["authorization"] != nil {
			failures = append(failures, "resource marker/authorization leaked to native signal")
		}
		if headers["x-fixture-header"] != "keep" {
			failures = append(failures, "harmless global exporter header lost")
		}
		if request["path"] == "/v1/traces" {
			if headers["agentstreamid"] != nil {
				failures = append(failures, "public AO stream header mixed into selected Studio routing")
			}
			if headers["x-precedence"] != "trace" {
				failures = append(failures, "signal-specific trace header precedence lost")
			}
			if project == nil || stream == nil || headers["projectid"] != project["id"] || headers["logstreamid"] != stream["id"] {
				failures = append(failures, "trace route IDs not resolved")
			}
		} else if headers["projectid"] != nil || headers["logstreamid"] != nil || headers["agentstreamid"] != nil || headers["x-precedence"] != "generic" {
			failures = append(failures, "AO IDs leaked to nontrace signal")
		}
	}
	serialized, _ := json.Marshal(requests)
	for _, secret := range []string{"fixture@example.test", "fixture-token-secret", "fixture-order-7"} {
		if bytes.Contains(serialized, []byte(secret)) {
			failures = append(failures, "unsafe source input emitted")
		}
	}
	for _, row := range spansFrom(run) {
		a := row["attributes"].(record)
		operation := a["gen_ai.operation.name"]
		toolOI := operation == "execute_tool" && a["openinference.span.kind"] == "TOOL" && a["input.value"] != nil
		for _, key := range []string{"gen_ai.input.messages"} {
			if (a[key] == nil || a[key] == "") && !toolOI {
				failures = append(failures, "missing "+key)
			}
		}
		scenario := a["app.scenario"]
		failed := scenario == "tool_error" && (operation == "execute_tool" || operation == "invoke_agent") || scenario == "provider_error" && (operation == "chat" || operation == "invoke_agent") || scenario == "cancel" && (operation == "execute_tool" || operation == "invoke_agent")
		if failed {
			if a["error.type"] == nil || a["gen_ai.output.messages"] != nil || a["output.value"] != nil || a["gen_ai.usage.input_tokens"] != nil {
				failures = append(failures, "failed operation output/error mismatch")
			}
		} else {
			for _, key := range []string{"gen_ai.output.messages"} {
				if a[key] == nil && !(toolOI && a["output.value"] != nil) {
					failures = append(failures, "missing "+key)
				}
			}
		}
	}
	metrics := map[string][]record{}
	for _, request := range requests {
		if request["path"] == "/v1/metrics" {
			for _, row := range request["records"].([]record) {
				metrics[fmt.Sprint(row["name"])] = append(metrics[fmt.Sprint(row["name"])], row)
			}
		}
	}
	for _, name := range []string{"gen_ai.client.inference.duration", "gen_ai.client.inference.usage.input_tokens", "gen_ai.client.inference.usage.output_tokens"} {
		if len(metrics[name]) == 0 {
			failures = append(failures, "missing "+name)
		}
	}
	failures = append(failures, profile(run, metrics)...)
	return failures
}
func main() {
	app := flag.String("app", "", "Absolute compiled app path")
	validatePath := flag.String("validate-receipt", "", "Read-only validation of an existing native receipt")
	output := flag.String("output", "capture.json", "Receipt path")
	expect := flag.String("expect", "capture", "baseline, native, capture")
	runs := flag.Int("runs", 1, "Process executions")
	resources := flag.String("resources", "missing", "existing, missing, auth")
	reject := flag.Bool("reject-traces", false, "Return actual trace400")
	flag.Parse()
	if *validatePath != "" {
		failures, err := validateReceipt(*validatePath, *expect)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		for _, failure := range failures {
			fmt.Fprintln(os.Stderr, failure)
		}
		fmt.Printf("receipt=%s failures=%d\n", *validatePath, len(failures))
		if len(failures) > 0 {
			os.Exit(1)
		}
		return
	}
	if !filepath.IsAbs(*app) || (*expect != "baseline" && *expect != "native" && *expect != "capture") || (*runs != 1 && *runs != 2) || (*resources != "existing" && *resources != "missing" && *resources != "auth") {
		fmt.Fprintln(os.Stderr, "invalid controller options")
		os.Exit(2)
	}
	state := &server{resources: *resources, reject: *reject, responseIDs: map[string]string{}}
	if *resources == "existing" {
		state.project = record{"id": uuid(), "name": "fixture-project", "type": "gen_ai"}
		state.stream = record{"id": uuid(), "name": "fixture-agent", "project_id": state.project["id"]}
	}
	sink := httptest.NewServer(state)
	defer sink.Close()
	receipt := record{"format": "local-go-native-genai-capture-v1", "expect": *expect, "resource_scenario": *resources, "reject_traces": *reject, "runs": []record{}, "logs_applicability": "No application logging stack; business stdout JSON is not an OTel LogRecord.", "passed": true}
	runRecords := []record{}
	for i := 0; i < *runs; i++ {
		state.mu.Lock()
		startNative, startModels, startJournal := len(state.native), len(state.models), len(state.journal)
		state.mu.Unlock()
		dir, e := os.MkdirTemp("", "native-go-proof-")
		if e != nil {
			panic(e)
		}
		business := filepath.Join(dir, "business.json")
		runCtx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
		command := exec.CommandContext(runCtx, *app, "--model-origin", sink.URL, "--scenario", "all", "--output", business)
		command.Env = cleanEnvironment(sink.URL)
		var stdout, stderr bytes.Buffer
		command.Stdout = &stdout
		command.Stderr = &stderr
		began := time.Now()
		e = command.Run()
		cancel()
		elapsed := time.Since(began)
		var outcomes []record
		data, _ := os.ReadFile(business)
		_ = json.Unmarshal(data, &outcomes)
		_ = os.RemoveAll(dir)
		state.mu.Lock()
		run := record{"run": i + 1, "exit_ok": e == nil, "duration_ms": elapsed.Milliseconds(), "business_outcomes": outcomes, "native_requests": append([]record{}, state.native[startNative:]...), "model_requests": append([]record{}, state.models[startModels:]...), "resource_requests": append([]record{}, state.journal[startJournal:]...), "model_response_ids": clone(state.responseIDs)}
		failures := validate(run, *expect, state.project, state.stream)
		if *expect == "capture" && (*resources == "auth" || *reject) {
			failures = append(failures, failureEvidence(run, *resources, *reject)...)
		}
		state.mu.Unlock()
		if e != nil {
			failures = append(failures, "app process failed")
		}
		run["failures"] = failures
		run["passed"] = len(failures) == 0
		run["stderr"] = stderr.String()
		runRecords = append(runRecords, run)
		if len(failures) > 0 {
			receipt["passed"] = false
		}
	}
	receipt["runs"] = runRecords
	receipt["resolved_project"] = state.project
	receipt["resolved_agent_stream"] = state.stream
	encoded, e := json.MarshalIndent(receipt, "", "  ")
	if e != nil {
		panic(e)
	}
	if e = os.WriteFile(*output, append(encoded, '\n'), 0600); e != nil {
		panic(e)
	}
	fmt.Printf("capture=%s passed=%v runs=%d\n", *output, receipt["passed"], len(runRecords))
	if receipt["passed"] != true {
		os.Exit(1)
	}
}

func clone(input map[string]string) map[string]string {
	out := map[string]string{}
	for k, v := range input {
		out[k] = v
	}
	return out
}
func asNumber(v any) float64 {
	switch n := v.(type) {
	case int:
		return float64(n)
	case int32:
		return float64(n)
	case int64:
		return float64(n)
	case uint64:
		return float64(n)
	case float64:
		return n
	}
	return -1
}
func profile(run record, metrics map[string][]record) []string {
	failures := []string{}
	responseIDs := map[string]string{}
	switch ids := run["model_response_ids"].(type) {
	case map[string]string:
		responseIDs = ids
	case map[string]any:
		for k, v := range ids {
			responseIDs[k] = fmt.Sprint(v)
		}
	}
	for _, row := range spansFrom(run) {
		a := row["attributes"].(record)
		op := fmt.Sprint(a["gen_ai.operation.name"])
		scenario := fmt.Sprint(a["app.scenario"])
		id := fmt.Sprint(a["app.request_id"])
		expectedScenario := map[string]string{"turn-1": "success", "turn-2": "tool_error", "turn-3": "provider_error", "turn-4": "cancel"}
		if a["app.scenario"] != expectedScenario[id] {
			failures = append(failures, "wrong source request/scenario")
		}
		wantName := map[string]string{"invoke_agent": "invoke_agent support_agent", "execute_tool": "execute_tool lookup_order", "retrieval": "retrieval knowledge_base", "chat": "chat fixture-model-v1"}[op]
		if row["name"] != wantName {
			failures = append(failures, "source span name mismatch")
		}
		if a["gen_ai.provider.name"] != "fixture.http" {
			failures = append(failures, "wrong source provider")
		}
		if oi := a["openinference.span.kind"]; oi != nil {
			want := map[string]string{"invoke_agent": "AGENT", "retrieval": "RETRIEVER", "execute_tool": "TOOL", "chat": "LLM"}[op]
			if oi != want || a["input.value"] == nil {
				failures = append(failures, "invalid selected OpenInference mapping")
			}
		}
		failed := scenario == "tool_error" && (op == "execute_tool" || op == "invoke_agent") || scenario == "provider_error" && (op == "chat" || op == "invoke_agent") || scenario == "cancel" && (op == "execute_tool" || op == "invoke_agent")
		status, _ := row["status"].(record)
		if failed && asNumber(status["code"]) != 2 {
			failures = append(failures, "failed source operation missing ERROR status")
		}
		if op == "invoke_agent" && (a["gen_ai.agent.name"] != "support_agent" || a["gen_ai.agent.description"] == nil) {
			failures = append(failures, "missing source agent metadata")
		}
		if op == "retrieval" {
			if a["gen_ai.retrieval.query.text"] == nil || a["gen_ai.retrieval.documents"] == nil || a["gen_ai.data_source.id"] != "knowledge_base" {
				failures = append(failures, "missing source retrieval content")
			}
		}
		if op == "execute_tool" {
			if a["gen_ai.tool.name"] != "lookup_order" || (a["gen_ai.tool.call.arguments"] == nil && a["openinference.span.kind"] != "TOOL") {
				failures = append(failures, "missing source tool identity/arguments")
			}
			if !failed && a["gen_ai.tool.call.result"] == nil && a["openinference.span.kind"] != "TOOL" {
				failures = append(failures, "missing actual tool result")
			}
			if a["gen_ai.tool.call.id"] != nil {
				failures = append(failures, "invented tool call ID")
			}
		}
		if op == "chat" {
			for _, key := range []string{"gen_ai.tool.definitions", "gen_ai.request.temperature", "gen_ai.request.top_p", "gen_ai.request.max_tokens", "gen_ai.request.stop_sequences", "server.address", "server.port"} {
				if a[key] == nil {
					failures = append(failures, "missing source model "+key)
				}
			}
			if a["gen_ai.request.model"] != "fixture-model-v1" {
				failures = append(failures, "wrong model")
			}
			if !failed {
				if a["gen_ai.response.id"] != responseIDs[id] || a["gen_ai.response.model"] != "fixture-model-v1" || asNumber(a["gen_ai.usage.input_tokens"]) != 11 || asNumber(a["gen_ai.usage.output_tokens"]) != 7 {
					failures = append(failures, "actual model response/fixture usage changed")
				}
			} else {
				for _, key := range []string{"gen_ai.response.id", "gen_ai.response.model", "gen_ai.response.finish_reasons", "gen_ai.usage.output_tokens"} {
					if a[key] != nil {
						failures = append(failures, "invented failed model response")
					}
				}
			}
		}
		if a["gen_ai.conversation.id"] != nil {
			failures = append(failures, "invented conversation ID")
		}
	}
	totals := map[string]float64{}
	for name, rows := range metrics {
		switch name {
		case "gen_ai.client.inference.duration", "gen_ai.client.inference.usage.input_tokens", "gen_ai.client.inference.usage.output_tokens":
		default:
			continue
		}
		for _, row := range rows {
			a := row["attributes"].(record)
			if a["gen_ai.operation.name"] != "chat" || a["gen_ai.provider.name"] != "fixture.http" || a["gen_ai.request.model"] != "fixture-model-v1" {
				failures = append(failures, "metric source dimensions missing")
			}
			switch name {
			case "gen_ai.client.inference.duration":
				if row["unit"] != "s" || asNumber(row["sum"]) <= 0 {
					failures = append(failures, "invalid inference duration")
				}
				totals[name] += asNumber(row["count"])
			case "gen_ai.client.inference.usage.input_tokens", "gen_ai.client.inference.usage.output_tokens":
				if asNumber(row["value"]) == 0 && (a["gen_ai.token.modality"] != "unknown" || a["error.type"] != "provider_unavailable") {
					failures = append(failures, "missing-usage zero identity wrong")
				}
				if asNumber(row["value"]) > 0 && a["gen_ai.token.modality"] != "text" {
					failures = append(failures, "known textual usage modality wrong")
				}
				if row["unit"] != "{token}" || (a["gen_ai.token.modality"] != "unknown" && a["gen_ai.token.modality"] != "text") || row["monotonic"] != true {
					failures = append(failures, "invalid source usage counter")
				}
				totals[name] += asNumber(row["value"])
			}
		}
	}
	for name, want := range map[string]float64{"gen_ai.client.inference.duration": 2, "gen_ai.client.inference.usage.input_tokens": 11, "gen_ai.client.inference.usage.output_tokens": 7} {
		if totals[name] != want {
			failures = append(failures, "wrong actual source metric total "+name)
		}
	}
	return failures
}
func validateReceipt(path, expect string) ([]string, error) {
	if expect != "baseline" && expect != "native" && expect != "capture" {
		return nil, errors.New("invalid expectation")
	}
	data, err := os.ReadFile(path)
	if err != nil || len(data) > 32*1024*1024 {
		return nil, errors.New("receipt unavailable/oversize")
	}
	var envelope struct {
		Resources string `json:"resource_scenario"`
		Reject    bool   `json:"reject_traces"`
		Format    string `json:"format"`
		Project   record `json:"resolved_project"`
		Stream    record `json:"resolved_agent_stream"`
		Runs      []struct {
			ExitOK    bool              `json:"exit_ok"`
			Business  []record          `json:"business_outcomes"`
			Models    []record          `json:"model_requests"`
			Resources []record          `json:"resource_requests"`
			IDs       map[string]string `json:"model_response_ids"`
			Native    []struct {
				Path    string   `json:"path"`
				Status  int      `json:"status"`
				Headers record   `json:"headers"`
				Body    []byte   `json:"body_base64"`
				Digest  string   `json:"body_sha256"`
				Records []record `json:"records"`
			} `json:"native_requests"`
		} `json:"runs"`
	}
	if json.Unmarshal(data, &envelope) != nil || envelope.Format != "local-go-native-genai-capture-v1" || len(envelope.Runs) == 0 {
		return nil, errors.New("invalid receipt envelope")
	}
	failures := []string{}
	for _, run := range envelope.Runs {
		native := []record{}
		for _, request := range run.Native {
			digest := sha256.Sum256(request.Body)
			if hex.EncodeToString(digest[:]) != request.Digest {
				failures = append(failures, "raw body digest changed")
			}
			wire := request.Body
			if request.Headers["content-encoding"] == "gzip" {
				reader, e := gzip.NewReader(bytes.NewReader(wire))
				if e != nil {
					return nil, errors.New("invalid compressed receipt")
				}
				wire, e = io.ReadAll(io.LimitReader(reader, 8*1024*1024+1))
				_ = reader.Close()
				if e != nil || len(wire) > 8*1024*1024 {
					return nil, errors.New("invalid compressed receipt")
				}
			}
			rows, e := decode(request.Path, wire)
			if e != nil {
				failures = append(failures, "raw protobuf invalid")
			}
			old, _ := json.Marshal(request.Records)
			fresh, _ := json.Marshal(rows)
			if !bytes.Equal(old, fresh) {
				failures = append(failures, "decoded records differ from raw protobuf")
			}
			native = append(native, record{"path": request.Path, "status": request.Status, "headers": request.Headers, "records": rows})
		}
		normalized := record{"exit_ok": run.ExitOK, "business_outcomes": run.Business, "model_requests": run.Models, "resource_requests": run.Resources, "model_response_ids": run.IDs, "native_requests": native}
		failures = append(failures, validate(normalized, expect, envelope.Project, envelope.Stream)...)
		if expect == "capture" && (envelope.Resources == "auth" || envelope.Reject) {
			failures = append(failures, failureEvidence(normalized, envelope.Resources, envelope.Reject)...)
		}
		if !run.ExitOK {
			failures = append(failures, "app process failed")
		}
	}
	return failures, nil
}

func failureEvidence(run record, resources string, reject bool) []string {
	failures := graph(spansFrom(run))
	metrics := map[string][]record{}
	traceRequests := 0
	metricRequests := 0
	for _, request := range run["native_requests"].([]record) {
		headers := request["headers"].(record)
		if headers["x-sf-token"] != nil || headers["authorization"] != nil {
			failures = append(failures, "resource marker/authorization leaked to native signal")
		}
		if headers["x-fixture-header"] != "keep" {
			failures = append(failures, "failure path lost harmless header")
		}
		if request["path"] == "/v1/traces" {
			if headers["agentstreamid"] != nil {
				failures = append(failures, "public AO stream header mixed into selected Studio routing")
			}
			traceRequests++
			if reject && request["status"] != 400 {
				failures = append(failures, "trace rejection not exercised")
			}
			if resources == "auth" && (headers["projectid"] != nil || headers["logstreamid"] != nil || headers["agentstreamid"] != nil) {
				failures = append(failures, "failed lookup retained stale AO binding")
			}
		}
		if request["path"] == "/v1/metrics" {
			metricRequests++
			if request["status"] != 200 || headers["projectid"] != nil || headers["logstreamid"] != nil || headers["agentstreamid"] != nil {
				failures = append(failures, "independent metric export failed")
			}
			for _, row := range request["records"].([]record) {
				metrics[fmt.Sprint(row["name"])] = append(metrics[fmt.Sprint(row["name"])], row)
			}
		}
	}
	if traceRequests < 1 || metricRequests < 1 {
		failures = append(failures, "failure path missing independent actual exports")
	}
	if resources == "auth" {
		journal := run["resource_requests"].([]record)
		if len(journal) != 1 || journal[0]["method"] != "GET" || asNumber(journal[0]["status"]) != 403 {
			failures = append(failures, "auth failure speculative resource request")
		}
	}
	return append(failures, profile(run, metrics)...)
}
