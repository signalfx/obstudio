package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
)

const (
	AgentName        = "support_agent"
	AgentDescription = "Resolve an order question with policy retrieval, order lookup, and an HTTP model."
	ToolName         = "lookup_order"
	ToolDescription  = "Read the current shipping state of an order."
	ProviderName     = "fixture.http"
	ModelName        = "fixture-model-v1"
)

var scenarios = []string{"success", "tool_error", "provider_error", "cancel"}

type Operation struct {
	Name      string
	RequestID string
	Scenario  string
	Input     any
}

// Observe is an application seam. The initial runtime leaves it nil.
type ObserveFunc func(context.Context, Operation) (context.Context, func(any, error))

type App struct {
	ModelOrigin string
	Client      *http.Client
	Observe     ObserveFunc
}

type Request struct {
	ID       string `json:"request_id"`
	Scenario string `json:"scenario"`
	Prompt   string `json:"prompt"`
}

type Message struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type ToolDefinition struct {
	Type     string       `json:"type"`
	Function ToolFunction `json:"function"`
}

type ToolFunction struct {
	Name        string         `json:"name"`
	Description string         `json:"description"`
	Parameters  map[string]any `json:"parameters"`
}

type ModelRequest struct {
	RequestID   string           `json:"request_id"`
	Scenario    string           `json:"scenario"`
	Model       string           `json:"model"`
	Messages    []Message        `json:"messages"`
	Tools       []ToolDefinition `json:"tools"`
	Temperature float64          `json:"temperature"`
	TopP        float64          `json:"top_p"`
	MaxTokens   int              `json:"max_tokens"`
	Stop        []string         `json:"stop"`
}

type Usage struct {
	InputTokens  int `json:"input_tokens"`
	OutputTokens int `json:"output_tokens"`
}

type ModelResponse struct {
	ID           string  `json:"id"`
	Model        string  `json:"model"`
	FinishReason string  `json:"finish_reason"`
	Message      Message `json:"message"`
	Usage        Usage   `json:"usage"`
}

type Order struct {
	State string `json:"state"`
}

type Outcome struct {
	RequestID string `json:"request_id"`
	Scenario  string `json:"scenario"`
	Result    string `json:"result,omitempty"`
	ErrorType string `json:"error_type,omitempty"`
}

type operationError struct{ code string }

func (e *operationError) Error() string { return e.code }

var errToolUnavailable = &operationError{"tool_unavailable"}
var errProviderUnavailable = &operationError{"provider_unavailable"}

func newApp(origin string) (*App, error) {
	parsed, err := url.Parse(origin)
	if err != nil {
		return nil, errors.New("invalid local model origin")
	}
	ip := net.ParseIP(parsed.Hostname())
	port, portErr := strconv.Atoi(parsed.Port())
	if parsed.Scheme != "http" || ip == nil || !ip.IsLoopback() || portErr != nil || port < 1 || port > 65535 || parsed.User != nil || parsed.RawQuery != "" || parsed.Fragment != "" || (parsed.Path != "" && parsed.Path != "/") {
		return nil, errors.New("model origin must be explicit numeric loopback HTTP")
	}
	return &App{ModelOrigin: strings.TrimRight(origin, "/"), Client: &http.Client{
		Transport: &http.Transport{Proxy: nil}, Timeout: 2 * time.Second,
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
	}}, nil
}

func (app *App) observe(ctx context.Context, operation Operation) (context.Context, func(any, error)) {
	if app.Observe != nil {
		return app.Observe(ctx, operation)
	}
	return ctx, func(any, error) {}
}

func (app *App) retrieveDocuments(ctx context.Context, request Request) (documents []string, err error) {
	ctx, finish := app.observe(ctx, Operation{"retrieval", request.ID, request.Scenario, map[string]any{"query": request.Prompt, "data_source": "knowledge_base"}})
	defer func() { finish(documents, err) }()
	if err = ctx.Err(); err != nil {
		return
	}
	return []string{"Policy: orders can be checked with lookup_order."}, nil
}

func (app *App) lookupOrder(ctx context.Context, request Request) (order Order, err error) {
	ctx, finish := app.observe(ctx, Operation{"tool", request.ID, request.Scenario, map[string]any{"order_id": "fixture-order-7"}})
	defer func() { finish(order, err) }()
	if err = ctx.Err(); err != nil {
		return
	}
	if request.Scenario == "tool_error" {
		return Order{}, errToolUnavailable
	}
	return Order{State: "shipped"}, nil
}

func (app *App) callModel(ctx context.Context, input ModelRequest) (output ModelResponse, err error) {
	ctx, finish := app.observe(ctx, Operation{"model", input.RequestID, input.Scenario, input})
	defer func() { finish(output, err) }()
	body, err := json.Marshal(input)
	if err != nil {
		return
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, app.ModelOrigin+"/model", bytes.NewReader(body))
	if err != nil {
		return
	}
	request.Header.Set("Content-Type", "application/json")
	response, err := app.Client.Do(request)
	if err != nil {
		return
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return ModelResponse{}, errProviderUnavailable
	}
	err = json.NewDecoder(io.LimitReader(response.Body, 65536)).Decode(&output)
	return
}

func (app *App) runAgent(ctx context.Context, request Request) (answer string, err error) {
	ctx, finish := app.observe(ctx, Operation{"agent", request.ID, request.Scenario, request})
	defer func() { finish(answer, err) }()
	documents, err := app.retrieveDocuments(ctx, request)
	if err != nil {
		return
	}
	if request.Scenario == "cancel" {
		var cancel context.CancelFunc
		ctx, cancel = context.WithCancel(ctx)
		cancel()
	}
	order, err := app.lookupOrder(ctx, request)
	if err != nil {
		return
	}
	userContent, err := json.Marshal(map[string]any{"prompt": request.Prompt, "documents": documents, "order": order})
	if err != nil {
		return
	}
	model, err := app.callModel(ctx, ModelRequest{
		RequestID: request.ID, Scenario: request.Scenario, Model: ModelName,
		Messages:    []Message{{Role: "system", Content: "Answer order questions using the supplied policy and order state."}, {Role: "user", Content: string(userContent)}},
		Tools:       []ToolDefinition{{Type: "function", Function: ToolFunction{Name: ToolName, Description: ToolDescription, Parameters: map[string]any{"type": "object", "properties": map[string]any{"order_id": map[string]any{"type": "string"}}, "required": []string{"order_id"}, "additionalProperties": false}}}},
		Temperature: 0.2, TopP: 0.9, MaxTokens: 64, Stop: []string{"END"},
	})
	if err != nil {
		return
	}
	return model.Message.Content, nil
}

func errorType(err error) string {
	if errors.Is(err, context.Canceled) {
		return "cancelled"
	}
	var failure *operationError
	if errors.As(err, &failure) {
		return failure.code
	}
	return "transport_error"
}

func main() {
	origin := flag.String("model-origin", "", "Explicit numeric-loopback HTTP model origin")
	scenario := flag.String("scenario", "all", "all, success, tool_error, provider_error, or cancel")
	output := flag.String("output", "", "Optional business receipt JSON path")
	flag.Parse()
	app, err := newApp(*origin)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	shutdown, err := configureTelemetry(context.Background(), app)
	if err != nil {
		fmt.Fprintln(os.Stderr, "telemetry setup failed")
		os.Exit(1)
	}
	var outcomes []Outcome
	for index, name := range scenarios {
		if *scenario != "all" && *scenario != name {
			continue
		}
		request := Request{ID: fmt.Sprintf("turn-%d", index+1), Scenario: name, Prompt: "Where is my order? email: fixture@example.test; token: fixture-token-secret; question: delivery status"}
		answer, failure := app.runAgent(context.Background(), request)
		outcome := Outcome{RequestID: request.ID, Scenario: name, Result: answer}
		if failure != nil {
			outcome.ErrorType = errorType(failure)
		}
		outcomes = append(outcomes, outcome)
	}
	if len(outcomes) == 0 {
		fmt.Fprintln(os.Stderr, "unknown scenario")
		os.Exit(1)
	}
	if err := shutdown(context.Background()); err != nil {
		fmt.Fprintln(os.Stderr, "telemetry shutdown failed")
		os.Exit(1)
	}
	app.Client.CloseIdleConnections()
	encoded, _ := json.MarshalIndent(outcomes, "", "  ")
	if *output != "" {
		if err := os.WriteFile(*output, append(encoded, '\n'), 0600); err != nil {
			fmt.Fprintln(os.Stderr, "business receipt write failed")
			os.Exit(1)
		}
	}
	fmt.Println(string(encoded))
}
