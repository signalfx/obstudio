package web

import (
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/signalfx/obstudio/observer/internal/store"
	"github.com/signalfx/obstudio/observer/internal/validator"
)

func TestStaticIndexReferencesObserverIcon(t *testing.T) {
	rootDir := filepath.Join("static")
	indexBytes, err := os.ReadFile(filepath.Join(rootDir, "index.html"))
	if err != nil {
		t.Fatalf("read static index: %v", err)
	}

	if !strings.Contains(string(indexBytes), `/assets/observer-icon.svg`) {
		t.Fatal("static index should reference the observer favicon asset")
	}
	if !strings.Contains(string(indexBytes), `/assets/main.js?v=0.0.8`) {
		t.Fatal("static index should cache-bust main.js with the extension release version")
	}
	if !strings.Contains(string(indexBytes), `/assets/main.css?v=0.0.8`) {
		t.Fatal("static index should cache-bust main.css with the extension release version")
	}

	if _, err := os.Stat(filepath.Join(rootDir, "assets", "observer-icon.svg")); err != nil {
		t.Fatalf("observer favicon asset missing: %v", err)
	}
}

func TestStaticAssetsAreRevalidated(t *testing.T) {
	mux := http.NewServeMux()
	cleanup := Register(mux, store.New(), validator.NewStore())
	defer cleanup()

	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodGet, "/assets/main.js?v=0.0.8", nil)
	mux.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("expected asset response status 200, got %d", recorder.Code)
	}
	if cache := recorder.Header().Get("Cache-Control"); cache != "no-cache" {
		t.Fatalf("expected Cache-Control no-cache, got %q", cache)
	}
}
