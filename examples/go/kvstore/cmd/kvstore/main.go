package main

import (
	"log"
	"net/http"
	"os"

	"kvstore/internal/api"
	"kvstore/internal/store"
)

func main() {
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
	if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatalf("server error: %v", err)
	}
}
