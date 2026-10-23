package mcp

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"strings"
	"testing"

	"github.com/signalfx/obstudio/observer/internal/configstatus"
	"github.com/signalfx/obstudio/observer/internal/store"
	"github.com/signalfx/obstudio/observer/internal/userconfig"
)

func statusResult(t *testing.T, d *Dispatcher) map[string]json.RawMessage {
	t.Helper()
	resp, _ := d.Dispatch(jsonRPCRequest{
		ID:      1,
		JSONRPC: "2.0",
		Method:  "tools/call",
		Params:  map[string]any{"name": "observer_status", "arguments": map[string]any{}},
	})
	result, ok := resp.Result.(toolResult)
	if !ok || result.IsError || len(result.Content) == 0 {
		t.Fatalf("observer_status result %#v", resp.Result)
	}
	var out map[string]json.RawMessage
	if err := json.Unmarshal([]byte(result.Content[0].Text), &out); err != nil {
		t.Fatal(err)
	}
	return out
}

func toolNames(t *testing.T, d *Dispatcher) []string {
	t.Helper()
	resp, _ := d.Dispatch(jsonRPCRequest{ID: 1, JSONRPC: "2.0", Method: "tools/list"})
	raw, err := json.Marshal(resp.Result)
	if err != nil {
		t.Fatal(err)
	}
	var list struct{ Tools []struct{ Name string } }
	if err := json.Unmarshal(raw, &list); err != nil {
		t.Fatal(err)
	}
	var names []string
	for _, tool := range list.Tools {
		names = append(names, tool.Name)
	}
	sort.Strings(names)
	return names
}

func builderFor(t *testing.T, content string) *configstatus.Builder {
	t.Helper()
	path := filepath.Join(t.TempDir(), "config.yaml")
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
	m, err := userconfig.NewManager(path, userconfig.WithLogf(func(string, ...any) {}))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { m.Close() })
	return configstatus.New(m, path)
}

func TestObserverStatusConfigField(t *testing.T) {
	sc := userconfig.Scaffold()
	maybe := strings.Replace(sc, "enabled: true", "enabled: maybe", 1)
	cases := []struct {
		name    string
		builder *configstatus.Builder
		present bool
	}{
		{"ok", builderFor(t, sc), false},
		{"invalid", builderFor(t, maybe), true},
		{"unknown key only", builderFor(t, sc+"zz: 1\n"), false},
		{"no builder", nil, false},
	}
	baseline := toolNames(t, NewDispatcher(store.New()))
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			var d *Dispatcher
			if tc.builder != nil {
				d = NewDispatcher(store.New(), tc.builder)
			} else {
				d = NewDispatcher(store.New())
			}
			out := statusResult(t, d)
			for _, k := range []string{"endpoints", "stats", "validation"} {
				if _, ok := out[k]; !ok {
					t.Errorf("%s missing", k)
				}
			}
			raw, ok := out["config"]
			if ok != tc.present {
				t.Fatalf("config present = %v, want %v", ok, tc.present)
			}
			if ok {
				want, err := json.Marshal(tc.builder.Build())
				if err != nil {
					t.Fatal(err)
				}
				var got, exp any
				json.Unmarshal(raw, &got)
				json.Unmarshal(want, &exp)
				if !reflect.DeepEqual(got, exp) {
					t.Errorf("config %s, want %s", raw, want)
				}
			}
			if names := toolNames(t, d); !reflect.DeepEqual(names, baseline) {
				t.Errorf("tools %v, want %v", names, baseline)
			}
		})
	}
}
