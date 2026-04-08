package main

import (
	"context"
	"log"
	"net/http"
	"os"

	"kvstore/internal/api"
	"kvstore/internal/store"
)

func main() {
	ctx := context.Background()
	shutdown, err := initOTel(ctx)
	if err != nil {
		log.Fatalf("failed to initialize telemetry: %v", err)
	}
	defer func() {
		if err := shutdown(ctx); err != nil {
			log.Printf("telemetry shutdown error: %v", err)
		}
	}()

	addr := ":8080"
	if p := os.Getenv("PORT"); p != "" {
		addr = ":" + p
	}

	s := store.New()
	h := api.New(s)

	server := &http.Server{
		Addr:    addr,
		Handler: h,
	}

	log.Printf("kvstore listening on %s", addr)
	if err = server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatalf("server error: %v", err)
	}
}
