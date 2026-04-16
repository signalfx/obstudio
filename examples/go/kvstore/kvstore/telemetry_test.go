package kvstore

import (
	"net/http/httptest"
	"testing"
)

func TestRoutePattern(t *testing.T) {
	t.Parallel()

	tests := []struct {
		path string
		want string
	}{
		{path: "/kv/test", want: "/kv/*"},
		{path: "/search", want: "/search"},
		{path: "/unknown", want: "/unknown"},
	}

	for _, tt := range tests {
		req := httptest.NewRequest("GET", tt.path, nil)
		if got := routePattern(req); got != tt.want {
			t.Fatalf("routePattern(%q) = %q, want %q", tt.path, got, tt.want)
		}
	}
}

func TestTelemetrySnapshot(t *testing.T) {
	t.Parallel()

	s := &Store{
		capacity: 4,
		items: map[string]*entry{
			"a": {},
			"b": {},
		},
		indexCh: make(chan indexEvent, 4),
	}

	s.indexCh <- indexEvent{kind: "set", key: "pending", new: []byte("value")}

	snapshot := s.telemetrySnapshot()
	if snapshot.items != 2 {
		t.Fatalf("items = %d, want 2", snapshot.items)
	}
	if snapshot.backlog < 1 {
		t.Fatalf("backlog = %d, want at least 1", snapshot.backlog)
	}
	if snapshot.utilization != 0.5 {
		t.Fatalf("utilization = %v, want 0.5", snapshot.utilization)
	}
}
