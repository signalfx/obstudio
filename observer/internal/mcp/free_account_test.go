package mcp

import (
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/signalfx/obstudio/observer/internal/freeaccount"
	"github.com/signalfx/obstudio/observer/internal/store"
)

type fakeMCPFreeAccountSubmitter struct {
	request        freeaccount.Request
	result         freeaccount.Result
	regionResult   freeaccount.RegionResult
	err            error
	ctxErr         error
	calls          int
	detectionCalls int
}

func (f *fakeMCPFreeAccountSubmitter) DetectRegion(ctx context.Context) freeaccount.RegionResult {
	f.detectionCalls++
	f.ctxErr = ctx.Err()
	return f.regionResult
}

func (f *fakeMCPFreeAccountSubmitter) Submit(ctx context.Context, request freeaccount.Request) (freeaccount.Result, error) {
	f.calls++
	f.request = request
	f.ctxErr = ctx.Err()
	return f.result, f.err
}

func TestFreeAccountToolIsConditionalAndRequiresOnlyMinimumInput(t *testing.T) {
	withoutService := NewDispatcher(store.New())
	for _, tool := range withoutService.tools {
		if tool.Name == "observer_splunk_free_account_create" || tool.Name == "observer_splunk_free_account_region_detect" {
			t.Fatal("free-account tool advertised without a submitter")
		}
	}
	response, _ := withoutService.Dispatch(jsonRPCRequest{
		ID: 1, JSONRPC: "2.0", Method: "tools/call",
		Params: map[string]any{"name": "observer_splunk_free_account_create", "arguments": map[string]any{}},
	})
	if response.Error == nil || response.Error.Code != -32602 {
		t.Fatalf("direct call without service = %+v, want unknown tool", response)
	}

	submitter := &fakeMCPFreeAccountSubmitter{}
	withService := NewDispatcher(store.New(), submitter)
	var definition *toolDef
	for index := range withService.tools {
		if withService.tools[index].Name == "observer_splunk_free_account_create" {
			definition = &withService.tools[index]
			break
		}
	}
	if definition == nil {
		t.Fatal("free-account tool was not advertised with submitter")
	}
	if got := definition.InputSchema.Required; len(got) != 4 || got[0] != "firstName" || got[1] != "lastName" || got[2] != "email" || got[3] != "termsAccepted" {
		t.Fatalf("required fields = %#v", got)
	}
	if len(definition.InputSchema.Properties) != 5 || definition.InputSchema.AdditionalProperties == nil || *definition.InputSchema.AdditionalProperties {
		t.Fatalf("input schema permits unsupported input: %+v", definition.InputSchema)
	}
	for _, field := range []string{"firstName", "lastName"} {
		if definition.InputSchema.Properties[field].MaxLength == nil || *definition.InputSchema.Properties[field].MaxLength != 40 {
			t.Fatalf("%s maxLength = %+v, want 40", field, definition.InputSchema.Properties[field].MaxLength)
		}
	}
	if definition.InputSchema.Properties["email"].MaxLength == nil || *definition.InputSchema.Properties["email"].MaxLength != 80 {
		t.Fatalf("email maxLength = %+v, want 80", definition.InputSchema.Properties["email"].MaxLength)
	}
	region := definition.InputSchema.Properties["region"]
	if got := strings.Join(region.Enum, "|"); got != "us|Europe (Ireland)|apac-au" {
		t.Fatalf("region enum = %q", got)
	}
	if definition.Annotations.ReadOnlyHint || definition.Annotations.DestructiveHint || definition.Annotations.IdempotentHint || !definition.Annotations.OpenWorldHint {
		t.Fatalf("unexpected annotations: %+v", definition.Annotations)
	}
	if !containsAll(definition.Description, "explicitly accepts", "GeoIP", "postal code", "privacyPolicyCheck=1", "public signup form", "technical realm", "never call this tool speculatively", "automatically retry", "acknowledged intake", "cannot verify provisioning or email delivery") {
		t.Fatalf("description lost safety guidance: %q", definition.Description)
	}
	if strings.Contains(definition.Description, "finish provisioning") || strings.Contains(definition.InputSchema.Properties["email"].Description, "will receive") {
		t.Fatalf("tool schema overstates downstream state: description=%q email=%q", definition.Description, definition.InputSchema.Properties["email"].Description)
	}
}

func TestFreeAccountRegionDetectionToolIsReadOnlyAndReturnsOnlyRegion(t *testing.T) {
	submitter := &fakeMCPFreeAccountSubmitter{regionResult: freeaccount.RegionResult{Region: "Europe (Ireland)"}}
	dispatcher := NewDispatcher(store.New(), submitter)
	var definition *toolDef
	for index := range dispatcher.tools {
		if dispatcher.tools[index].Name == "observer_splunk_free_account_region_detect" {
			definition = &dispatcher.tools[index]
			break
		}
	}
	if definition == nil {
		t.Fatal("region detection tool was not advertised")
	}
	if definition.InputSchema.AdditionalProperties == nil || *definition.InputSchema.AdditionalProperties || len(definition.InputSchema.Properties) != 0 {
		t.Fatalf("unexpected detector input schema: %+v", definition.InputSchema)
	}
	if !definition.Annotations.ReadOnlyHint || !definition.Annotations.IdempotentHint || definition.Annotations.DestructiveHint || !definition.Annotations.OpenWorldHint {
		t.Fatalf("unexpected detector annotations: %+v", definition.Annotations)
	}

	response, handled := dispatcher.Dispatch(jsonRPCRequest{
		ID: 1, JSONRPC: "2.0", Method: "tools/call",
		Params: map[string]any{"name": "observer_splunk_free_account_region_detect", "arguments": map[string]any{}},
	})
	if !handled || response.Error != nil || submitter.detectionCalls != 1 || submitter.calls != 0 {
		t.Fatalf("unexpected response/calls: response=%+v detect=%d submit=%d", response, submitter.detectionCalls, submitter.calls)
	}
	result := response.Result.(toolResult)
	payload := toMapAny(parseToolResult(t, result))
	if len(payload) != 1 || payload["region"] != "Europe (Ireland)" {
		t.Fatalf("payload = %#v, want only region", payload)
	}

	response, _ = dispatcher.Dispatch(jsonRPCRequest{
		ID: 2, JSONRPC: "2.0", Method: "tools/call",
		Params: map[string]any{"name": "observer_splunk_free_account_region_detect", "arguments": map[string]any{"email": "not-allowed@example.com"}},
	})
	result = response.Result.(toolResult)
	if !result.IsError || submitter.detectionCalls != 1 {
		t.Fatalf("detector accepted arguments: result=%+v calls=%d", result, submitter.detectionCalls)
	}
}

func TestFreeAccountToolForwardsExplicitConsentAndReturnsAcknowledgedIntake(t *testing.T) {
	submitter := &fakeMCPFreeAccountSubmitter{result: freeaccount.Result{
		IntakeAcknowledged: true,
		Realm:              "au0",
		Region:             "apac-au",
		Message:            "Thank you for registering. Your free edition account is on its way!",
	}}
	dispatcher := NewDispatcher(store.New(), submitter)
	response, handled := dispatcher.Dispatch(jsonRPCRequest{
		ID: 1, JSONRPC: "2.0", Method: "tools/call",
		Params: map[string]any{
			"name": "observer_splunk_free_account_create",
			"arguments": map[string]any{
				"firstName":     "Ada",
				"lastName":      "Lovelace",
				"email":         "ada@example.com",
				"region":        "Europe (Ireland)",
				"termsAccepted": true,
			},
		},
	})
	if !handled || response.Error != nil {
		t.Fatalf("unexpected response: %+v", response)
	}
	if submitter.calls != 1 {
		t.Fatalf("submitter calls = %d, want 1", submitter.calls)
	}
	if submitter.ctxErr != nil {
		t.Fatalf("transport-neutral Dispatch context error = %v, want background context", submitter.ctxErr)
	}
	want := freeaccount.Request{FirstName: "Ada", LastName: "Lovelace", Email: "ada@example.com", Region: "Europe (Ireland)", TermsAccepted: true}
	if submitter.request != want {
		t.Fatalf("request = %+v, want %+v", submitter.request, want)
	}
	result := response.Result.(toolResult)
	if result.IsError {
		t.Fatalf("tool returned error: %+v", result)
	}
	payload := toMapAny(parseToolResult(t, result))
	if payload["intakeAcknowledged"] != true || payload["realm"] != "au0" || payload["region"] != "apac-au" || payload["message"] != "Thank you for registering. Your free edition account is on its way!" {
		t.Fatalf("unexpected tool payload: %#v", payload)
	}
	if len(payload) != 4 {
		t.Fatalf("tool payload fields = %#v, want only intakeAcknowledged, realm, region, and message", payload)
	}
	if _, exists := payload["intakeAccepted"]; exists {
		t.Fatalf("tool payload retained misleading intakeAccepted field: %#v", payload)
	}
}

func TestFreeAccountToolRejectsUnexpectedArgumentsBeforeSubmission(t *testing.T) {
	for _, extraKey := range []string{"fullName", "publicIp", "company"} {
		t.Run(extraKey, func(t *testing.T) {
			submitter := &fakeMCPFreeAccountSubmitter{}
			dispatcher := NewDispatcher(store.New(), submitter)
			response, handled := dispatcher.Dispatch(jsonRPCRequest{
				ID: 1, JSONRPC: "2.0", Method: "tools/call",
				Params: map[string]any{
					"name": "observer_splunk_free_account_create",
					"arguments": map[string]any{
						"firstName":     "Ada",
						"lastName":      "Lovelace",
						"email":         "ada@example.com",
						"termsAccepted": true,
						extraKey:        "must-not-pass",
					},
				},
			})
			if !handled || response.Error != nil {
				t.Fatalf("unexpected response: %+v", response)
			}
			if submitter.calls != 0 {
				t.Fatalf("submitter calls = %d, want 0", submitter.calls)
			}
			result := response.Result.(toolResult)
			if !result.IsError {
				t.Fatalf("tool did not reject unexpected argument: %+v", result)
			}
			payload := toMapAny(parseToolResult(t, result))
			if payload["code"] != string(freeaccount.ErrorCodeValidation) || payload["retrySafe"] != true {
				t.Fatalf("payload = %#v", payload)
			}
		})
	}

	submitter := &fakeMCPFreeAccountSubmitter{}
	dispatcher := NewDispatcher(store.New(), submitter)
	response, _ := dispatcher.Dispatch(jsonRPCRequest{
		ID: 1, JSONRPC: "2.0", Method: "tools/call",
		Params: map[string]any{
			"name": "observer_splunk_free_account_create",
			"arguments": map[string]any{
				"firstName": "Ada", "lastName": "Lovelace", "email": "ada@example.com",
				"termsAccepted": true, "region": 1,
			},
		},
	})
	result := response.Result.(toolResult)
	if !result.IsError || submitter.calls != 0 {
		t.Fatalf("tool accepted non-string region: result=%+v calls=%d", result, submitter.calls)
	}
}

func TestFreeAccountToolRejectsLegacyRealmRegion(t *testing.T) {
	dispatcher := NewDispatcher(store.New(), freeaccount.New(freeaccount.Config{GeoURL: ":", SignupURL: ":"}))
	response, handled := dispatcher.Dispatch(jsonRPCRequest{
		ID: 1, JSONRPC: "2.0", Method: "tools/call",
		Params: map[string]any{
			"name": "observer_splunk_free_account_create",
			"arguments": map[string]any{
				"firstName":     "Ada",
				"lastName":      "Lovelace",
				"email":         "ada@example.com",
				"region":        "eu0",
				"termsAccepted": true,
			},
		},
	})
	if !handled || response.Error != nil {
		t.Fatalf("unexpected response: %+v", response)
	}
	result := response.Result.(toolResult)
	payload := toMapAny(parseToolResult(t, result))
	if !result.IsError || payload["code"] != string(freeaccount.ErrorCodeValidation) || payload["retrySafe"] != true {
		t.Fatalf("legacy realm was not rejected: result=%+v payload=%#v", result, payload)
	}
}

func TestFreeAccountToolReturnsStructuredSafeErrors(t *testing.T) {
	tests := []struct {
		name      string
		err       error
		wantCode  string
		wantRetry bool
	}{
		{
			name:      "signup error",
			err:       &freeaccount.Error{Code: freeaccount.ErrorCodeOutcomeUnknown, Message: "Check email before trying again.", RetrySafe: false},
			wantCode:  "outcome_unknown",
			wantRetry: false,
		},
		{
			name:      "internal error redacted",
			err:       errors.New("secret.person@example.com could not submit"),
			wantCode:  "internal_error",
			wantRetry: false,
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			submitter := &fakeMCPFreeAccountSubmitter{err: test.err}
			dispatcher := NewDispatcher(store.New(), submitter)
			response, handled := dispatcher.Dispatch(jsonRPCRequest{
				ID: 1, JSONRPC: "2.0", Method: "tools/call",
				Params: map[string]any{
					"name": "observer_splunk_free_account_create",
					"arguments": map[string]any{
						"firstName":     "Secret",
						"lastName":      "Person",
						"email":         "secret.person@example.com",
						"termsAccepted": true,
					},
				},
			})
			if !handled || response.Error != nil {
				t.Fatalf("unexpected response: %+v", response)
			}
			result := response.Result.(toolResult)
			if !result.IsError {
				t.Fatalf("tool did not mark error: %+v", result)
			}
			payload := toMapAny(parseToolResult(t, result))
			if payload["code"] != test.wantCode || payload["retrySafe"] != test.wantRetry {
				t.Fatalf("payload = %#v", payload)
			}
			if strings.Contains(result.Content[0].Text, "secret.person@example.com") {
				t.Fatalf("tool response exposed internal PII: %s", result.Content[0].Text)
			}
		})
	}
}
