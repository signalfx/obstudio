package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/signalfx/obstudio/observer/internal/buildutil"
)

// Integration coverage for the instance-singleton behavior added to the
// obstudio binary: auto port scan from 17900, --port conflict reporting,
// pre-flight detection of an already-running instance, and stale state-file
// cleanup. These tests build and run the real binary so they ride the
// cross-OS CI matrix (ubuntu/windows/macos). They stay OS-portable: ports are
// probed with net.Listen, liveness via the HTTP health endpoint, and homes via
// per-test temp dirs — never raw PID signalling, which differs across OSes.

// buildSingletonBinary compiles the obstudio binary once per test and returns
// its path. Embedded skills are staged first so the //go:embed directive is
// satisfied.
func buildSingletonBinary(t *testing.T) string {
	t.Helper()

	observerRoot := observerModuleRoot(t)
	repoRoot := filepath.Dir(observerRoot)
	if err := buildutil.StageEmbeddedSkills(repoRoot, observerRoot); err != nil {
		t.Fatalf("stage embedded skills: %v", err)
	}

	binary := filepath.Join(t.TempDir(), smokeBinaryName())
	build := exec.Command("go", "build", "-o", binary, "./cmd/obstudio")
	build.Dir = observerRoot
	if output, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build singleton binary: %v\n%s", err, strings.TrimSpace(string(output)))
	}
	return binary
}

// singletonRunEnv builds the environment for a singleton binary run rooted at
// homeDir. detection controls whether the pre-flight "already running"
// detection is enabled (smokeHomeEnv disables it by default).
func singletonRunEnv(homeDir string, detection bool, extra ...string) []string {
	env := append(os.Environ(), smokeHomeEnv(homeDir)...)
	if detection {
		// smokeHomeEnv sets disableSharedObserverDetectionEnv=1; override to
		// empty so the pre-flight path runs.
		env = append(env, disableSharedObserverDetectionEnv+"=")
	}
	return append(env, extra...)
}

// startSingletonObserver launches the binary and waits until it writes a
// healthy shared-observer.json, returning the parsed state and a stop func.
func startSingletonObserver(t *testing.T, binary, homeDir string, extraEnv ...string) (sharedObserverState, func()) {
	t.Helper()

	otlpHTTPPort := pickSmokePort(t)
	otlpGRPCPort := pickSmokePort(t)
	env := singletonRunEnv(homeDir, false, append([]string{
		fmt.Sprintf("OTLP_HTTP_PORT=%d", otlpHTTPPort),
		fmt.Sprintf("OTLP_GRPC_PORT=%d", otlpGRPCPort),
	}, extraEnv...)...)

	cmd := exec.Command(binary)
	cmd.Env = env
	var logs bytes.Buffer
	cmd.Stdout = &logs
	cmd.Stderr = &logs
	if err := cmd.Start(); err != nil {
		t.Fatalf("start observer: %v", err)
	}
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	stop := func() { stopSmokeProcess(cmd, done) }

	statePath := filepath.Join(homeDir, sharedObserverStateDirName, sharedObserverStateFileName)
	state := waitForSingletonState(t, statePath, done, &logs, 15*time.Second)
	waitForSingletonHealth(t, state.HealthURL, done, &logs, 10*time.Second)
	return state, stop
}

func waitForSingletonState(t *testing.T, statePath string, done <-chan error, logs *bytes.Buffer, timeout time.Duration) sharedObserverState {
	t.Helper()

	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		select {
		case err := <-done:
			t.Fatalf("observer exited before writing %s: %v\n%s", statePath, err, strings.TrimSpace(logs.String()))
		default:
		}
		if data, err := os.ReadFile(statePath); err == nil {
			var state sharedObserverState
			if json.Unmarshal(data, &state) == nil && strings.TrimSpace(state.BaseURL) != "" {
				return state
			}
		}
		time.Sleep(100 * time.Millisecond)
	}
	t.Fatalf("observer did not write %s within %s\n%s", statePath, timeout, strings.TrimSpace(logs.String()))
	return sharedObserverState{}
}

func waitForSingletonHealth(t *testing.T, healthURL string, done <-chan error, logs *bytes.Buffer, timeout time.Duration) {
	t.Helper()

	client := &http.Client{Timeout: time.Second}
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		select {
		case err := <-done:
			t.Fatalf("observer exited before becoming healthy: %v\n%s", err, strings.TrimSpace(logs.String()))
		default:
		}
		if resp, err := client.Get(healthURL); err == nil {
			resp.Body.Close()
			if resp.StatusCode == http.StatusOK {
				return
			}
		}
		time.Sleep(200 * time.Millisecond)
	}
	t.Fatalf("observer did not become healthy at %s within %s\n%s", healthURL, timeout, strings.TrimSpace(logs.String()))
}

func portFromBaseURL(t *testing.T, baseURL string) int {
	t.Helper()

	trimmed := strings.TrimPrefix(baseURL, "http://")
	_, portStr, err := net.SplitHostPort(trimmed)
	if err != nil {
		t.Fatalf("split host/port from %q: %v", baseURL, err)
	}
	port, err := strconv.Atoi(portStr)
	if err != nil {
		t.Fatalf("parse port from %q: %v", baseURL, err)
	}
	return port
}

// occupyPort binds a listener on an available port and returns the port and a
// closer. The listener stays open so the port is observably in use.
func occupyPort(t *testing.T) (int, func()) {
	t.Helper()

	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("occupy port: %v", err)
	}
	addr, ok := listener.Addr().(*net.TCPAddr)
	if !ok {
		listener.Close()
		t.Fatalf("expected TCP listener address, got %T", listener.Addr())
	}
	return addr.Port, func() { listener.Close() }
}

// TestSingletonSmokeAutoScansFreePort verifies the binary auto-scans a free
// HTTP port when --port is omitted, binds it, and records it in
// shared-observer.json. It then confirms that when a candidate port is already
// occupied the scan skips past it.
func TestSingletonSmokeAutoScansFreePort(t *testing.T) {
	binary := buildSingletonBinary(t)

	home := t.TempDir()
	state, stop := startSingletonObserver(t, binary, home)
	defer stop()

	port := portFromBaseURL(t, state.BaseURL)
	if port < 17900 {
		t.Fatalf("auto-scanned port %d is below the 17900 scan floor", port)
	}

	// Occupy the port the first instance bound, then start a second instance in
	// a fresh home; the scan must skip the occupied port and pick a higher one.
	blocker, err := net.Listen("tcp", net.JoinHostPort("127.0.0.1", strconv.Itoa(port)))
	if err != nil {
		// The first instance still owns the port, which equally proves it is
		// occupied; bind the next port up as the blocker instead.
		blocker, err = net.Listen("tcp", "127.0.0.1:0")
		if err != nil {
			t.Fatalf("establish blocker listener: %v", err)
		}
	}
	defer blocker.Close()
	blockedPort := blocker.Addr().(*net.TCPAddr).Port

	home2 := t.TempDir()
	state2, stop2 := startSingletonObserver(t, binary, home2)
	defer stop2()
	port2 := portFromBaseURL(t, state2.BaseURL)
	if port2 == blockedPort {
		t.Fatalf("second instance bound the occupied port %d instead of skipping it", blockedPort)
	}
	if port2 < 17900 {
		t.Fatalf("second instance port %d is below the 17900 scan floor", port2)
	}
}

// TestSingletonSmokePinnedPortConflict verifies that pinning --port to an
// occupied port fails with the specific conflict message rather than
// auto-scanning.
func TestSingletonSmokePinnedPortConflict(t *testing.T) {
	binary := buildSingletonBinary(t)

	occupied, release := occupyPort(t)
	defer release()

	home := t.TempDir()
	env := singletonRunEnv(home, false,
		fmt.Sprintf("OTLP_HTTP_PORT=%d", pickSmokePort(t)),
		fmt.Sprintf("OTLP_GRPC_PORT=%d", pickSmokePort(t)),
	)
	cmd := exec.Command(binary, "--port", strconv.Itoa(occupied))
	cmd.Env = env
	output, err := cmd.CombinedOutput()
	if err == nil {
		t.Fatalf("expected pinned conflict to fail, output:\n%s", output)
	}
	if !strings.Contains(string(output), "already in use") {
		t.Fatalf("expected conflict message mentioning the occupied port, got:\n%s", output)
	}
}

// TestSingletonSmokeDetectsRunningInstance verifies the pre-flight detection:
// a second launch with detection enabled finds the already-running instance,
// prints "already running at", and exits 0 without starting a new server.
func TestSingletonSmokeDetectsRunningInstance(t *testing.T) {
	binary := buildSingletonBinary(t)

	home := t.TempDir()
	state, stop := startSingletonObserver(t, binary, home)
	defer stop()

	env := singletonRunEnv(home, true,
		fmt.Sprintf("OTLP_HTTP_PORT=%d", pickSmokePort(t)),
		fmt.Sprintf("OTLP_GRPC_PORT=%d", pickSmokePort(t)),
	)
	output, err := runSingletonWithDeadline(t, binary, nil, env, 20*time.Second)
	if err != nil {
		t.Fatalf("second launch should exit 0 when an instance is already running, got %v\n%s", err, output)
	}
	if !strings.Contains(output, "already running at") {
		t.Fatalf("expected 'already running at' message, got:\n%s", output)
	}
	if !strings.Contains(output, state.BaseURL) {
		t.Fatalf("expected detection to report the running URL %q, got:\n%s", state.BaseURL, output)
	}
}

// TestSingletonSmokeDefersWhenOTLPPortsHeldWithoutStateFile verifies Fix 2: an
// instance already holding the fixed OTLP ports — but with NO readable
// shared-observer.json (the upgrade case) — causes an unpinned launch to defer
// (exit 0) rather than crash with a fatal port-in-use error. We simulate the
// held OTLP ports with plain TCP listeners and point the launch at a fresh,
// empty home so no state file exists to short-circuit via pre-flight detection.
func TestSingletonSmokeDefersWhenOTLPPortsHeldWithoutStateFile(t *testing.T) {
	binary := buildSingletonBinary(t)

	otlpHTTPPort, releaseHTTP := occupyPort(t)
	defer releaseHTTP()
	otlpGRPCPort, releaseGRPC := occupyPort(t)
	defer releaseGRPC()

	home := t.TempDir() // empty: no shared-observer.json for pre-flight to find
	env := singletonRunEnv(home, true,
		fmt.Sprintf("OTLP_HTTP_PORT=%d", otlpHTTPPort),
		fmt.Sprintf("OTLP_GRPC_PORT=%d", otlpGRPCPort),
	)
	output, err := runSingletonWithDeadline(t, binary, nil, env, 20*time.Second)
	if err != nil {
		t.Fatalf("launch should exit 0 (defer) when OTLP ports are already held, got %v\n%s", err, output)
	}
	if !strings.Contains(output, "already running") {
		t.Fatalf("expected a 'already running'/defer message when OTLP ports are held, got:\n%s", output)
	}
}

// runSingletonWithDeadline runs the binary to completion with a hard deadline,
// capturing combined output. If the process does not exit within timeout it is
// force-killed and reaped so no child survives the test — this is the
// guaranteed-kill path for launches expected to exit on their own (detection /
// defer), replacing a bare cmd.CombinedOutput() that would hang (and leak the
// process) if the exit-on-detect behavior regressed.
func runSingletonWithDeadline(t *testing.T, binary string, args, env []string, timeout time.Duration) (string, error) {
	t.Helper()

	cmd := exec.Command(binary, args...)
	cmd.Env = env
	var logs bytes.Buffer
	cmd.Stdout = &logs
	cmd.Stderr = &logs
	if err := cmd.Start(); err != nil {
		t.Fatalf("start singleton binary: %v", err)
	}

	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	// Guaranteed reap even on panic/early-return: kill if still running.
	t.Cleanup(func() { stopSmokeProcess(cmd, done) })

	select {
	case err := <-done:
		return logs.String(), err
	case <-time.After(timeout):
		stopSmokeProcess(cmd, done)
		t.Fatalf("singleton binary did not exit within %s (expected a quick detect/defer exit)\n%s", timeout, strings.TrimSpace(logs.String()))
		return logs.String(), fmt.Errorf("timeout")
	}
}

// TestSingletonSmokeCleansStaleStateFile verifies that a stale
// shared-observer.json (pointing at a dead instance) is deleted and normal
// startup proceeds when detection is enabled.
func TestSingletonSmokeCleansStaleStateFile(t *testing.T) {
	binary := buildSingletonBinary(t)

	home := t.TempDir()
	stateDir := filepath.Join(home, sharedObserverStateDirName)
	if err := os.MkdirAll(stateDir, 0o755); err != nil {
		t.Fatalf("mkdir state dir: %v", err)
	}
	statePath := filepath.Join(stateDir, sharedObserverStateFileName)

	// Point the stale state at a port that is bound but not a healthy observer,
	// so the pre-flight health probe fails and triggers cleanup.
	deadPort, release := occupyPort(t)
	defer release()
	staleBase := fmt.Sprintf("http://127.0.0.1:%d", deadPort)
	stale := sharedObserverState{
		BaseURL:   staleBase,
		HealthURL: staleBase + "/api/health",
		MCPURL:    staleBase + "/mcp",
		PID:       999999,
		UpdatedAt: time.Now().UTC().Add(-time.Hour),
	}
	data, err := json.Marshal(stale)
	if err != nil {
		t.Fatalf("marshal stale state: %v", err)
	}
	if err := os.WriteFile(statePath, data, 0o600); err != nil {
		t.Fatalf("write stale state: %v", err)
	}

	// Start with detection enabled; the stale file must be cleaned and a fresh,
	// healthy instance must come up and rewrite the state file.
	otlpHTTPPort := pickSmokePort(t)
	otlpGRPCPort := pickSmokePort(t)
	env := singletonRunEnv(home, true,
		fmt.Sprintf("OTLP_HTTP_PORT=%d", otlpHTTPPort),
		fmt.Sprintf("OTLP_GRPC_PORT=%d", otlpGRPCPort),
	)
	cmd := exec.Command(binary)
	cmd.Env = env
	var logs bytes.Buffer
	cmd.Stdout = &logs
	cmd.Stderr = &logs
	if err := cmd.Start(); err != nil {
		t.Fatalf("start observer: %v", err)
	}
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	defer stopSmokeProcess(cmd, done)

	// Wait until the fresh instance rewrites the state file (distinguished by a
	// PID differing from the stale sentinel), not merely until a file exists —
	// the stale content is present at startup and would otherwise race us.
	state := waitForRewrittenState(t, statePath, stale.PID, done, &logs, 15*time.Second)
	waitForSingletonHealth(t, state.HealthURL, done, &logs, 10*time.Second)

	if state.BaseURL == staleBase {
		t.Fatalf("fresh instance reused the stale base URL %q", staleBase)
	}
	if state.PID == stale.PID {
		t.Fatalf("state file was not rewritten; still records stale PID %d", stale.PID)
	}
}

// waitForRewrittenState polls statePath until it records a PID different from
// stalePID (i.e. a fresh instance has replaced the stale sentinel file).
func waitForRewrittenState(t *testing.T, statePath string, stalePID int, done <-chan error, logs *bytes.Buffer, timeout time.Duration) sharedObserverState {
	t.Helper()

	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		select {
		case err := <-done:
			t.Fatalf("observer exited before rewriting %s: %v\n%s", statePath, err, strings.TrimSpace(logs.String()))
		default:
		}
		if data, err := os.ReadFile(statePath); err == nil {
			var state sharedObserverState
			if json.Unmarshal(data, &state) == nil && strings.TrimSpace(state.BaseURL) != "" && state.PID != stalePID {
				return state
			}
		}
		time.Sleep(100 * time.Millisecond)
	}
	t.Fatalf("observer did not rewrite %s with a fresh PID within %s\n%s", statePath, timeout, strings.TrimSpace(logs.String()))
	return sharedObserverState{}
}
