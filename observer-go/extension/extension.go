package extension

import (
	"context"
	"net/http"

	"github.com/signalfx/obstudio/observer-go/internal/api"
	"github.com/signalfx/obstudio/observer-go/internal/mcp"
	"github.com/signalfx/obstudio/observer-go/internal/store"
	"github.com/signalfx/obstudio/observer-go/internal/web"
	"go.opentelemetry.io/collector/component"
)

type obstudioExtension struct {
	cfg    *Config
	store  *store.Store
	server *http.Server
}

func newExtension(cfg *Config, s *store.Store) *obstudioExtension {
	return &obstudioExtension{cfg: cfg, store: s}
}

func (e *obstudioExtension) Start(_ context.Context, _ component.Host) error {
	mux := http.NewServeMux()
	api.Register(mux, e.store)
	mcp.Register(mux, e.store)
	web.Register(mux, e.store)

	e.server = &http.Server{Addr: e.cfg.Endpoint, Handler: mux}
	go e.server.ListenAndServe()
	return nil
}

func (e *obstudioExtension) Shutdown(ctx context.Context) error {
	if e.server != nil {
		return e.server.Shutdown(ctx)
	}
	return nil
}
