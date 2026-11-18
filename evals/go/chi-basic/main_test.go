package main

import (
	"bytes"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/go-chi/chi/v5"
)

func TestLoggingWorkflowRoutes(t *testing.T) {
	var output bytes.Buffer
	previous := slog.Default()
	slog.SetDefault(slog.New(slog.NewTextHandler(&output, nil)))
	t.Cleanup(func() { slog.SetDefault(previous) })
	router := chi.NewRouter()
	registerLoggingWorkflow(router)

	for _, slot := range []string{"left", "right", "leftx", "xright", "not-a-slot"} {
		t.Run(slot, func(t *testing.T) {
			output.Reset()
			response := httptest.NewRecorder()
			router.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/logging-workflow/"+slot, nil))
			if slot != "left" && slot != "right" {
				if response.Code != http.StatusNotFound || output.Len() != 0 {
					t.Fatalf("invalid slot returned %d and logged %q", response.Code, output.String())
				}
				return
			}
			if response.Code != http.StatusOK {
				t.Fatalf("valid slot returned %d", response.Code)
			}
			for _, kind := range []string{"sync", "async"} {
				message := "workflow " + kind + " completed " + slot
				if count := strings.Count(output.String(), message); count != 1 {
					t.Errorf("expected one %q before the response, got %d", message, count)
				}
			}
		})
	}
}
