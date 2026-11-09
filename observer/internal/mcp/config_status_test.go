package mcp

import (
	"bytes"
	"encoding/json"
	"io"
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

// brokenAfterStart starts a Manager on the Scaffold and then breaks the YAML.
func brokenAfterStart(t *testing.T) *configstatus.Builder {
	t.Helper()
	b := builderFor(t, userconfig.Scaffold())
	path := b.Build().Path
	if err := os.WriteFile(path, []byte("telemetry: [unclosed"), 0o600); err != nil {
		t.Fatal(err)
	}
	return b
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
		{"unparseable after start", brokenAfterStart(t), true},
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
				if tc.name == "unparseable after start" && got.(map[string]any)["state"] != "unparseable" {
					t.Errorf("config state %v, want unparseable", got.(map[string]any)["state"])
				}
			}
			if names := toolNames(t, d); !reflect.DeepEqual(names, baseline) {
				t.Errorf("tools %v, want %v", names, baseline)
			}
		})
	}
}

// stdioStatus runs one observer_status call through RunStdio and returns the
// tool's JSON payload.
func stdioStatus(t *testing.T, params ...any) map[string]json.RawMessage {
	t.Helper()
	req := `{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"observer_status","arguments":{}}}` + "\n"
	var out bytes.Buffer
	RunStdio(store.New(), io.NopCloser(strings.NewReader(req)), &out, params...)
	var resp jsonRPCResponse
	if err := json.Unmarshal(bytes.TrimSpace(out.Bytes()), &resp); err != nil {
		t.Fatalf("unmarshal stdio response %q: %v", out.String(), err)
	}
	if resp.Error != nil {
		t.Fatalf("stdio error: %+v", resp.Error)
	}
	content := toSliceAny(toMapAny(resp.Result)["content"])
	if len(content) != 1 {
		t.Fatalf("content = %#v, want one text result", content)
	}
	text, _ := toMapAny(content[0])["text"].(string)
	var payload map[string]json.RawMessage
	if err := json.Unmarshal([]byte(text), &payload); err != nil {
		t.Fatalf("unmarshal tool payload %q: %v", text, err)
	}
	return payload
}

func TestStdioObserverStatusConfig(t *testing.T) {
	// mcp-stdio-config (a): a stdio dispatcher given a Builder reports config.
	got := stdioStatus(t, builderFor(t, "telemetry:\n  enabled: maybe"))
	raw, ok := got["config"]
	if !ok {
		t.Fatalf("mcp-stdio-config (a): no config key in %v", got)
	}
	var config struct {
		Problem bool `json:"problem"`
	}
	if err := json.Unmarshal(raw, &config); err != nil {
		t.Fatalf("mcp-stdio-config (a): config %s: %v", raw, err)
	}
	if !config.Problem {
		t.Errorf("mcp-stdio-config (a): config = %s, want problem true", raw)
	}

	// (b) No Builder: no config key.
	if _, ok := stdioStatus(t)["config"]; ok {
		t.Error("mcp-stdio-config (b): config key present without a Builder")
	}

	// (c) A nil *configstatus.Builder, as run passes with the gate off, is no
	// Builder.
	var none *configstatus.Builder
	if _, ok := stdioStatus(t, none)["config"]; ok {
		t.Error("mcp-stdio-config (c): config key present with a nil Builder")
	}
}
