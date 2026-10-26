package api

import (
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/signalfx/obstudio/observer/internal/configmanager"
	"github.com/signalfx/obstudio/observer/internal/configmanager/configmanagertest"
	"github.com/signalfx/obstudio/observer/internal/store"
)

func newConfigTestMux(manager configmanager.ConfigManager) *http.ServeMux {
	mux := http.NewServeMux()
	if manager == nil {
		Register(mux, store.New())
	} else {
		Register(mux, store.New(), manager)
	}
	return mux
}

func newConfigTestMock() *configmanagertest.Mock {
	return configmanagertest.New(map[string]any{
		"splunk.realm":  "us1",
		"splunk.export": false,
		"ui.port":       float64(17900),
	}).WithValidator("ui.port", func(value any) error {
		port, ok := value.(float64)
		if !ok || port < 1024 || port > 65535 {
			return errors.New("port must be a number between 1024 and 65535")
		}
		return nil
	})
}

func configRequest(method, target, body string) *http.Request {
	request := httptest.NewRequest(method, target, strings.NewReader(body))
	request.RemoteAddr = "127.0.0.1:54321"
	return request
}

func serveConfig(mux *http.ServeMux, request *http.Request) *httptest.ResponseRecorder {
	response := httptest.NewRecorder()
	mux.ServeHTTP(response, request)
	return response
}

func decodeConfigBody(t *testing.T, response *httptest.ResponseRecorder) map[string]any {
	t.Helper()
	var body map[string]any
	if err := json.Unmarshal(response.Body.Bytes(), &body); err != nil {
		t.Fatalf("response is not a JSON object: %v; body=%s", err, response.Body.String())
	}
	return body
}

func TestConfigRoutesAbsentWithoutManager(t *testing.T) {
	mux := newConfigTestMux(nil)
	for _, request := range []*http.Request{
		configRequest(http.MethodGet, "/api/config", ""),
		configRequest(http.MethodGet, "/api/config/ui.port", ""),
		configRequest(http.MethodPut, "/api/config/ui.port", `{"value": 1}`),
	} {
		// 405 rather than 404: the existing OPTIONS /api/ preflight pattern
		// matches every path under /api/, so the mux reports a method mismatch.
		if code := serveConfig(mux, request).Code; code != http.StatusNotFound && code != http.StatusMethodNotAllowed {
			t.Errorf("%s %s status = %d, want 404 or 405 when no ConfigManager is registered", request.Method, request.URL.Path, code)
		}
	}
}

func TestConfigGetAllReturnsNestedValues(t *testing.T) {
	response := serveConfig(newConfigTestMux(newConfigTestMock()), configRequest(http.MethodGet, "/api/config", ""))
	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d; body=%s", response.Code, http.StatusOK, response.Body.String())
	}
	if got := response.Header().Get("Access-Control-Allow-Origin"); got != "" {
		t.Errorf("Access-Control-Allow-Origin = %q, want none: config must not be readable cross-origin", got)
	}
	if got := response.Header().Get("Cache-Control"); got != "no-store" {
		t.Errorf("Cache-Control = %q, want no-store", got)
	}
	values, _ := decodeConfigBody(t, response)["values"].(map[string]any)
	splunk, _ := values["splunk"].(map[string]any)
	if splunk["realm"] != "us1" || splunk["export"] != false {
		t.Errorf("values.splunk = %#v, want realm=us1 export=false", splunk)
	}
}

func TestConfigGetByKey(t *testing.T) {
	mux := newConfigTestMux(newConfigTestMock())
	tests := []struct {
		name string
		key  string
		want any
	}{
		{"leaf string", "splunk.realm", "us1"},
		{"leaf number", "ui.port", float64(17900)},
		{"section", "splunk", map[string]any{"realm": "us1", "export": false}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			response := serveConfig(mux, configRequest(http.MethodGet, "/api/config/"+test.key, ""))
			if response.Code != http.StatusOK {
				t.Fatalf("status = %d, want %d; body=%s", response.Code, http.StatusOK, response.Body.String())
			}
			body := decodeConfigBody(t, response)
			if body["key"] != test.key {
				t.Errorf("key = %v, want %s", body["key"], test.key)
			}
			if fmt.Sprint(body["value"]) != fmt.Sprint(test.want) {
				t.Errorf("value = %v, want %v", body["value"], test.want)
			}
		})
	}
}

func TestConfigGetUnknownKeyReturnsNotFound(t *testing.T) {
	response := serveConfig(newConfigTestMux(newConfigTestMock()), configRequest(http.MethodGet, "/api/config/splunk.nope", ""))
	if response.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want %d", response.Code, http.StatusNotFound)
	}
	if code := decodeConfigBody(t, response)["code"]; code != "unknown_key" {
		t.Errorf("code = %v, want unknown_key", code)
	}
}

func TestConfigPutPersistsAndReturnsStoredValue(t *testing.T) {
	mock := newConfigTestMock()
	mux := newConfigTestMux(mock)

	response := serveConfig(mux, configRequest(http.MethodPut, "/api/config/ui.port", `{"value": 18000}`))
	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d; body=%s", response.Code, http.StatusOK, response.Body.String())
	}
	body := decodeConfigBody(t, response)
	if body["key"] != "ui.port" || body["value"] != float64(18000) {
		t.Errorf("body = %#v, want key=ui.port value=18000", body)
	}
	calls := mock.SetCalls()
	if len(calls) != 1 || calls[0].Key != "ui.port" || calls[0].Value != float64(18000) {
		t.Fatalf("Set calls = %#v, want one call for ui.port=18000", calls)
	}

	read := serveConfig(mux, configRequest(http.MethodGet, "/api/config/ui.port", ""))
	if got := decodeConfigBody(t, read)["value"]; got != float64(18000) {
		t.Errorf("GET after PUT value = %v, want 18000", got)
	}
}

func TestConfigPutSupportsNonNumericValues(t *testing.T) {
	mock := newConfigTestMock()
	mux := newConfigTestMux(mock)
	for _, body := range []string{`{"value": "eu0"}`, `{"value": true}`, `{"value": null}`} {
		response := serveConfig(mux, configRequest(http.MethodPut, "/api/config/splunk.realm", body))
		if response.Code != http.StatusOK {
			t.Errorf("PUT %s status = %d, want %d; body=%s", body, response.Code, http.StatusOK, response.Body.String())
		}
	}
	if got := len(mock.SetCalls()); got != 3 {
		t.Errorf("Set calls = %d, want 3 (null is passed to the manager, which decides)", got)
	}
}

func TestConfigPutRejectedValueReturnsUnprocessableAndLeavesConfigUnchanged(t *testing.T) {
	mock := newConfigTestMock()
	mux := newConfigTestMux(mock)

	response := serveConfig(mux, configRequest(http.MethodPut, "/api/config/ui.port", `{"value": 80}`))
	if response.Code != http.StatusUnprocessableEntity {
		t.Fatalf("status = %d, want %d; body=%s", response.Code, http.StatusUnprocessableEntity, response.Body.String())
	}
	body := decodeConfigBody(t, response)
	if body["code"] != "invalid_value" || body["key"] != "ui.port" ||
		!strings.Contains(fmt.Sprint(body["error"]), "between 1024 and 65535") {
		t.Errorf("body = %#v, want invalid_value with the validation message", body)
	}
	if len(mock.SetCalls()) != 0 {
		t.Errorf("Set calls = %#v, want none for a rejected value", mock.SetCalls())
	}
}

func TestConfigPutUnknownKeyReturnsNotFound(t *testing.T) {
	response := serveConfig(newConfigTestMux(newConfigTestMock()), configRequest(http.MethodPut, "/api/config/splunk.nope", `{"value": 1}`))
	if response.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want %d", response.Code, http.StatusNotFound)
	}
}

func TestConfigPutRejectsMalformedRequests(t *testing.T) {
	mock := newConfigTestMock()
	mux := newConfigTestMux(mock)
	tests := []struct {
		name string
		body string
	}{
		{"not json", `nope`},
		{"empty body", ``},
		{"missing value", `{}`},
		{"unknown field", `{"value": 1, "extra": true}`},
		{"trailing data", `{"value": 1} {"value": 2}`},
		{"bare value", `18000`},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			response := serveConfig(mux, configRequest(http.MethodPut, "/api/config/ui.port", test.body))
			if response.Code != http.StatusBadRequest {
				t.Fatalf("status = %d, want %d; body=%s", response.Code, http.StatusBadRequest, response.Body.String())
			}
			if code := decodeConfigBody(t, response)["code"]; code != "invalid_request" {
				t.Errorf("code = %v, want invalid_request", code)
			}
		})
	}
	if len(mock.SetCalls()) != 0 {
		t.Errorf("Set calls = %#v, want none for malformed requests", mock.SetCalls())
	}
}

func TestConfigRejectsInvalidKeySyntax(t *testing.T) {
	mux := newConfigTestMux(newConfigTestMock())
	for _, key := range []string{"a..b", ".a", "a.", "a%20b", "a%3Bb", strings.Repeat("a", maxConfigKeyLength+1)} {
		for _, method := range []string{http.MethodGet, http.MethodPut} {
			response := serveConfig(mux, configRequest(method, "/api/config/"+key, `{"value": 1}`))
			if response.Code != http.StatusBadRequest {
				t.Errorf("%s key %q status = %d, want %d", method, key, response.Code, http.StatusBadRequest)
			}
			if code := decodeConfigBody(t, response)["code"]; code != "invalid_key" {
				t.Errorf("%s key %q code = %v, want invalid_key", method, key, code)
			}
		}
	}
}

func TestConfigManagerFailuresReturnInternalErrorWithoutLeakingDetail(t *testing.T) {
	secret := "disk full writing /home/someone/.obstudio/config.yaml token=abc123"
	var logged strings.Builder
	previousWriter := log.Writer()
	log.SetOutput(&logged)
	defer log.SetOutput(previousWriter)

	mock := newConfigTestMock()
	mux := newConfigTestMux(mock)
	mock.FailGetWith(errors.New(secret))
	mock.FailSetWith(errors.New(secret))

	for _, request := range []*http.Request{
		configRequest(http.MethodGet, "/api/config", ""),
		configRequest(http.MethodGet, "/api/config/ui.port", ""),
		configRequest(http.MethodPut, "/api/config/ui.port", `{"value": 18000}`),
	} {
		response := serveConfig(mux, request)
		if response.Code != http.StatusInternalServerError {
			t.Errorf("%s %s status = %d, want %d", request.Method, request.URL.Path, response.Code, http.StatusInternalServerError)
		}
		if strings.Contains(response.Body.String(), "abc123") || strings.Contains(response.Body.String(), "config.yaml") {
			t.Errorf("%s %s leaked manager error detail: %s", request.Method, request.URL.Path, response.Body.String())
		}
	}
	if !strings.Contains(logged.String(), "abc123") {
		t.Errorf("manager error detail was not logged server-side: %q", logged.String())
	}
}

func TestConfigRoutesRequireLocalObserverRequest(t *testing.T) {
	mock := newConfigTestMock()
	mux := newConfigTestMux(mock)
	tests := []struct {
		name   string
		method string
		target string
		body   string
		mutate func(*http.Request)
	}{
		{"GET from remote address", http.MethodGet, "/api/config", "", func(r *http.Request) { r.RemoteAddr = "203.0.113.5:4000" }},
		{"GET from cross-site origin", http.MethodGet, "/api/config", "", func(r *http.Request) { r.Header.Set("Origin", "https://evil.example") }},
		{"GET key from cross-site origin", http.MethodGet, "/api/config/splunk.realm", "", func(r *http.Request) { r.Header.Set("Origin", "https://evil.example") }},
		{"PUT from remote address", http.MethodPut, "/api/config/ui.port", `{"value": 18000}`, func(r *http.Request) { r.RemoteAddr = "203.0.113.5:4000" }},
		{"PUT from cross-site origin", http.MethodPut, "/api/config/ui.port", `{"value": 18000}`, func(r *http.Request) { r.Header.Set("Origin", "https://evil.example") }},
		{"PUT from cross-site fetch", http.MethodPut, "/api/config/ui.port", `{"value": 18000}`, func(r *http.Request) { r.Header.Set("Sec-Fetch-Site", "cross-site") }},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			request := configRequest(test.method, test.target, test.body)
			test.mutate(request)
			response := serveConfig(mux, request)
			if response.Code != http.StatusForbidden {
				t.Fatalf("status = %d, want %d; body=%s", response.Code, http.StatusForbidden, response.Body.String())
			}
		})
	}
	if len(mock.SetCalls()) != 0 {
		t.Errorf("Set calls = %#v, want none for forbidden requests", mock.SetCalls())
	}
}

func TestConfigRoutesAcceptSameOriginBrowserRequest(t *testing.T) {
	mux := newConfigTestMux(newConfigTestMock())
	request := configRequest(http.MethodPut, "/api/config/ui.port", `{"value": 18000}`)
	request.Host = "127.0.0.1:17900"
	request.Header.Set("Origin", "http://127.0.0.1:17900")
	request.Header.Set("Sec-Fetch-Site", "same-origin")
	request.Header.Set(splunkBrowserRequestHeader, "1")
	response := serveConfig(mux, request)
	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d; body=%s", response.Code, http.StatusOK, response.Body.String())
	}
}

func TestConfigPatchAppliesNestedValuesAtomicallyAndReturnsFullConfig(t *testing.T) {
	mock := newConfigTestMock()
	mux := newConfigTestMux(mock)

	response := serveConfig(mux, configRequest(http.MethodPatch, "/api/config",
		`{"ui": {"port": 18000}, "splunk": {"realm": "eu0", "export": true}}`))
	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d; body=%s", response.Code, http.StatusOK, response.Body.String())
	}
	if got := response.Header().Get("Access-Control-Allow-Origin"); got != "" {
		t.Errorf("Access-Control-Allow-Origin = %q, want none", got)
	}
	values, _ := decodeConfigBody(t, response)["values"].(map[string]any)
	ui, _ := values["ui"].(map[string]any)
	splunk, _ := values["splunk"].(map[string]any)
	if ui["port"] != float64(18000) || splunk["realm"] != "eu0" || splunk["export"] != true {
		t.Errorf("values = %#v, want the full updated configuration", values)
	}
	if got := len(mock.SetCalls()); got != 3 {
		t.Errorf("Set calls = %d, want 3 (ui.port, splunk.realm, splunk.export)", got)
	}
}

func TestConfigPatchRejectsEverythingWhenAnyValueIsInvalid(t *testing.T) {
	mock := newConfigTestMock()
	mux := newConfigTestMux(mock)

	response := serveConfig(mux, configRequest(http.MethodPatch, "/api/config",
		`{"ui": {"port": 80}, "splunk": {"realm": "eu0", "nope": 1}}`))
	if response.Code != http.StatusUnprocessableEntity {
		t.Fatalf("status = %d, want %d; body=%s", response.Code, http.StatusUnprocessableEntity, response.Body.String())
	}
	body := decodeConfigBody(t, response)
	if body["code"] != "invalid_value" {
		t.Errorf("code = %v, want invalid_value", body["code"])
	}
	fields, _ := body["errors"].([]any)
	if len(fields) != 2 {
		t.Fatalf("errors = %#v, want one entry for ui.port and one for splunk.nope", body["errors"])
	}
	first, _ := fields[0].(map[string]any)
	second, _ := fields[1].(map[string]any)
	if first["key"] != "splunk.nope" || second["key"] != "ui.port" {
		t.Errorf("errors = %#v, want entries sorted by key: splunk.nope then ui.port", fields)
	}
	if len(mock.SetCalls()) != 0 {
		t.Errorf("Set calls = %#v, want none: the valid splunk.realm must not be applied", mock.SetCalls())
	}
	read := serveConfig(mux, configRequest(http.MethodGet, "/api/config/splunk.realm", ""))
	if got := decodeConfigBody(t, read)["value"]; got != "us1" {
		t.Errorf("splunk.realm = %v after a rejected PATCH, want us1", got)
	}
}

func TestConfigPatchPassesNullArraysAndEmptyObjectsToManagerAsValues(t *testing.T) {
	mock := configmanagertest.New(map[string]any{"a.null": "x", "a.list": "x", "a.empty": "x"})
	mux := newConfigTestMux(mock)

	response := serveConfig(mux, configRequest(http.MethodPatch, "/api/config",
		`{"a": {"null": null, "list": [1, 2], "empty": {}}}`))
	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d; body=%s", response.Code, http.StatusOK, response.Body.String())
	}
	got := map[string]string{}
	for _, call := range mock.SetCalls() {
		got[call.Key] = fmt.Sprintf("%#v", call.Value)
	}
	want := map[string]string{
		"a.null":  "<nil>",
		"a.list":  `[]interface {}{1, 2}`,
		"a.empty": `map[string]interface {}{}`,
	}
	for key, value := range want {
		if got[key] != value {
			t.Errorf("value for %s = %s, want %s", key, got[key], value)
		}
	}
}

func TestConfigPatchRejectsMalformedRequests(t *testing.T) {
	mock := newConfigTestMock()
	mux := newConfigTestMux(mock)
	tooMany := make([]string, 0, maxConfigPatchValues+1)
	for i := 0; i <= maxConfigPatchValues; i++ {
		tooMany = append(tooMany, fmt.Sprintf(`"k%d": 1`, i))
	}
	tests := []struct {
		name string
		body string
		code string
	}{
		{"not json", `nope`, "invalid_request"},
		{"empty body", ``, "invalid_request"},
		{"empty object", `{}`, "invalid_request"},
		{"null body", `null`, "invalid_request"},
		{"array body", `[1]`, "invalid_request"},
		{"scalar body", `18000`, "invalid_request"},
		{"trailing data", `{"a": 1} {"b": 2}`, "invalid_request"},
		{"dotted segment", `{"ui.port": 18000}`, "invalid_key"},
		{"empty segment", `{"": 1}`, "invalid_key"},
		{"bad characters", `{"ui": {"po rt": 1}}`, "invalid_key"},
		{"too many values", "{" + strings.Join(tooMany, ",") + "}", "invalid_key"},
		{"overlong key", `{"` + strings.Repeat("a", maxConfigKeyLength+1) + `": 1}`, "invalid_key"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			response := serveConfig(mux, configRequest(http.MethodPatch, "/api/config", test.body))
			if response.Code != http.StatusBadRequest {
				t.Fatalf("status = %d, want %d; body=%s", response.Code, http.StatusBadRequest, response.Body.String())
			}
			if code := decodeConfigBody(t, response)["code"]; code != test.code {
				t.Errorf("code = %v, want %s", code, test.code)
			}
		})
	}
	if len(mock.SetCalls()) != 0 {
		t.Errorf("Set calls = %#v, want none for malformed requests", mock.SetCalls())
	}
}

func TestConfigPatchManagerFailureReturnsInternalErrorWithoutLeakingDetail(t *testing.T) {
	previousWriter := log.Writer()
	log.SetOutput(&strings.Builder{})
	defer log.SetOutput(previousWriter)

	mock := newConfigTestMock()
	mux := newConfigTestMux(mock)
	mock.FailSetWith(errors.New("disk full writing /home/someone/.obstudio/config.yaml token=abc123"))

	response := serveConfig(mux, configRequest(http.MethodPatch, "/api/config", `{"ui": {"port": 18000}}`))
	if response.Code != http.StatusInternalServerError {
		t.Fatalf("status = %d, want %d", response.Code, http.StatusInternalServerError)
	}
	if strings.Contains(response.Body.String(), "abc123") || strings.Contains(response.Body.String(), "config.yaml") {
		t.Errorf("leaked manager error detail: %s", response.Body.String())
	}
}

func TestConfigPatchRequiresLocalObserverRequest(t *testing.T) {
	mock := newConfigTestMock()
	mux := newConfigTestMux(mock)
	for name, mutate := range map[string]func(*http.Request){
		"remote address":    func(r *http.Request) { r.RemoteAddr = "203.0.113.5:4000" },
		"cross-site origin": func(r *http.Request) { r.Header.Set("Origin", "https://evil.example") },
		"cross-site fetch":  func(r *http.Request) { r.Header.Set("Sec-Fetch-Site", "cross-site") },
	} {
		request := configRequest(http.MethodPatch, "/api/config", `{"ui": {"port": 18000}}`)
		mutate(request)
		if code := serveConfig(mux, request).Code; code != http.StatusForbidden {
			t.Errorf("PATCH from %s status = %d, want %d", name, code, http.StatusForbidden)
		}
	}
	if len(mock.SetCalls()) != 0 {
		t.Errorf("Set calls = %#v, want none for forbidden requests", mock.SetCalls())
	}
}

func int64Pointer(value int64) *int64 { return &value }

func newConfigSchemaTestMock() *configmanagertest.Mock {
	return configmanagertest.New(map[string]any{
		"ui.port":       float64(17900),
		"logging.level": "info",
		"splunk.export": false,
		"splunk.realm":  "us1",
	}).
		WithSpec(configmanager.KeySpec{Key: "ui.port", Type: configmanager.TypeInteger, Minimum: int64Pointer(1024), Maximum: int64Pointer(65535)}).
		WithSpec(configmanager.KeySpec{
			Key: "logging.level", Type: configmanager.TypeString, AllowedValues: []any{"debug", "info", "warn", "error"},
			Label: "Log level", Description: "How much detail is written to the log.",
		}).
		WithSpec(configmanager.KeySpec{Key: "splunk.export", Type: configmanager.TypeBoolean})
}

func TestConfigSchemaListsEveryKeyWithTypeAndConstraints(t *testing.T) {
	response := serveConfig(newConfigTestMux(newConfigSchemaTestMock()), configRequest(http.MethodGet, "/api/config/schema", ""))
	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d; body=%s", response.Code, http.StatusOK, response.Body.String())
	}
	if got := response.Header().Get("Access-Control-Allow-Origin"); got != "" {
		t.Errorf("Access-Control-Allow-Origin = %q, want none", got)
	}
	var body struct {
		Keys []map[string]any `json:"keys"`
	}
	if err := json.Unmarshal(response.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode: %v; body=%s", err, response.Body.String())
	}
	keys := make([]string, 0, len(body.Keys))
	byKey := map[string]map[string]any{}
	for _, spec := range body.Keys {
		keys = append(keys, spec["key"].(string))
		byKey[spec["key"].(string)] = spec
	}
	if got, want := strings.Join(keys, ","), "logging.level,splunk.export,splunk.realm,ui.port"; got != want {
		t.Fatalf("keys = %s, want %s (sorted)", got, want)
	}

	port := byKey["ui.port"]
	if port["type"] != "integer" || port["minimum"] != float64(1024) || port["maximum"] != float64(65535) {
		t.Errorf("ui.port spec = %#v, want integer 1024..65535", port)
	}
	level := byKey["logging.level"]
	if allowed, _ := level["allowedValues"].([]any); level["type"] != "string" || fmt.Sprint(allowed) != "[debug info warn error]" {
		t.Errorf("logging.level spec = %#v, want string enum", level)
	}
	if export := byKey["splunk.export"]; export["type"] != "boolean" {
		t.Errorf("splunk.export spec = %#v, want boolean", export)
	}
	// A key with no declared spec still appears, typed from its value, with no
	// constraint fields at all.
	realm := byKey["splunk.realm"]
	if realm["type"] != "string" || realm["allowedValues"] != nil || realm["minimum"] != nil || realm["maximum"] != nil ||
		realm["label"] != nil || realm["description"] != nil {
		t.Errorf("splunk.realm spec = %#v, want a bare string spec", realm)
	}
	if level["label"] != "Log level" || level["description"] != "How much detail is written to the log." {
		t.Errorf("logging.level spec = %#v, want its label and description passed through", level)
	}
}

func TestConfigSchemaIsNotShadowedByKeyLookup(t *testing.T) {
	mux := newConfigTestMux(newConfigSchemaTestMock())
	body := decodeConfigBody(t, serveConfig(mux, configRequest(http.MethodGet, "/api/config/schema", "")))
	if _, ok := body["keys"]; !ok {
		t.Errorf("GET /api/config/schema = %#v, want the schema, not a key lookup", body)
	}
}

func TestConfigSchemaEmptyReturnsEmptyArray(t *testing.T) {
	mux := newConfigTestMux(configmanagertest.New(nil))
	response := serveConfig(mux, configRequest(http.MethodGet, "/api/config/schema", ""))
	if response.Code != http.StatusOK || strings.TrimSpace(response.Body.String()) != `{"keys":[]}` {
		t.Errorf("status=%d body=%s, want 200 {\"keys\":[]}", response.Code, response.Body.String())
	}
}

func TestConfigSchemaRequiresLocalRequestAndHidesManagerErrors(t *testing.T) {
	previousWriter := log.Writer()
	log.SetOutput(&strings.Builder{})
	defer log.SetOutput(previousWriter)

	mock := newConfigSchemaTestMock()
	mux := newConfigTestMux(mock)

	forbidden := configRequest(http.MethodGet, "/api/config/schema", "")
	forbidden.Header.Set("Origin", "https://evil.example")
	if code := serveConfig(mux, forbidden).Code; code != http.StatusForbidden {
		t.Errorf("cross-site status = %d, want %d", code, http.StatusForbidden)
	}

	mock.FailGetWith(errors.New("reading /home/someone/.obstudio/config.yaml: token=abc123"))
	response := serveConfig(mux, configRequest(http.MethodGet, "/api/config/schema", ""))
	if response.Code != http.StatusInternalServerError {
		t.Fatalf("status = %d, want %d", response.Code, http.StatusInternalServerError)
	}
	if strings.Contains(response.Body.String(), "abc123") || strings.Contains(response.Body.String(), "config.yaml") {
		t.Errorf("leaked manager error detail: %s", response.Body.String())
	}
}

func TestConfigSpecsAreEnforcedOnPutAndPatch(t *testing.T) {
	mux := newConfigTestMux(newConfigSchemaTestMock())
	tests := []struct {
		name, method, target, body, wantFragment string
	}{
		{"PUT wrong type", http.MethodPut, "/api/config/ui.port", `{"value": "18000"}`, "whole number"},
		{"PUT fractional", http.MethodPut, "/api/config/ui.port", `{"value": 18000.5}`, "whole number"},
		{"PUT out of range", http.MethodPut, "/api/config/ui.port", `{"value": 70000}`, "between 1024 and 65535"},
		{"PUT not in enum", http.MethodPut, "/api/config/logging.level", `{"value": "loud"}`, "one of: debug, info, warn, error"},
		{"PUT not a boolean", http.MethodPut, "/api/config/splunk.export", `{"value": "yes"}`, "true or false"},
		{"PATCH out of range", http.MethodPatch, "/api/config", `{"ui": {"port": 80}}`, "between 1024 and 65535"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			response := serveConfig(mux, configRequest(test.method, test.target, test.body))
			if response.Code != http.StatusUnprocessableEntity || !strings.Contains(response.Body.String(), test.wantFragment) {
				t.Fatalf("status = %d body=%s, want 422 containing %q", response.Code, response.Body.String(), test.wantFragment)
			}
		})
	}
	ok := serveConfig(mux, configRequest(http.MethodPut, "/api/config/logging.level", `{"value": "debug"}`))
	if ok.Code != http.StatusOK {
		t.Errorf("valid enum value status = %d, want %d; body=%s", ok.Code, http.StatusOK, ok.Body.String())
	}
}
