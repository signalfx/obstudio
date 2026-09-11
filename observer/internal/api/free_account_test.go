package api

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/signalfx/obstudio/observer/internal/freeaccount"
	"github.com/signalfx/obstudio/observer/internal/store"
)

type fakeFreeAccountSubmitter struct {
	request        freeaccount.Request
	result         freeaccount.Result
	regionResult   freeaccount.RegionResult
	err            error
	calls          int
	detectionCalls int
}

func (f *fakeFreeAccountSubmitter) Submit(_ context.Context, request freeaccount.Request) (freeaccount.Result, error) {
	f.calls++
	f.request = request
	return f.result, f.err
}

func (f *fakeFreeAccountSubmitter) DetectRegion(_ context.Context) freeaccount.RegionResult {
	f.detectionCalls++
	return f.regionResult
}

func localFreeAccountRequest(method, target string, body io.Reader) *http.Request {
	request := httptest.NewRequest(method, target, body)
	request.RemoteAddr = "127.0.0.1:54321"
	return request
}

func TestFreeAccountEndpointUsesLocalOriginTrustWithoutControlCredentials(t *testing.T) {
	submitter := &fakeFreeAccountSubmitter{result: freeaccount.Result{
		IntakeAcknowledged: true,
		Realm:              "us1",
		Region:             "United States",
	}}
	mux := http.NewServeMux()
	Register(mux, store.New(), submitter)
	body := `{"firstName":"Ada","lastName":"Lovelace","email":"ada@example.com","region":"us","termsAccepted":true}`

	localRequest := httptest.NewRequest(http.MethodPost, "/api/splunk/free-account", strings.NewReader(body))
	localRequest.RemoteAddr = "127.0.0.1:54321"
	localResponse := httptest.NewRecorder()
	mux.ServeHTTP(localResponse, localRequest)
	if localResponse.Code != http.StatusAccepted {
		t.Fatalf("local request status = %d, want %d; body=%s", localResponse.Code, http.StatusAccepted, localResponse.Body.String())
	}
	if submitter.calls != 1 {
		t.Fatalf("local request submitter calls = %d, want 1", submitter.calls)
	}
	if got := localResponse.Header().Get("Access-Control-Allow-Origin"); got != "" {
		t.Fatalf("local mutation Access-Control-Allow-Origin = %q, want unset", got)
	}

	crossOriginRequest := httptest.NewRequest(http.MethodPost, "http://127.0.0.1:3000/api/splunk/free-account", strings.NewReader(body))
	crossOriginRequest.RemoteAddr = "127.0.0.1:54321"
	crossOriginRequest.Header.Set("Origin", "https://attacker.example")
	crossOriginRequest.Header.Set("Sec-Fetch-Site", "cross-site")
	crossOriginResponse := httptest.NewRecorder()
	mux.ServeHTTP(crossOriginResponse, crossOriginRequest)
	if crossOriginResponse.Code != http.StatusForbidden {
		t.Fatalf("cross-origin request status = %d, want %d; body=%s", crossOriginResponse.Code, http.StatusForbidden, crossOriginResponse.Body.String())
	}
	if submitter.calls != 1 {
		t.Fatalf("cross-origin request reached submitter; calls = %d, want 1", submitter.calls)
	}
	if got := crossOriginResponse.Header().Get("Access-Control-Allow-Origin"); got != "" {
		t.Fatalf("cross-origin mutation Access-Control-Allow-Origin = %q, want unset", got)
	}
}

func TestFreeAccountEndpointForwardsExactLocalRequest(t *testing.T) {
	submitter := &fakeFreeAccountSubmitter{result: freeaccount.Result{
		IntakeAcknowledged: true,
		Realm:              "eu0",
		Region:             "Europe (Ireland)",
		Message:            "Thank you for registering. Your free edition account is on its way!",
	}}
	mux := http.NewServeMux()
	Register(mux, store.New(), submitter)

	requestBody := `{"firstName":"Ada","lastName":"Lovelace","email":"ada@example.com","region":"Europe (Ireland)","termsAccepted":true}`
	request := localFreeAccountRequest(http.MethodPost, "/api/splunk/free-account", strings.NewReader(requestBody))
	response := httptest.NewRecorder()
	mux.ServeHTTP(response, request)
	if response.Code != http.StatusAccepted {
		t.Fatalf("status = %d, body=%s", response.Code, response.Body.String())
	}
	if submitter.calls != 1 {
		t.Fatalf("submitter calls = %d, want 1", submitter.calls)
	}
	want := freeaccount.Request{
		FirstName:     "Ada",
		LastName:      "Lovelace",
		Email:         "ada@example.com",
		Region:        "Europe (Ireland)",
		TermsAccepted: true,
	}
	if submitter.request != want {
		t.Fatalf("request = %+v, want %+v", submitter.request, want)
	}
	var result freeaccount.Result
	if err := json.Unmarshal(response.Body.Bytes(), &result); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if result != submitter.result {
		t.Fatalf("result = %+v, want %+v", result, submitter.result)
	}
	var payload map[string]any
	if err := json.Unmarshal(response.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode response fields: %v", err)
	}
	if len(payload) != 4 {
		t.Fatalf("response fields = %#v, want only intakeAcknowledged, realm, region, and message", payload)
	}
	if response.Header().Get("Cache-Control") != "no-store" {
		t.Fatalf("Cache-Control = %q", response.Header().Get("Cache-Control"))
	}
}

func TestFreeAccountEndpointPreservesPendingAccountSetupResult(t *testing.T) {
	submitter := &fakeFreeAccountSubmitter{result: freeaccount.Result{
		IntakeAcknowledged:  true,
		AccountSetupPending: true,
		Realm:               "eu0",
		Region:              "Europe (Ireland)",
		Message:             "Splunk needs extra time to finish setting up the account.",
	}}
	mux := http.NewServeMux()
	Register(mux, store.New(), submitter)
	request := localFreeAccountRequest(
		http.MethodPost,
		"/api/splunk/free-account",
		strings.NewReader(`{"firstName":"Ada","lastName":"Lovelace","email":"ada@example.com","termsAccepted":true}`),
	)
	response := httptest.NewRecorder()
	mux.ServeHTTP(response, request)

	if response.Code != http.StatusAccepted {
		t.Fatalf("status = %d, body=%s", response.Code, response.Body.String())
	}
	var payload map[string]any
	if err := json.Unmarshal(response.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if payload["intakeAcknowledged"] != true || payload["accountSetupPending"] != true {
		t.Fatalf("pending setup response = %#v", payload)
	}
}

func TestFreeAccountRegionEndpointReturnsOnlyRegionForLocalRequest(t *testing.T) {
	submitter := &fakeFreeAccountSubmitter{regionResult: freeaccount.RegionResult{Region: "Europe (Ireland)"}}
	mux := http.NewServeMux()
	Register(mux, store.New(), submitter)

	request := localFreeAccountRequest(http.MethodGet, "/api/splunk/free-account/region", nil)
	response := httptest.NewRecorder()
	mux.ServeHTTP(response, request)
	if response.Code != http.StatusOK || submitter.detectionCalls != 1 {
		t.Fatalf("authorized response=%d calls=%d body=%s", response.Code, submitter.detectionCalls, response.Body.String())
	}
	var payload map[string]any
	if err := json.Unmarshal(response.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if len(payload) != 1 || payload["region"] != "Europe (Ireland)" {
		t.Fatalf("payload = %#v, want only region", payload)
	}
	if response.Header().Get("Cache-Control") != "no-store" {
		t.Fatalf("Cache-Control = %q", response.Header().Get("Cache-Control"))
	}
}

func TestFreeAccountEndpointRejectsLegacyRealmRegion(t *testing.T) {
	submitter := freeaccount.New(freeaccount.Config{GeoURL: ":", SignupURL: ":"})
	mux := http.NewServeMux()
	Register(mux, store.New(), submitter)

	request := localFreeAccountRequest(
		http.MethodPost,
		"/api/splunk/free-account",
		strings.NewReader(`{"firstName":"Ada","lastName":"Lovelace","email":"ada@example.com","region":"eu0","termsAccepted":true}`),
	)
	response := httptest.NewRecorder()
	mux.ServeHTTP(response, request)

	if response.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, body=%s", response.Code, response.Body.String())
	}
	assertFreeAccountErrorResponse(t, response, string(freeaccount.ErrorCodeValidation), true)
}

func TestFreeAccountEndpointIsOnlyRegisteredWhenInjected(t *testing.T) {
	mux := http.NewServeMux()
	Register(mux, store.New())
	response := httptest.NewRecorder()
	mux.ServeHTTP(response, localFreeAccountRequest(http.MethodPost, "/api/splunk/free-account", strings.NewReader(`{}`)))
	if response.Code != http.StatusMethodNotAllowed {
		t.Fatalf("status = %d, want 405 with no POST route", response.Code)
	}
}

func TestFreeAccountEndpointRejectsUnknownAndCallerControlledLocationFields(t *testing.T) {
	for _, field := range []string{
		`"company":"not-allowed"`,
		`"realm":"eu0"`,
		`"publicIp":"8.8.8.8"`,
		`"clientIpLookupAttempted":true`,
		`"fullName":"Ada Lovelace"`,
	} {
		t.Run(field, func(t *testing.T) {
			submitter := &fakeFreeAccountSubmitter{}
			mux := http.NewServeMux()
			Register(mux, store.New(), submitter)
			request := localFreeAccountRequest(
				http.MethodPost,
				"/api/splunk/free-account",
				strings.NewReader(`{"firstName":"Ada","lastName":"Lovelace","email":"ada@example.com","termsAccepted":true,`+field+`}`),
			)
			response := httptest.NewRecorder()
			mux.ServeHTTP(response, request)
			if response.Code != http.StatusBadRequest || submitter.calls != 0 {
				t.Fatalf("response=%d calls=%d body=%s", response.Code, submitter.calls, response.Body.String())
			}
			assertFreeAccountErrorResponse(t, response, "invalid_request", true)
		})
	}
}

func TestFreeAccountEndpointMapsSafeSignupErrors(t *testing.T) {
	tests := []struct {
		name       string
		err        error
		wantStatus int
		wantCode   string
		wantRetry  bool
	}{
		{name: "validation", err: &freeaccount.Error{Code: freeaccount.ErrorCodeValidation, Message: "validation", RetrySafe: true}, wantStatus: http.StatusBadRequest, wantCode: "validation_error", wantRetry: true},
		{name: "rejected", err: &freeaccount.Error{Code: freeaccount.ErrorCodeRejected, Message: "rejected", RetrySafe: true}, wantStatus: http.StatusUnprocessableEntity, wantCode: "submission_rejected", wantRetry: true},
		{name: "preparation", err: &freeaccount.Error{Code: freeaccount.ErrorCodePreparation, Message: "preparation", RetrySafe: true}, wantStatus: http.StatusServiceUnavailable, wantCode: "submission_preparation_failed", wantRetry: true},
		{name: "unknown", err: &freeaccount.Error{Code: freeaccount.ErrorCodeOutcomeUnknown, Message: "unknown", RetrySafe: false}, wantStatus: http.StatusBadGateway, wantCode: "outcome_unknown", wantRetry: false},
		{name: "canceled before send", err: &freeaccount.Error{Code: freeaccount.ErrorCodeCanceled, Message: "canceled", RetrySafe: true}, wantStatus: http.StatusRequestTimeout, wantCode: "request_canceled", wantRetry: true},
		{name: "internal error is redacted", err: errors.New("PII secret.person@example.com"), wantStatus: http.StatusInternalServerError, wantCode: "internal_error", wantRetry: false},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			submitter := &fakeFreeAccountSubmitter{err: test.err}
			mux := http.NewServeMux()
			Register(mux, store.New(), submitter)
			request := localFreeAccountRequest(http.MethodPost, "/api/splunk/free-account", strings.NewReader(`{"firstName":"Ada","lastName":"Lovelace","email":"ada@example.com","termsAccepted":true}`))
			response := httptest.NewRecorder()
			mux.ServeHTTP(response, request)
			if response.Code != test.wantStatus {
				t.Fatalf("status = %d, want %d; body=%s", response.Code, test.wantStatus, response.Body.String())
			}
			assertFreeAccountErrorResponse(t, response, test.wantCode, test.wantRetry)
			if strings.Contains(response.Body.String(), "secret.person@example.com") {
				t.Fatalf("response exposed internal error: %s", response.Body.String())
			}
		})
	}
}

func assertFreeAccountErrorResponse(t *testing.T, response *httptest.ResponseRecorder, code string, retrySafe bool) {
	t.Helper()
	var payload freeAccountErrorResponse
	if err := json.Unmarshal(response.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode error response: %v; body=%s", err, response.Body.String())
	}
	if payload.Code != code || payload.Error == "" || payload.RetrySafe != retrySafe {
		t.Fatalf("error payload = %+v, want code=%q retrySafe=%t", payload, code, retrySafe)
	}
}
