//go:build ignore

// This verification-only candidate is excluded from fresh application and instrument inputs.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetrichttp"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	"go.opentelemetry.io/otel/metric"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/trace"
)

var emailPattern = regexp.MustCompile(`[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}`)
var secretPattern = regexp.MustCompile(`(?i)(token|password|secret|order_id)["\s:=]+[^\s;,"}]+`)

const (
	maxMessages        = 4
	maxParts           = 4
	maxDocuments       = 4
	maxTextBytes       = 2048
	maxStructuredBytes = 32768
)

func clipText(text string) string {
	if len(text) <= maxTextBytes {
		return text
	}
	cut := maxTextBytes - len("[TRUNCATED]")
	for !utf8.RuneStart(text[cut]) {
		cut--
	}
	return text[:cut] + "[TRUNCATED]"
}
func sanitized(value any) any {
	data, _ := json.Marshal(value)
	var decoded any
	_ = json.Unmarshal(data, &decoded)
	budget := maxStructuredBytes / 8
	var walk func(any, int) any
	walk = func(input any, depth int) any {
		budget -= 16
		if depth > 8 || budget <= 0 {
			return "[TRUNCATED]"
		}
		switch v := input.(type) {
		case map[string]any:
			out := map[string]any{}
			keys := []string{}
			for key := range v {
				keys = append(keys, key)
			}
			sort.Strings(keys)
			for index, key := range keys {
				if index == 16 || budget <= 0 {
					break
				}
				if len(key) > 64 {
					continue
				}
				budget -= len(key)
				switch strings.ToLower(key) {
				case "token", "password", "secret", "order_id":
					out[key] = "[REDACTED]"
				default:
					out[key] = walk(v[key], depth+1)
				}
			}
			return out
		case []any:
			out := []any{}
			for index, item := range v {
				if index == 8 || budget <= 0 {
					break
				}
				out = append(out, walk(item, depth+1))
			}
			return out
		case string:
			var nested any
			if json.Unmarshal([]byte(v), &nested) == nil && (strings.HasPrefix(v, "{") || strings.HasPrefix(v, "[")) {
				encoded, _ := json.Marshal(walk(nested, depth+1))
				if len(encoded) > maxTextBytes {
					return `{"_telemetry_truncated":true}`
				}
				budget -= len(encoded)
				return string(encoded)
			}
			text := emailPattern.ReplaceAllString(v, "[REDACTED_EMAIL]")
			text = secretPattern.ReplaceAllString(text, "${1}:[REDACTED]")

			text = clipText(text)
			if len(text) > budget {
				text = "[TRUNCATED]"
			}
			budget -= len(text)
			return text
		default:
			return input
		}
	}
	return walk(decoded, 0)
}
func safe(value any) string { data, _ := json.Marshal(sanitized(value)); return string(data) }
func contentText(input any) string {
	value := sanitized(input)
	if text, ok := value.(string); ok {
		return text
	}
	data, _ := json.Marshal(value)
	return string(data)
}
func contentMIME(input any) string {
	if _, ok := input.(string); ok {
		return "text/plain"
	}
	return "application/json"
}

func messages(role string, input any) string {
	data, _ := json.Marshal([]any{map[string]any{"role": role, "parts": []any{map[string]any{"type": "text", "content": contentText(input)}}}})
	return string(data)
}
func jsonAttribute(key string, value any) attribute.KeyValue {
	data, _ := json.Marshal(value)
	return attribute.String(key, string(data))
}
func safeObject(value any) any { return sanitized(value) }

func studioHeaders(ctx context.Context) (map[string]string, error) {
	origin := os.Getenv("STUDIO_API_ORIGIN")
	if _, err := newApp(origin); err != nil {
		return nil, errors.New("invalid Studio API origin")
	}
	client := &http.Client{Transport: &http.Transport{Proxy: nil}, Timeout: 2 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	defer client.CloseIdleConnections()
	call := func(method, path string, input any, output any) error {
		var body io.Reader
		if input != nil {
			data, _ := json.Marshal(input)
			body = strings.NewReader(string(data))
		}
		request, err := http.NewRequestWithContext(ctx, method, origin+"/ao/api/projects"+path, body)
		if err != nil {
			return errors.New("resource request invalid")
		}
		request.Header.Set("X-SF-Token", "local-gateway")
		if input != nil {
			request.Header.Set("Content-Type", "application/json")
		}
		response, err := client.Do(request)
		if err != nil {
			return errors.New("resource request failed")
		}
		defer response.Body.Close()
		if response.StatusCode != 200 && (method != "POST" || response.StatusCode != 201) {
			return errors.New("resource response rejected")
		}
		data, err := io.ReadAll(io.LimitReader(response.Body, 1024*1024+1))
		if err != nil || len(data) > 1024*1024 {
			return errors.New("resource body invalid")
		}
		if json.Unmarshal(data, output) != nil {
			return errors.New("resource JSON invalid")
		}
		return nil
	}
	type item struct {
		ID        string `json:"id"`
		Name      string `json:"name"`
		ProjectID string `json:"project_id"`
	}
	validID := regexp.MustCompile(`^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$`)
	var projects []item
	if err := call("GET", "/all?type=gen_ai", nil, &projects); err != nil {
		return nil, err
	}
	var project item
	for _, candidate := range projects {
		if !validID.MatchString(candidate.ID) || candidate.Name == "" {
			return nil, errors.New("incomplete project list")
		}
		if candidate.Name == os.Getenv("SPLUNK_AO_PROJECT") {
			if project.ID != "" {
				return nil, errors.New("ambiguous project")
			}
			project = candidate
		}
	}
	if project.ID == "" {
		if err := call("POST", "", map[string]any{"name": os.Getenv("SPLUNK_AO_PROJECT"), "type": "gen_ai", "create_example_templates": false}, &project); err != nil {
			return nil, err
		}
	}
	if !validID.MatchString(project.ID) || project.Name != os.Getenv("SPLUNK_AO_PROJECT") {
		return nil, errors.New("wrong project identity")
	}
	var stream item
	seen := map[int]bool{}
	token := 0
	for pages := 0; pages < 1000; pages++ {
		if seen[token] {
			return nil, errors.New("pagination loop")
		}
		seen[token] = true
		var page struct {
			Streams   []item          `json:"log_streams"`
			Paginated *bool           `json:"paginated"`
			Next      json.RawMessage `json:"next_starting_token"`
		}
		path := "/" + project.ID + "/log_streams/paginated?include_counts=false&limit=100&starting_token=" + strconv.Itoa(token)
		if err := call("GET", path, nil, &page); err != nil {
			return nil, err
		}
		if page.Streams == nil || page.Paginated == nil || len(page.Next) == 0 {
			return nil, errors.New("incomplete stream page")
		}
		for _, candidate := range page.Streams {
			if !validID.MatchString(candidate.ID) || candidate.Name == "" || candidate.ProjectID != project.ID {
				return nil, errors.New("incomplete stream list")
			}
			if candidate.Name == os.Getenv("SPLUNK_AO_AGENT_STREAM") {
				if stream.ID != "" {
					return nil, errors.New("ambiguous stream")
				}
				stream = candidate
			}
		}
		if string(page.Next) == "null" {
			break
		}
		if !*page.Paginated || json.Unmarshal(page.Next, &token) != nil || token < 0 || pages == 999 {
			return nil, errors.New("invalid stream pagination")
		}
	}
	if stream.ID == "" {
		if err := call("POST", "/"+project.ID+"/log_streams", map[string]any{"name": os.Getenv("SPLUNK_AO_AGENT_STREAM")}, &stream); err != nil {
			return nil, err
		}
	}
	if !validID.MatchString(stream.ID) || stream.Name != os.Getenv("SPLUNK_AO_AGENT_STREAM") || stream.ProjectID != project.ID {
		return nil, errors.New("wrong stream identity")
	}
	return map[string]string{"projectid": project.ID, "logstreamid": stream.ID}, nil
}
func toolDefinitions(tools []ToolDefinition) []any {
	out := []any{}
	for index, tool := range tools {
		if index >= 4 {
			break
		}
		out = append(out, map[string]any{"type": tool.Type, "name": tool.Function.Name, "description": tool.Function.Description, "parameters": tool.Function.Parameters})
	}
	return out
}

func exportHeaders(signal string) (map[string]string, error) {
	headers := map[string]string{}
	text, present := os.LookupEnv("OTEL_EXPORTER_OTLP_" + signal + "_HEADERS")
	if !present {
		text = os.Getenv("OTEL_EXPORTER_OTLP_HEADERS")
	}
	for _, pair := range strings.Split(text, ",") {
		key, value, ok := strings.Cut(pair, "=")
		if !ok {
			continue
		}
		key = strings.TrimSpace(key)
		lower := strings.ToLower(key)
		if lower == "projectid" || lower == "logstreamid" || lower == "agentstreamid" {
			continue
		}
		decoded, err := url.PathUnescape(strings.TrimSpace(value))
		if err != nil {
			return nil, errors.New("invalid exporter header encoding")
		}
		headers[key] = decoded
	}
	return headers, nil
}

func configureTelemetry(ctx context.Context, app *App) (func(context.Context) error, error) {
	headers, lookupErr := studioHeaders(ctx)
	if lookupErr != nil {
		fmt.Fprintln(os.Stderr, "Studio resource lookup failed; exporting without bound AO IDs")
	}
	effective, err := exportHeaders("TRACES")
	if err != nil {
		return nil, err
	}
	for key, value := range headers {
		effective[key] = value
	}
	exporter, err := otlptracehttp.New(ctx, otlptracehttp.WithHeaders(effective), otlptracehttp.WithTimeout(2*time.Second))
	if err != nil {
		return nil, err
	}
	resource := resource.NewWithAttributes("", attribute.String("service.name", "native-genai-demo"), attribute.String("service.version", "1.0.0"))
	provider := sdktrace.NewTracerProvider(sdktrace.WithResource(resource), sdktrace.WithSyncer(exporter), sdktrace.WithSampler(sdktrace.AlwaysSample()))
	metricHeaders, err := exportHeaders("METRICS")
	if err != nil {
		return nil, err
	}
	metricExporter, err := otlpmetrichttp.New(ctx, otlpmetrichttp.WithHeaders(metricHeaders), otlpmetrichttp.WithTimeout(2*time.Second))
	if err != nil {
		_ = provider.Shutdown(ctx)
		return nil, err
	}
	meterProvider := sdkmetric.NewMeterProvider(sdkmetric.WithResource(resource), sdkmetric.WithReader(sdkmetric.NewPeriodicReader(metricExporter, sdkmetric.WithInterval(time.Hour))))
	meter := meterProvider.Meter("native-genai-profile")
	duration, err := meter.Float64Histogram("gen_ai.client.inference.duration", metric.WithUnit("s"))
	if err != nil {
		return nil, err
	}
	inputTokens, err := meter.Int64Counter("gen_ai.client.inference.usage.input_tokens", metric.WithUnit("{token}"))
	if err != nil {
		return nil, err
	}
	outputTokens, err := meter.Int64Counter("gen_ai.client.inference.usage.output_tokens", metric.WithUnit("{token}"))
	if err != nil {
		return nil, err
	}
	tracer := provider.Tracer("native-genai-profile")
	app.Observe = func(ctx context.Context, operation Operation) (context.Context, func(any, error)) {
		name, kind, oi := "", trace.SpanKindInternal, ""
		attrs := []attribute.KeyValue{attribute.String("app.request_id", operation.RequestID), attribute.String("app.scenario", operation.Scenario), attribute.String("gen_ai.provider.name", ProviderName), attribute.String("input.value", safe(operation.Input)), attribute.String("input.mime_type", "application/json")}
		switch operation.Name {
		case "agent":
			name = "invoke_agent"
			oi = "AGENT"
			attrs = append(attrs, attribute.String("gen_ai.agent.name", AgentName), attribute.String("gen_ai.agent.description", AgentDescription))
		case "retrieval":
			name = "retrieval"
			oi = "RETRIEVER"
			attrs = append(attrs, attribute.String("gen_ai.retrieval.query.text", contentText(operation.Input.(map[string]any)["query"])), attribute.String("gen_ai.data_source.id", fmt.Sprint(operation.Input.(map[string]any)["data_source"])))
		case "tool":
			name = "execute_tool"
			oi = ""
			attrs = append(attrs, attribute.String("gen_ai.tool.name", ToolName), attribute.String("gen_ai.tool.description", ToolDescription), attribute.String("gen_ai.tool.type", "function"), jsonAttribute("gen_ai.tool.call.arguments", safeObject(operation.Input)))
		case "model":
			name = "chat"
			kind = trace.SpanKindClient
			oi = "LLM"
			input := operation.Input.(ModelRequest)
			origin, _ := url.Parse(app.ModelOrigin)
			port, _ := strconv.Atoi(origin.Port())
			attrs = append(attrs, attribute.String("gen_ai.request.model", input.Model), attribute.Float64("gen_ai.request.temperature", input.Temperature), attribute.Float64("gen_ai.request.top_p", input.TopP), attribute.Int("gen_ai.request.max_tokens", input.MaxTokens), attribute.StringSlice("gen_ai.request.stop_sequences", input.Stop), attribute.String("server.address", origin.Hostname()), attribute.Int("server.port", port), jsonAttribute("gen_ai.tool.definitions", toolDefinitions(input.Tools)))
			modelMessages := []any{}
			for index, message := range input.Messages {
				if index >= maxMessages {
					break
				}
				modelMessages = append(modelMessages, map[string]any{"role": message.Role, "parts": []any{map[string]any{"type": "text", "content": contentText(message.Content)}}})
			}
			attrs = append(attrs, jsonAttribute("gen_ai.input.messages", modelMessages))
		}
		attrs = append(attrs, attribute.String("gen_ai.operation.name", name))
		if oi != "" {
			attrs = append(attrs, attribute.String("openinference.span.kind", oi))
		}
		if operation.Name != "model" {
			role := "user"
			if operation.Name == "tool" {
				role = "tool"
			}
			attrs = append(attrs, attribute.String("gen_ai.input.messages", messages(role, operation.Input)))
		}
		spanName := name
		switch operation.Name {
		case "agent":
			spanName += " " + AgentName
		case "tool":
			spanName += " " + ToolName
		case "retrieval":
			spanName += " knowledge_base"
		case "model":
			spanName += " " + operation.Input.(ModelRequest).Model
		}
		spanCtx, span := tracer.Start(ctx, spanName, trace.WithSpanKind(kind), trace.WithAttributes(attrs...))
		began := time.Now()
		return spanCtx, func(result any, failure error) {
			defer span.End()
			if operation.Name == "model" {
				origin, _ := url.Parse(app.ModelOrigin)
				values := []attribute.KeyValue{attribute.String("gen_ai.operation.name", "chat"), attribute.String("gen_ai.provider.name", ProviderName), attribute.String("gen_ai.request.model", operation.Input.(ModelRequest).Model), attribute.String("server.address", origin.Hostname())}
				port, _ := strconv.Atoi(origin.Port())
				values = append(values, attribute.Int("server.port", port))
				if failure != nil {
					values = append(values, attribute.String("error.type", errorType(failure)))
				}
				in, out := int64(0), int64(0)
				if failure == nil {
					response := result.(ModelResponse)
					in, out = int64(response.Usage.InputTokens), int64(response.Usage.OutputTokens)
				}
				duration.Record(spanCtx, time.Since(began).Seconds(), metric.WithAttributes(values...))
				modality := "unknown"
				if failure == nil {
					modality = "text"
					values = append(values, attribute.String("gen_ai.response.model", result.(ModelResponse).Model))
				}
				values = append(values, attribute.String("gen_ai.token.modality", modality))
				inputTokens.Add(spanCtx, in, metric.WithAttributes(values...))
				outputTokens.Add(spanCtx, out, metric.WithAttributes(values...))
			}
			if failure != nil {
				span.SetStatus(codes.Error, errorType(failure))
				span.SetAttributes(attribute.String("error.type", errorType(failure)))
				span.AddEvent("exception", trace.WithAttributes(attribute.String("exception.type", errorType(failure)), attribute.String("exception.message", errorType(failure))))
				return
			}
			outputValue := result
			if operation.Name == "model" {
				outputValue = result.(ModelResponse).Message.Content
			}
			span.SetAttributes(attribute.String("output.value", contentText(outputValue)), attribute.String("output.mime_type", contentMIME(outputValue)))
			role := "assistant"
			if operation.Name == "tool" {
				role = "tool"
			}
			span.SetAttributes(attribute.String("gen_ai.output.messages", messages(role, result)))
			switch operation.Name {
			case "tool":
				span.SetAttributes(jsonAttribute("gen_ai.tool.call.result", safeObject(result)))
			case "retrieval":
				documents := []any{}
				for index, text := range result.([]string) {
					if index >= maxDocuments {
						break
					}
					documents = append(documents, map[string]any{"content": contentText(text)})
				}
				span.SetAttributes(jsonAttribute("gen_ai.retrieval.documents", documents))
				for index, text := range result.([]string) {
					if index >= maxDocuments {
						break
					}
					span.SetAttributes(attribute.String(fmt.Sprintf("retrieval.documents.%d.document.content", index), contentText(text)))
				}
			case "model":
				response := result.(ModelResponse)
				span.SetAttributes(attribute.String("gen_ai.response.id", response.ID), attribute.String("gen_ai.response.model", response.Model), attribute.StringSlice("gen_ai.response.finish_reasons", []string{response.FinishReason}), attribute.Int("gen_ai.usage.input_tokens", response.Usage.InputTokens), attribute.Int("gen_ai.usage.output_tokens", response.Usage.OutputTokens), attribute.String("gen_ai.output.messages", messages(response.Message.Role, response.Message.Content)))
			}
		}
	}
	return func(ctx context.Context) error {
		if err := provider.Shutdown(ctx); err != nil {
			fmt.Fprintln(os.Stderr, "trace export failed")
		}
		if err := meterProvider.Shutdown(ctx); err != nil {
			fmt.Fprintln(os.Stderr, "metric export failed")
		}
		return nil
	}, nil
}
