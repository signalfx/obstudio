package kvstore

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"testing"
	"time"
)

func TestAPISetGetDelete(t *testing.T) {
	s, err := NewStore(StoreConfig{Capacity: 10, DataDir: t.TempDir()})
	if err != nil {
		t.Fatalf("NewStore: %v", err)
	}
	defer s.Close()
	api := NewAPI(s)
	ts := httptest.NewServer(api.Handler())
	defer ts.Close()

	req, _ := http.NewRequest(http.MethodPut, ts.URL+"/kv/test", strings.NewReader("value"))
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("PUT: %v", err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusAccepted {
		t.Fatalf("unexpected status: %d", resp.StatusCode)
	}

	waitFor(t, time.Second, func() bool {
		keys := s.Search("value")
		return reflect.DeepEqual(keys, []string{"test"})
	})

	resp, err = http.Get(ts.URL + "/kv/test")
	if err != nil {
		t.Fatalf("GET: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected status: %d", resp.StatusCode)
	}

	req, _ = http.NewRequest(http.MethodDelete, ts.URL+"/kv/test", nil)
	resp, err = http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("DELETE: %v", err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusNoContent {
		t.Fatalf("unexpected status: %d", resp.StatusCode)
	}
}

func TestAPIErrors(t *testing.T) {
	s, err := NewStore(StoreConfig{Capacity: 10, DataDir: t.TempDir()})
	if err != nil {
		t.Fatalf("NewStore: %v", err)
	}
	defer s.Close()
	api := NewAPI(s)
	ts := httptest.NewServer(api.Handler())
	defer ts.Close()

	resp, err := http.Get(ts.URL + "/kv/missing")
	if err != nil {
		t.Fatalf("GET: %v", err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusNotFound {
		t.Fatalf("unexpected status: %d", resp.StatusCode)
	}

	req, _ := http.NewRequest(http.MethodPut, ts.URL+"/kv/bad key", strings.NewReader("x"))
	resp, err = http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("PUT: %v", err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusBadRequest {
		t.Fatalf("unexpected status: %d", resp.StatusCode)
	}

	big := strings.Repeat("a", MaxValueSize+1)
	req, _ = http.NewRequest(http.MethodPut, ts.URL+"/kv/ok", strings.NewReader(big))
	resp, err = http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("PUT big: %v", err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusRequestEntityTooLarge && resp.StatusCode != http.StatusBadRequest {
		t.Fatalf("unexpected status: %d", resp.StatusCode)
	}
}

func TestAPISearch(t *testing.T) {
	s, err := NewStore(StoreConfig{Capacity: 10, DataDir: t.TempDir()})
	if err != nil {
		t.Fatalf("NewStore: %v", err)
	}
	defer s.Close()
	api := NewAPI(s)
	ts := httptest.NewServer(api.Handler())
	defer ts.Close()

	_ = s.Set("a", []byte("foo bar"))
	_ = s.Set("b", []byte("bar baz"))
	waitFor(t, time.Second, func() bool {
		return len(s.Search("bar")) == 2
	})

	resp, err := http.Get(ts.URL + "/search?word=bar")
	if err != nil {
		t.Fatalf("search: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("unexpected status: %d", resp.StatusCode)
	}
	var got struct {
		Keys []string `json:"keys"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&got); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if !reflect.DeepEqual(got.Keys, []string{"a", "b"}) {
		t.Fatalf("unexpected keys: %#v", got.Keys)
	}
}
