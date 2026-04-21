package main

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"strconv"
	"sync"

	"github.com/go-chi/chi/v5"
	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/metric"
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

var (
	meter        = otel.Meter("go-chi-basic")
	tasksCreated metric.Int64Counter
	tasksCompleted metric.Int64Counter
	tasksDeleted metric.Int64Counter
)

func initMetrics() {
	var err error
	tasksCreated, err = meter.Int64Counter("tasks.created.count",
		metric.WithDescription("Total tasks created"),
		metric.WithUnit("{tasks}"))
	if err != nil {
		log.Printf("failed to create tasks.created.count: %v", err)
	}

	tasksCompleted, err = meter.Int64Counter("tasks.completed.count",
		metric.WithDescription("Total tasks marked as done"),
		metric.WithUnit("{tasks}"))
	if err != nil {
		log.Printf("failed to create tasks.completed.count: %v", err)
	}

	tasksDeleted, err = meter.Int64Counter("tasks.deleted.count",
		metric.WithDescription("Total tasks deleted"),
		metric.WithUnit("{tasks}"))
	if err != nil {
		log.Printf("failed to create tasks.deleted.count: %v", err)
	}

	_, err = meter.Int64ObservableGauge("tasks.active.count",
		metric.WithDescription("Current number of active tasks"),
		metric.WithUnit("{tasks}"),
		metric.WithInt64Callback(func(_ context.Context, o metric.Int64Observer) error {
			mu.Lock()
			defer mu.Unlock()
			o.Observe(int64(len(tasks)))
			return nil
		}))
	if err != nil {
		log.Printf("failed to create tasks.active.count: %v", err)
	}
}

func main() {
	ctx := context.Background()
	shutdown, err := initOTel(ctx)
	if err != nil {
		log.Fatalf("failed to initialize telemetry: %v", err)
	}
	defer shutdown(ctx)

	initMetrics()

	r := chi.NewRouter()

	r.Get("/health", func(w http.ResponseWriter, _ *http.Request) {
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
		log.Printf("http.request.error route=/tasks/%d error.type=not_found", id)
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
		tasksCreated.Add(r.Context(), 1)
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
				wasDone := tasks[i].Done
				if body.Title != nil {
					tasks[i].Title = *body.Title
				}
				if body.Done != nil {
					tasks[i].Done = *body.Done
				}
				if !wasDone && tasks[i].Done {
					tasksCompleted.Add(r.Context(), 1)
				}
				writeJSON(w, http.StatusOK, tasks[i])
				return
			}
		}
		log.Printf("http.request.error route=/tasks/%d error.type=not_found", id)
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "not found"})
	})

	r.Delete("/tasks/{id}", func(w http.ResponseWriter, r *http.Request) {
		id, _ := strconv.Atoi(chi.URLParam(r, "id"))
		mu.Lock()
		defer mu.Unlock()
		for i, t := range tasks {
			if t.ID == id {
				tasks = append(tasks[:i], tasks[i+1:]...)
				tasksDeleted.Add(r.Context(), 1)
				w.WriteHeader(http.StatusNoContent)
				return
			}
		}
		log.Printf("http.request.error route=/tasks/%d error.type=not_found", id)
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "not found"})
	})

	handler := otelhttp.NewHandler(r, "go-chi-basic")
	log.Printf("listening on :8000")
	if err := http.ListenAndServe(":8000", handler); err != nil {
		log.Fatalf("server error: %v", err)
	}
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}
