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
	cleanup := Register(mux, store.New(), validator.NewStore(), "")
	defer cleanup()

	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodGet, "/assets/main.js?v=0.0.8", nil)
	mux.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("expected asset response status 200, got %d", recorder.Code)
	}
	if cache := recorder.Header().Get("Cache-Control"); cache != "max-age=0, must-revalidate" {
		t.Fatalf("expected Cache-Control max-age=0, must-revalidate, got %q", cache)
	}
}

func TestStaticIndexCannotBeFramedByAnotherSite(t *testing.T) {
	mux := http.NewServeMux()
	cleanup := Register(mux, store.New(), validator.NewStore(), "")
	defer cleanup()

	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodGet, "/?tab=cloud", nil)
	mux.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("expected index response status 200, got %d", recorder.Code)
	}
	if csp := recorder.Header().Get("Content-Security-Policy"); csp != "frame-ancestors 'none'" {
		t.Fatalf("Content-Security-Policy = %q, want frame-ancestors 'none'", csp)
	}
	if frameOptions := recorder.Header().Get("X-Frame-Options"); frameOptions != "DENY" {
		t.Fatalf("X-Frame-Options = %q, want DENY", frameOptions)
	}
}

func TestIndexInjectsControlTokenForOwnPageOnly(t *testing.T) {
	mux := http.NewServeMux()
	cleanup := Register(mux, store.New(), validator.NewStore(), "test-control-token")
	defer cleanup()

	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodGet, "/", nil)
	request.RemoteAddr = "127.0.0.1:54321"
	request.Host = "127.0.0.1:3000"
	mux.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("expected index response status 200, got %d", recorder.Code)
	}
	if cache := recorder.Header().Get("Cache-Control"); cache != "no-store" {
		t.Fatalf("expected Cache-Control no-store on index, got %q", cache)
	}
	body := recorder.Body.String()
	if !strings.Contains(body, `window.__OBSTUDIO_CONTROL_TOKEN__ = "test-control-token";`) {
		t.Fatalf("expected index to inject the control token, got body: %s", body)
	}
	// injectControlToken has no access-control headers of its own: the token must not
	// also be readable from a route any cross-origin page can fetch.
	if strings.Contains(recorder.Header().Get("Access-Control-Allow-Origin"), "*") {
		t.Fatal("index response must not carry a wildcard CORS header alongside the control token")
	}
}

func TestIndexOmitsControlTokenForNonLoopbackRequest(t *testing.T) {
	mux := http.NewServeMux()
	cleanup := Register(mux, store.New(), validator.NewStore(), "test-control-token")
	defer cleanup()

	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodGet, "/", nil)
	request.RemoteAddr = "192.0.2.1:1234"
	request.Host = "127.0.0.1:3000"
	mux.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("expected index response status 200, got %d", recorder.Code)
	}
	if strings.Contains(recorder.Body.String(), "__OBSTUDIO_CONTROL_TOKEN__") {
		t.Fatal("index must not inject the control token for a non-loopback remote address, " +
			"e.g. when the Observer is bound to 0.0.0.0 or a LAN address")
	}
}

func TestIndexOmitsControlTokenForNonLoopbackHost(t *testing.T) {
	mux := http.NewServeMux()
	cleanup := Register(mux, store.New(), validator.NewStore(), "test-control-token")
	defer cleanup()

	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodGet, "/", nil)
	// Simulates a DNS-rebinding attack: an attacker-controlled hostname's DNS record has
	// been flipped to point at the Observer's loopback bind, so the TCP peer is loopback
	// even though the request's Host -- and therefore the browser's same-origin identity
	// for this page -- is still the attacker's.
	request.RemoteAddr = "127.0.0.1:54321"
	request.Host = "attacker.example.test:3000"
	mux.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("expected index response status 200, got %d", recorder.Code)
	}
	if strings.Contains(recorder.Body.String(), "__OBSTUDIO_CONTROL_TOKEN__") {
		t.Fatal("index must not inject the control token for a non-loopback Host, even with a loopback RemoteAddr")
	}
}

func TestIndexOmitsInjectionWithoutAControlToken(t *testing.T) {
	mux := http.NewServeMux()
	cleanup := Register(mux, store.New(), validator.NewStore(), "")
	defer cleanup()

	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodGet, "/", nil)
	mux.ServeHTTP(recorder, request)

	if strings.Contains(recorder.Body.String(), "__OBSTUDIO_CONTROL_TOKEN__") {
		t.Fatal("index should not inject a control token when none is configured")
	}
}

func TestInjectControlTokenEscapesUntrustedCharacters(t *testing.T) {
	index := []byte("<html><head></head><body></body></html>")
	injected := injectControlToken(index, `token"; alert(1); //`)
	if !strings.Contains(string(injected), `window.__OBSTUDIO_CONTROL_TOKEN__ = "token\"; alert(1); //";`) {
		t.Fatalf("expected the token to be JSON-escaped, got: %s", injected)
	}
}
