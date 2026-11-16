package main

import (
	"encoding/json"
	"log/slog"
	"net"
	"net/http"
	"os"
	"strconv"
	"sync"

	"github.com/go-chi/chi/v5"
)

type Task struct {
	ID    int    `json:"id"`
	Title string `json:"title"`
	Done  bool   `json:"done"`
}

var (
	mu     sync.Mutex
	nextID = 3
	tasks  = []Task{
		{ID: 1, Title: "Buy groceries", Done: false},
		{ID: 2, Title: "Walk the dog", Done: true},
	}
)

func main() {
	r := chi.NewRouter()

	r.Get("/health", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
	})
	r.Get("/logging-workflow/{slot:left|right}", func(w http.ResponseWriter, req *http.Request) {
		slot := chi.URLParam(req, "slot")
		slog.Warn("workflow sync completed " + slot)
		done := make(chan struct{})
		go func() {
			slog.Warn("workflow async completed " + slot)
			close(done)
		}()
		<-done
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
	})

	r.Get("/tasks", func(w http.ResponseWriter, _ *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		writeJSON(w, http.StatusOK, tasks)
	})

	r.Get("/tasks/{id}", func(w http.ResponseWriter, r *http.Request) {
		id, _ := strconv.Atoi(chi.URLParam(r, "id"))
		mu.Lock()
		defer mu.Unlock()
		for _, t := range tasks {
			if t.ID == id {
				writeJSON(w, http.StatusOK, t)
				return
			}
		}
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "not found"})
	})

	r.Post("/tasks", func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Title string `json:"title"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid body"})
			return
		}
		mu.Lock()
		t := Task{ID: nextID, Title: body.Title, Done: false}
		nextID++
		tasks = append(tasks, t)
		mu.Unlock()
		writeJSON(w, http.StatusCreated, t)
	})

	r.Patch("/tasks/{id}", func(w http.ResponseWriter, r *http.Request) {
		id, _ := strconv.Atoi(chi.URLParam(r, "id"))
		var body struct {
			Title *string `json:"title"`
			Done  *bool   `json:"done"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid body"})
			return
		}
		mu.Lock()
		defer mu.Unlock()
		for i := range tasks {
			if tasks[i].ID == id {
				if body.Title != nil {
					tasks[i].Title = *body.Title
				}
				if body.Done != nil {
					tasks[i].Done = *body.Done
				}
				writeJSON(w, http.StatusOK, tasks[i])
				return
			}
		}
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "not found"})
	})

	r.Delete("/tasks/{id}", func(w http.ResponseWriter, r *http.Request) {
		id, _ := strconv.Atoi(chi.URLParam(r, "id"))
		mu.Lock()
		defer mu.Unlock()
		for i, t := range tasks {
			if t.ID == id {
				tasks = append(tasks[:i], tasks[i+1:]...)
				w.WriteHeader(http.StatusNoContent)
				return
			}
		}
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "not found"})
	})

	port := os.Getenv("PORT")
	if port == "" {
		port = "8000"
	}
	slog.Warn("workflow outside completed")
	http.ListenAndServe(net.JoinHostPort(os.Getenv("HOST"), port), r)
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}
