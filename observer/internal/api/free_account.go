package api

import (
	"crypto/subtle"
	"encoding/json"
	"errors"
	"net/http"
	"os"
	"strings"

	"github.com/signalfx/obstudio/observer/internal/freeaccount"
)

type freeAccountAPI struct {
	submitter    freeaccount.Submitter
	controlToken string
}

type freeAccountErrorResponse struct {
	Code      string `json:"code"`
	Error     string `json:"error"`
	RetrySafe bool   `json:"retrySafe"`
}

func newFreeAccountAPI(submitter freeaccount.Submitter) *freeAccountAPI {
	return &freeAccountAPI{
		submitter:    submitter,
		controlToken: strings.TrimSpace(os.Getenv("OBSTUDIO_CONTROL_TOKEN")),
	}
}

func (a *freeAccountAPI) register(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/splunk/free-account/region", a.authorize(a.detectRegion))
	mux.HandleFunc("POST /api/splunk/free-account", a.authorize(a.submit))
}

func (a *freeAccountAPI) detectRegion(w http.ResponseWriter, r *http.Request) {
	result := a.submitter.DetectRegion(r.Context())
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Access-Control-Allow-Origin", "*")
	_ = json.NewEncoder(w).Encode(result)
}

func (a *freeAccountAPI) submit(w http.ResponseWriter, r *http.Request) {
	var request freeaccount.Request
	if err := decodeStrictJSON(w, r, &request); err != nil {
		writeFreeAccountError(w, http.StatusBadRequest, "invalid_request", err.Error(), true)
		return
	}
	result, err := a.submitter.Submit(r.Context(), request)
	if err == nil {
		w.Header().Set("Cache-Control", "no-store")
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.WriteHeader(http.StatusAccepted)
		_ = json.NewEncoder(w).Encode(result)
		return
	}

	var signupErr *freeaccount.Error
	if !errors.As(err, &signupErr) {
		writeFreeAccountError(w, http.StatusInternalServerError, "internal_error", "Could not submit the Free Edition signup.", false)
		return
	}
	status := http.StatusInternalServerError
	switch signupErr.Code {
	case freeaccount.ErrorCodeValidation:
		status = http.StatusBadRequest
	case freeaccount.ErrorCodeRejected:
		status = http.StatusUnprocessableEntity
	case freeaccount.ErrorCodeOutcomeUnknown:
		status = http.StatusBadGateway
	case freeaccount.ErrorCodeCanceled:
		status = http.StatusRequestTimeout
	}
	writeFreeAccountError(w, status, string(signupErr.Code), signupErr.Message, signupErr.RetrySafe)
}

func (a *freeAccountAPI) authorize(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if a.controlToken == "" {
			writeFreeAccountError(w, http.StatusServiceUnavailable, "observer_control_unavailable", "Observer control is not configured.", true)
			return
		}
		const bearerPrefix = "Bearer "
		authorization := r.Header.Get("Authorization")
		if !strings.HasPrefix(authorization, bearerPrefix) {
			writeFreeAccountError(w, http.StatusUnauthorized, "unauthorized", "Missing Observer control token.", true)
			return
		}
		provided := strings.TrimSpace(strings.TrimPrefix(authorization, bearerPrefix))
		if len(provided) != len(a.controlToken) || subtle.ConstantTimeCompare([]byte(provided), []byte(a.controlToken)) != 1 {
			writeFreeAccountError(w, http.StatusUnauthorized, "unauthorized", "Invalid Observer control token.", true)
			return
		}
		next(w, r)
	}
}

func writeFreeAccountError(w http.ResponseWriter, status int, code, message string, retrySafe bool) {
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(freeAccountErrorResponse{
		Code:      code,
		Error:     message,
		RetrySafe: retrySafe,
	})
}
