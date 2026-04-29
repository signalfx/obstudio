package main

import (
	"flag"
	"log"
	"net/http"

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

	if err := http.ListenAndServe(*addr, api.Handler()); err != nil {
		log.Fatalf("server error: %v", err)
	}
}
