package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// writeClaudeMCPConfig writes a .claude.json with an obstudio HTTP MCP server
// pinned to mcpURL, under the given HOME.
func writeClaudeMCPConfig(t *testing.T, home, mcpURL string) {
	t.Helper()
	path := filepath.Join(home, ".claude.json")
	body := `{
  "mcpServers": {
    "obstudio": {
      "type": "http",
      "url": "` + mcpURL + `"
    }
  }
}
`
	if err := os.WriteFile(path, []byte(body), 0o644); err != nil {
		t.Fatalf("write claude config: %v", err)
	}
}

// TestWarnStaleMCPPortConfigsFlagsWrongPort verifies the start-time nudge fires
// when an agent config pins obstudio at a port other than the running one, and
// that the message names the stale target and the install --target hint.
func TestWarnStaleMCPPortConfigsFlagsWrongPort(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	writeClaudeMCPConfig(t, home, "http://127.0.0.1:3000/mcp")

	var buf bytes.Buffer
	warnStaleMCPPortConfigs(&buf, "17900")

	out := buf.String()
	if !strings.Contains(out, "old port") {
		t.Fatalf("nudge missing stale-port notice: %q", out)
	}
	if !strings.Contains(out, "claude-code") {
		t.Fatalf("nudge did not name the stale target: %q", out)
	}
	if !strings.Contains(out, "obstudio install --target=claude-code") {
		t.Fatalf("nudge missing install hint: %q", out)
	}
	if !strings.Contains(out, ":17900") {
		t.Fatalf("nudge did not name the current port: %q", out)
	}
}

// TestWarnStaleMCPPortConfigsSilentWhenMatching verifies the nudge stays silent
// when the pinned port already matches the running port.
func TestWarnStaleMCPPortConfigsSilentWhenMatching(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	writeClaudeMCPConfig(t, home, "http://127.0.0.1:17900/mcp")

	var buf bytes.Buffer
	warnStaleMCPPortConfigs(&buf, "17900")

	if buf.Len() != 0 {
		t.Fatalf("nudge fired for a matching port: %q", buf.String())
	}
}

// TestWarnStaleMCPPortConfigsSilentForStdio verifies stdio command-mode entries
// (no url) never trigger the nudge — they do not pin a port.
func TestWarnStaleMCPPortConfigsSilentForStdio(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	path := filepath.Join(home, ".claude.json")
	body := `{
  "mcpServers": {
    "obstudio": {
      "command": "/usr/local/bin/obstudio",
      "args": []
    }
  }
}
`
	if err := os.WriteFile(path, []byte(body), 0o644); err != nil {
		t.Fatalf("write claude config: %v", err)
	}

	var buf bytes.Buffer
	warnStaleMCPPortConfigs(&buf, "17900")

	if buf.Len() != 0 {
		t.Fatalf("nudge fired for a stdio command-mode entry: %q", buf.String())
	}
}
