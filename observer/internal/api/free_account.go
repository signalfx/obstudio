package api

import (
	"encoding/json"
	"errors"
	"net/http"

	"github.com/signalfx/obstudio/observer/internal/freeaccount"
)

type freeAccountAPI struct {
	submitter freeaccount.Submitter
}

type freeAccountErrorResponse struct {
	Code      string `json:"code"`
	Error     string `json:"error"`
	RetrySafe bool   `json:"retrySafe"`
}

func newFreeAccountAPI(submitter freeaccount.Submitter) *freeAccountAPI {
	return &freeAccountAPI{
		submitter: submitter,
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
	case freeaccount.ErrorCodePreparation:
		status = http.StatusServiceUnavailable
	case freeaccount.ErrorCodeOutcomeUnknown:
		status = http.StatusBadGateway
	case freeaccount.ErrorCodeCanceled:
		status = http.StatusRequestTimeout
	}
	writeFreeAccountError(w, status, string(signupErr.Code), signupErr.Message, signupErr.RetrySafe)
}

func (a *freeAccountAPI) authorize(next http.HandlerFunc) http.HandlerFunc {
	return requireLocalObserverRequest(next, func(w http.ResponseWriter, status int, message string) {
		writeFreeAccountError(w, status, "forbidden", message, true)
	})
}

func writeFreeAccountError(w http.ResponseWriter, status int, code, message string, retrySafe bool) {
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(freeAccountErrorResponse{
		Code:      code,
		Error:     message,
		RetrySafe: retrySafe,
	})
}
