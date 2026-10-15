package main

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"reflect"
	"testing"
)

func TestAgentBusinessFlowWithoutTelemetry(t *testing.T) {
	calls := []string{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var request ModelRequest
		if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
			t.Error(err)
		}
		calls = append(calls, request.Scenario)
		if r.URL.Path != "/model" || r.Method != "POST" || request.Model != ModelName || len(request.Messages) != 2 || len(request.Tools) != 1 || request.Temperature != 0.2 || request.MaxTokens != 64 {
			t.Error("source request controls changed")
		}
		if request.Scenario == "provider_error" {
			w.WriteHeader(503)
			return
		}
		_ = json.NewEncoder(w).Encode(ModelResponse{ID: "actual-response", Model: request.Model, FinishReason: "stop", Message: Message{Role: "assistant", Content: "source answer"}, Usage: Usage{InputTokens: 11, OutputTokens: 7}})
	}))
	defer server.Close()
	app, err := newApp(server.URL)
	if err != nil {
		t.Fatal(err)
	}
	if app.Observe != nil {
		t.Fatal("new app unexpectedly has an active observer")
	}
	for _, scenario := range scenarios {
		answer, err := app.runAgent(context.Background(), Request{ID: "source-request", Scenario: scenario, Prompt: "source prompt"})
		if scenario == "success" {
			if err != nil || answer != "source answer" {
				t.Fatal("success changed")
			}
		} else {
			want := map[string]string{"tool_error": "tool_unavailable", "provider_error": "provider_unavailable", "cancel": "cancelled"}[scenario]
			if err == nil || errorType(err) != want {
				t.Fatalf("%s error=%v", scenario, err)
			}
		}
	}
	if !reflect.DeepEqual(calls, []string{"success", "provider_error"}) {
		t.Fatal(calls)
	}
}
func TestModelOriginRequiresExplicitNumericLoopback(t *testing.T) {
	for _, origin := range []string{"http://localhost:1234", "https://127.0.0.1:1234", "http://127.0.0.1", "http://127.0.0.1:1234/path", "http://user:secret@127.0.0.1:1234", "http://192.0.2.1:1234"} {
		if _, err := newApp(origin); err == nil {
			t.Fatalf("accepted %s", origin)
		}
	}
}
