package main

import (
	"context"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strings"

	"go.opentelemetry.io/otel"

	"github.com/signalfx/obstudio/observer/internal/adoption"
	"github.com/signalfx/obstudio/observer/internal/adoption/export"
	"github.com/signalfx/obstudio/observer/internal/adoption/gate"
	"github.com/signalfx/obstudio/observer/internal/api"
	"github.com/signalfx/obstudio/observer/internal/mcp"
	"github.com/signalfx/obstudio/observer/internal/store"
	"github.com/signalfx/obstudio/observer/internal/userconfig"
)

// adoptionWiring is obstudio's own adoption telemetry: the gate, the emitter
// and its export path. The zero value, used when there is no Config Manager,
// does nothing: no reader, no timer, no files, no network.
type adoptionWiring struct {
	gate    *gate.Gate
	emitter *adoption.Emitter
}

// resolveObserverOwner is what started this observer: the OBSTUDIO_OWNER
// launcher contract, cli when unset. It is reported in the server info and,
// bucketed to the launcher set, as obstudio.launcher in usage data.
func resolveObserverOwner() string { return envOr("OBSTUDIO_OWNER", "cli") }

// buildAdoption wires adoption telemetry over the Config Manager. With no
// Manager the gate could never open, so nothing is built. path is the
// Manager's config.yaml; its directory is ~/.obstudio. owner is the resolved
// OBSTUDIO_OWNER; a value outside the launcher set is sent as "other".
func buildAdoption(m *userconfig.Manager, path, owner string, s *store.Store) adoptionWiring {
	if m == nil || path == "" {
		return adoptionWiring{}
	}
	_, overrideSet := export.Endpoint(os.Getenv)
	g := gate.New(gate.Inputs{
		Config: m,
		Path:   path,
		// A dev build has no destination unless the endpoint override is set,
		// so a local build never sends to the production endpoint.
		DestinationSet: overrideSet || version != "dev",
	})
	w, err := startAdoption(g, filepath.Dir(path), owner)
	if err != nil {
		log.Printf("adoption telemetry is unavailable: %v", err)
		g.Close()
		return adoptionWiring{}
	}
	s.SetReceiptCallback(w.emitter.OTLPReceipt)
	return w
}

func startAdoption(g *gate.Gate, dir, owner string) (adoptionWiring, error) {
	exp, err := export.NewExporter(export.ExporterConfig{ClientType: export.ClientTypeLongRunning, Gate: g})
	if err != nil {
		return adoptionWiring{}, err
	}
	em, err := adoption.New(adoption.Config{Dir: dir, Gate: g, Version: version, Launcher: owner})
	if err != nil {
		return adoptionWiring{}, err
	}
	reader, err := export.NewReader(em.Exporter(exp), export.ReaderConfig{ClientType: export.ClientTypeLongRunning})
	if err != nil {
		return adoptionWiring{}, err
	}
	em.SetFlush(reader.ForceFlush)
	installAdoptionErrorHandler()
	if err := em.Start(reader); err != nil {
		return adoptionWiring{}, err
	}
	return adoptionWiring{gate: g, emitter: em}, nil
}

// installAdoptionErrorHandler keeps dropped and failed adoption exports out of
// the process log: the SDK reader hands every export error to the global OTel
// handler. Every other OTel error is still logged as before.
func installAdoptionErrorHandler() {
	otel.SetErrorHandler(otel.ErrorHandlerFunc(func(err error) {
		if export.IsAdoptionError(err) {
			return
		}
		log.Print(err)
	}))
}

// mcpHooks reports MCP tool use to the emitter. A nil emitter ignores it.
func (w adoptionWiring) mcpHooks() mcp.UsageHooks {
	em := w.emitter
	return mcp.UsageHooks{ToolsCall: em.ActiveMCP, ValidationRun: em.ValidationRun, Connect: em.Connected}
}

// cloudConnected reports a Splunk Observability Cloud connect from the REST
// API: a verified token connection or an established O11y OAuth session.
// With no emitter it is nil, which the api package ignores.
func (w adoptionWiring) cloudConnected() api.SplunkCloudConnected {
	if w.emitter == nil {
		return nil
	}
	return w.emitter.Connected
}

// observerStarted records first_use{observer_start}.
func (w adoptionWiring) observerStarted() { w.emitter.ObserverStarted() }

// shutdown runs the clean-exit flush, bounded by export.FlushTimeout, then
// closes the gate. The caller closes the Manager afterwards.
func (w adoptionWiring) shutdown() {
	if w.emitter == nil {
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), export.FlushTimeout)
	defer cancel()
	_ = w.emitter.Shutdown(ctx)
	w.gate.Close()
}

// surfaceHeader is set by the extension host on requests made while the
// Splunk Observability Studio panel is visible and focused.
const surfaceHeader = "X-Obstudio-Surface"

// handler wraps the HTTP mux to observe UI activity and UI validation runs.
// Connects are reported by the api package (cloudConnected). With no emitter
// it returns next unchanged.
func (w adoptionWiring) handler(next http.Handler) http.Handler {
	em := w.emitter
	if em == nil {
		return next
	}
	return http.HandlerFunc(func(rw http.ResponseWriter, r *http.Request) {
		path := r.URL.Path
		if strings.EqualFold(strings.TrimSpace(r.Header.Get(surfaceHeader)), "ui") &&
			path != "/api/health" && !strings.HasPrefix(path, "/api/splunk/") {
			em.ActiveUI()
		}
		if r.Method != http.MethodPost || path != "/api/validation/run" {
			next.ServeHTTP(rw, r)
			return
		}
		sw := &statusWriter{ResponseWriter: rw, status: http.StatusOK}
		next.ServeHTTP(sw, r)
		if sw.status >= 200 && sw.status < 300 {
			em.ValidationRun()
		}
	})
}

// statusWriter records the response status of a plain JSON handler.
type statusWriter struct {
	http.ResponseWriter
	status  int
	written bool
}

func (w *statusWriter) WriteHeader(code int) {
	if !w.written {
		w.status, w.written = code, true
	}
	w.ResponseWriter.WriteHeader(code)
}

func (w *statusWriter) Write(b []byte) (int, error) {
	w.written = true
	return w.ResponseWriter.Write(b)
}

func (w *statusWriter) Unwrap() http.ResponseWriter { return w.ResponseWriter }
