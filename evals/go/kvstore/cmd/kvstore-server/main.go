package main

import (
	"context"
	"errors"
	"flag"
	"log"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"kvstore/kvstore"
)

func main() {
	var (
		addr     = flag.String("addr", ":8080", "HTTP listen address")
		dataDir  = flag.String("data-dir", "./data", "directory used for persistence")
		capacity = flag.Int("capacity", 1024, "maximum number of key/value pairs in memory")
	)
	flag.Parse()

	store, err := kvstore.NewStore(kvstore.StoreConfig{
		Capacity: *capacity,
		DataDir:  *dataDir,
		Logger:   log.Default(),
	})
	if err != nil {
		log.Fatalf("failed to create store: %v", err)
	}

	api := kvstore.NewAPI(store)
	log.Printf("listening on %s", *addr)
	defer store.Close()

	server := &http.Server{Addr: *addr, Handler: api.Handler()}
	serverErrors := make(chan error, 1)
	go func() {
		serverErrors <- server.ListenAndServe()
	}()

	shutdownSignals := make(chan os.Signal, 1)
	signal.Notify(shutdownSignals, os.Interrupt, syscall.SIGTERM)
	defer signal.Stop(shutdownSignals)

	select {
	case err := <-serverErrors:
		if errors.Is(err, http.ErrServerClosed) {
			return
		}
		log.Fatalf("server error: %v", err)
	case <-shutdownSignals:
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		if err := server.Shutdown(shutdownCtx); err != nil {
			log.Printf("server shutdown error: %v", err)
			return
		}
		if err := <-serverErrors; !errors.Is(err, http.ErrServerClosed) {
			log.Printf("server error during shutdown: %v", err)
			return
		}
		slog.Warn("runtime shutdown completed")
	}
}
