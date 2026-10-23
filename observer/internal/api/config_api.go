package api

import (
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net/http"
	"regexp"
	"sort"

	"github.com/signalfx/obstudio/observer/internal/configmanager"
)

const (
	maxConfigKeyLength   = 256
	maxConfigPatchValues = 256
)

// configKeyPattern is the syntax of a dotted config key. Whether the key
// exists, and whether a value is acceptable, is the ConfigManager's decision.
var configKeyPattern = regexp.MustCompile(`^[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+)*$`)

// configSegmentPattern is one level of a nested PATCH body. Dots are excluded
// so {"a.b": 1} cannot be confused with {"a": {"b": 1}}.
var configSegmentPattern = regexp.MustCompile(`^[A-Za-z0-9_-]+$`)

type configAPI struct {
	manager configmanager.ConfigManager
}

type configErrorResponse struct {
	Code   string             `json:"code"`
	Error  string             `json:"error"`
	Key    string             `json:"key,omitempty"`
	Errors []configFieldError `json:"errors,omitempty"`
}

type configFieldError struct {
	Key   string `json:"key"`
	Error string `json:"error"`
}

type configSchemaResponse struct {
	Keys []configmanager.KeySpec `json:"keys"`
}

type configValuesResponse struct {
	Values map[string]any `json:"values"`
}

type configValueResponse struct {
	Key   string `json:"key"`
	Value any    `json:"value"`
}

func newConfigAPI(manager configmanager.ConfigManager) *configAPI {
	return &configAPI{manager: manager}
}

func (a *configAPI) register(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/config", a.authorize(a.getAll))
	mux.HandleFunc("PATCH /api/config", a.authorize(a.patch))
	// A literal path outranks the {key} wildcard below, so a top-level config
	// key literally named "schema" cannot be fetched individually.
	mux.HandleFunc("GET /api/config/schema", a.authorize(a.schema))
	mux.HandleFunc("GET /api/config/{key}", a.authorize(a.get))
	mux.HandleFunc("PUT /api/config/{key}", a.authorize(a.put))
}

func (a *configAPI) getAll(w http.ResponseWriter, r *http.Request) {
	values, err := a.manager.GetAll(r.Context())
	if err != nil {
		a.writeManagerError(w, "", "read", err)
		return
	}
	if values == nil {
		values = map[string]any{}
	}
	writeSameOriginJSON(w, configValuesResponse{Values: values})
}

// schema lists every settable key with its type and constraints, as declared by
// the ConfigManager so it cannot drift from what the manager validates.
func (a *configAPI) schema(w http.ResponseWriter, r *http.Request) {
	specs, err := a.manager.Schema(r.Context())
	if err != nil {
		a.writeManagerError(w, "", "read", err)
		return
	}
	keys := append([]configmanager.KeySpec{}, specs...)
	sort.Slice(keys, func(i, j int) bool { return keys[i].Key < keys[j].Key })
	writeSameOriginJSON(w, configSchemaResponse{Keys: keys})
}

func (a *configAPI) get(w http.ResponseWriter, r *http.Request) {
	key := r.PathValue("key")
	if !validConfigKey(w, key) {
		return
	}
	value, err := a.manager.Get(r.Context(), key)
	if err != nil {
		a.writeManagerError(w, key, "read", err)
		return
	}
	writeSameOriginJSON(w, configValueResponse{Key: key, Value: value})
}

func (a *configAPI) put(w http.ResponseWriter, r *http.Request) {
	key := r.PathValue("key")
	if !validConfigKey(w, key) {
		return
	}
	var body struct {
		Value json.RawMessage `json:"value"`
	}
	if err := decodeStrictJSON(w, r, &body); err != nil {
		writeConfigError(w, http.StatusBadRequest, "invalid_request", err.Error(), key)
		return
	}
	if len(body.Value) == 0 {
		writeConfigError(w, http.StatusBadRequest, "invalid_request", `request body must contain a "value" field`, key)
		return
	}
	var value any
	if err := json.Unmarshal(body.Value, &value); err != nil {
		writeConfigError(w, http.StatusBadRequest, "invalid_request", "invalid JSON request: value is malformed", key)
		return
	}

	if err := a.manager.Set(r.Context(), key, value); err != nil {
		a.writeManagerError(w, key, "update", err)
		return
	}
	stored, err := a.manager.Get(r.Context(), key)
	if err != nil {
		a.writeManagerError(w, key, "read back", err)
		return
	}
	writeSameOriginJSON(w, configValueResponse{Key: key, Value: stored})
}

// patch applies several values at once. The body is shaped like the response of
// GET /api/config; every leaf becomes a dotted key and all leaves are applied
// atomically through SetMany. Unlike RFC 7396 merge patch, null is a value
// handed to the manager, not a deletion, and an empty object is a value too.
func (a *configAPI) patch(w http.ResponseWriter, r *http.Request) {
	var body map[string]any
	if err := decodeStrictJSON(w, r, &body); err != nil {
		writeConfigError(w, http.StatusBadRequest, "invalid_request", err.Error(), "")
		return
	}
	if len(body) == 0 {
		writeConfigError(w, http.StatusBadRequest, "invalid_request", "request body must be a JSON object with at least one value", "")
		return
	}
	values := map[string]any{}
	if err := flattenConfigPatch("", body, values); err != nil {
		writeConfigError(w, http.StatusBadRequest, "invalid_key", err.Error(), "")
		return
	}

	if err := a.manager.SetMany(r.Context(), values); err != nil {
		a.writeManagerError(w, "", "update", err)
		return
	}
	stored, err := a.manager.GetAll(r.Context())
	if err != nil {
		a.writeManagerError(w, "", "read back", err)
		return
	}
	if stored == nil {
		stored = map[string]any{}
	}
	writeSameOriginJSON(w, configValuesResponse{Values: stored})
}

func flattenConfigPatch(prefix string, node map[string]any, out map[string]any) error {
	for name, value := range node {
		if !configSegmentPattern.MatchString(name) {
			return errors.New("configuration key segments may contain only letters, digits, '_' and '-'")
		}
		key := name
		if prefix != "" {
			key = prefix + "." + name
		}
		if len(key) > maxConfigKeyLength {
			return fmt.Errorf("configuration key exceeds %d characters", maxConfigKeyLength)
		}
		if child, ok := value.(map[string]any); ok && len(child) > 0 {
			if err := flattenConfigPatch(key, child, out); err != nil {
				return err
			}
			continue
		}
		out[key] = value
		if len(out) > maxConfigPatchValues {
			return fmt.Errorf("a single request may change at most %d values", maxConfigPatchValues)
		}
	}
	return nil
}

// authorize applies the local-origin boundary to reads as well as writes:
// configuration can hold credentials, so it must not be drivable or readable
// from a remote web origin.
func (a *configAPI) authorize(next http.HandlerFunc) http.HandlerFunc {
	return requireLocalObserverRequest(next, func(w http.ResponseWriter, status int, message string) {
		writeConfigError(w, status, "forbidden", message, "")
	})
}

func (a *configAPI) writeManagerError(w http.ResponseWriter, key, action string, err error) {
	var validationErr *configmanager.ValidationError
	var batchErr *configmanager.ValidationErrors
	switch {
	case errors.As(err, &batchErr):
		fields := make([]configFieldError, 0, len(batchErr.Errors))
		for _, rejected := range batchErr.Errors {
			fields = append(fields, configFieldError{Key: rejected.Key, Error: rejected.Message})
		}
		sort.Slice(fields, func(i, j int) bool { return fields[i].Key < fields[j].Key })
		writeConfigErrorWithFields(w, http.StatusUnprocessableEntity, "invalid_value",
			fmt.Sprintf("%d values were rejected; nothing was changed", len(fields)), fields)
	case errors.Is(err, configmanager.ErrUnknownKey):
		writeConfigError(w, http.StatusNotFound, "unknown_key", "unknown configuration key", key)
	case errors.As(err, &validationErr):
		writeConfigError(w, http.StatusUnprocessableEntity, "invalid_value", validationErr.Message, key)
	default:
		log.Printf("[api] config %s failed: %v", action, err)
		writeConfigError(w, http.StatusInternalServerError, "internal_error", "Could not "+action+" the configuration.", key)
	}
}

func validConfigKey(w http.ResponseWriter, key string) bool {
	if len(key) > maxConfigKeyLength || !configKeyPattern.MatchString(key) {
		writeConfigError(w, http.StatusBadRequest, "invalid_key", "configuration key must be a dotted path such as splunk.realm", "")
		return false
	}
	return true
}

func writeConfigError(w http.ResponseWriter, status int, code, message, key string) {
	writeConfigErrorResponse(w, status, configErrorResponse{Code: code, Error: message, Key: key})
}

func writeConfigErrorWithFields(w http.ResponseWriter, status int, code, message string, fields []configFieldError) {
	writeConfigErrorResponse(w, status, configErrorResponse{Code: code, Error: message, Errors: fields})
}

func writeConfigErrorResponse(w http.ResponseWriter, status int, response configErrorResponse) {
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(response); err != nil {
		log.Printf("[api] writeConfigError: %v", err)
	}
}
