package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"runtime"
	"slices"
	"strconv"
	"strings"
	"testing"
	"time"
)

type failingObserverListener struct{}

func (failingObserverListener) Accept() (net.Conn, error) {
	return nil, errors.New("forced listener failure")
}

func (failingObserverListener) Close() error   { return nil }
func (failingObserverListener) Addr() net.Addr { return failingObserverAddr{} }

type failingObserverAddr struct{}

func (failingObserverAddr) Network() string { return "tcp" }
func (failingObserverAddr) String() string  { return "127.0.0.1:0" }

func TestManagedStopRequiresLoopbackBearerAndQueuesOnce(t *testing.T) {
	stop := make(chan struct{}, 1)
	mux := http.NewServeMux()
	registerManagedStop(mux, "secret", stop)
	tests := []struct {
		name, remote, token string
		status              int
	}{
		{"remote", "192.0.2.1:1234", "Bearer secret", http.StatusUnauthorized},
		{"missing", "127.0.0.1:1234", "", http.StatusUnauthorized},
		{"wrong", "127.0.0.1:1234", "Bearer wrong", http.StatusUnauthorized},
		{"valid", "127.0.0.1:1234", "Bearer secret", http.StatusAccepted},
		{"duplicate", "127.0.0.1:1234", "Bearer secret", http.StatusConflict},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			request := httptest.NewRequest(http.MethodPost, managedStopPath, nil)
			request.RemoteAddr = test.remote
			request.Header.Set("Authorization", test.token)
			response := httptest.NewRecorder()
			mux.ServeHTTP(response, request)
			if response.Code != test.status {
				t.Fatalf("status = %d, want %d", response.Code, test.status)
			}
		})
	}
}

func TestManagedServeFailureReturnsErrorAndCleansState(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	environment, cleanup, err := createManagedLaunchCapability()
	if err != nil {
		t.Fatal(err)
	}
	defer cleanup()
	for _, entry := range environment {
		key, value, _ := strings.Cut(entry, "=")
		t.Setenv(key, value)
	}
	t.Setenv("OBSTUDIO_OWNER", "cli")
	t.Setenv("OBSTUDIO_MODE", managedObserverMode)
	originalListen := listenObserverHTTP
	listenObserverHTTP = func(string, string) (net.Listener, error) { return failingObserverListener{}, nil }
	t.Cleanup(func() { listenObserverHTTP = originalListen })
	err = run(runConfig{
		host: "127.0.0.1", observerHTTPPort: strconv.Itoa(pickSmokePort(t)),
		otlpHTTPPort: strconv.Itoa(pickSmokePort(t)), otlpGRPCHost: "127.0.0.1", otlpGRPCPort: strconv.Itoa(pickSmokePort(t)),
	})
	if err == nil || !strings.Contains(err.Error(), "forced listener failure") {
		t.Fatalf("managed serve failure = %v", err)
	}
	for _, path := range []string{managedControlStatePath(), sharedObserverStatePath()} {
		if _, statErr := os.Stat(path); !errors.Is(statErr, os.ErrNotExist) {
			t.Fatalf("serve failure left state %s: %v", path, statErr)
		}
	}
}

func TestManagedStopDoesNotForwardBearerOnRedirect(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	redirected := false
	target := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) { redirected = true }))
	defer target.Close()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/api/health":
			_ = json.NewEncoder(w).Encode(sharedObserverHealth{Kind: "obstudio", APIVersion: "v1", Owner: "cli", Mode: managedObserverMode})
		case managedStopPath:
			http.Redirect(w, r, target.URL, http.StatusTemporaryRedirect)
		}
	}))
	defer server.Close()
	if err := writeSharedObserverState(managedControlStatePath(), sharedObserverState{HealthURL: server.URL + "/api/health", ControlToken: "secret"}); err != nil {
		t.Fatal(err)
	}
	if err := stopManagedObserver(server.Client()); err == nil || !strings.Contains(err.Error(), "HTTP 307") {
		t.Fatalf("redirecting stop = %v", err)
	}
	if redirected {
		t.Fatal("stop request followed redirect and exposed its bearer token")
	}
}

func TestManagedArgsPersistForRestart(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	want := []string{"--host", "127.0.0.1", "--observer-http-port", "43100", "--env-file", "/tmp/observer.env"}
	wantEnv := []string{"PORT=43100", "OTLP_HTTP_PORT=43118"}
	if err := writeManagedLaunch(managedLaunch{Args: want, Env: wantEnv}); err != nil {
		t.Fatalf("write args: %v", err)
	}
	got, err := readManagedLaunch()
	if err != nil {
		t.Fatalf("read args: %v", err)
	}
	if !reflect.DeepEqual(got.Args, want) || !reflect.DeepEqual(got.Env, wantEnv) {
		t.Fatalf("launch = %#v", got)
	}
	info, err := os.Stat(managedStatePath())
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Fatalf("mode = %#o", info.Mode().Perm())
	}
}

func TestManagedRestartMergesExplicitFlagsOverSavedLaunch(t *testing.T) {
	saved := []string{"--host", "127.0.0.1", "--observer-http-port", "3000", "--env-file", "/tmp/original.env"}
	current := []string{"--observer-http-port", "4000"}
	want := []string{"--host", "127.0.0.1", "--observer-http-port", "4000", "--env-file", "/tmp/original.env"}
	if got := mergeManagedArgs(saved, current); !reflect.DeepEqual(got, want) {
		t.Fatalf("merged args = %#v, want %#v", got, want)
	}
}

func TestManagedRunArgsCanonicalizesEnvFile(t *testing.T) {
	working := t.TempDir()
	previous, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Chdir(working); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chdir(previous) })
	args, err := managedRunArgs(runConfig{envFile: "observer.env"})
	if err != nil {
		t.Fatal(err)
	}
	want, err := filepath.Abs("observer.env")
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(args, []string{"--env-file", want}) {
		t.Fatalf("args = %#v", args)
	}
}

func TestManagedBindRequiresLoopback(t *testing.T) {
	for _, host := range []string{"127.0.0.1", "::1", "localhost"} {
		if !isLoopbackBindHost(host) {
			t.Fatalf("loopback host %q rejected", host)
		}
	}
	if isLoopbackBindHost("192.0.2.10") {
		t.Fatal("non-loopback host accepted")
	}
	if isLoopbackBindHost("[::1]") {
		t.Fatal("bracketed IPv6 host accepted even though the bind path expects raw ::1")
	}
}

func TestPrepareManagedLaunchRejectsCorruptSavedState(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	if err := os.MkdirAll(filepath.Dir(managedStatePath()), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(managedStatePath(), []byte("not-json"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := prepareManagedLaunch(runConfig{}, true); err == nil || !strings.Contains(err.Error(), "read managed Observer configuration") {
		t.Fatalf("prepare with corrupt state = %v", err)
	}
}

func TestFreshStartIgnoresSavedWorkingDirectory(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	if err := writeManagedLaunch(managedLaunch{WorkingDirectory: filepath.Join(home, "deleted")}); err != nil {
		t.Fatal(err)
	}
	launch, err := prepareManagedLaunch(runConfig{}, false)
	if err != nil {
		t.Fatal(err)
	}
	if launch.workingDirectory == filepath.Join(home, "deleted") {
		t.Fatal("fresh start restored the previous working directory")
	}
}

func TestManagedLaunchCapabilityIsOneTime(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	environment, cleanup, err := createManagedLaunchCapability()
	if err != nil {
		t.Fatal(err)
	}
	defer cleanup()
	for _, entry := range environment {
		key, value, _ := strings.Cut(entry, "=")
		t.Setenv(key, value)
	}
	if !consumeManagedLaunchCapability() {
		t.Fatal("launcher capability was rejected")
	}
	if consumeManagedLaunchCapability() {
		t.Fatal("launcher capability was reusable")
	}
}

func TestPrepareManagedLaunchDoesNotPersistStagedWeaverPath(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	externalWeaver := filepath.Join(t.TempDir(), installedWeaverName(os.Args[0]))
	if err := os.WriteFile(externalWeaver, []byte("external-weaver"), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("WEAVER_PATH", externalWeaver)
	launch, err := prepareManagedLaunch(runConfig{}, false)
	if err != nil {
		t.Fatal(err)
	}
	if got := managedEnvironmentValue(launch.state.Env, "WEAVER_PATH"); got != externalWeaver {
		t.Fatalf("persisted Weaver path = %q, want %q", got, externalWeaver)
	}
	if got := managedEnvironmentValue(launch.environment, "WEAVER_PATH"); got == externalWeaver || filepath.Dir(got) != filepath.Dir(launch.executable) {
		t.Fatalf("child Weaver path = %q, executable = %q", got, launch.executable)
	}
}

func TestPrepareManagedLaunchStagesEnvFileWeaver(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	working := t.TempDir()
	previous, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Chdir(working); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chdir(previous) })
	previousWeaver, hadWeaver := os.LookupEnv("WEAVER_PATH")
	_ = os.Unsetenv("WEAVER_PATH")
	envFileShellPrecedence.Lock()
	_, hadPrecedence := envFileShellPrecedence.keys["WEAVER_PATH"]
	delete(envFileShellPrecedence.keys, "WEAVER_PATH")
	envFileShellPrecedence.Unlock()
	t.Cleanup(func() {
		if hadWeaver {
			_ = os.Setenv("WEAVER_PATH", previousWeaver)
		} else {
			_ = os.Unsetenv("WEAVER_PATH")
		}
		envFileShellPrecedence.Lock()
		if hadPrecedence {
			envFileShellPrecedence.keys["WEAVER_PATH"] = struct{}{}
		} else {
			delete(envFileShellPrecedence.keys, "WEAVER_PATH")
		}
		envFileShellPrecedence.Unlock()
	})
	weaver := filepath.Join(working, "tools", installedWeaverName(os.Args[0]))
	if err := os.MkdirAll(filepath.Dir(weaver), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(weaver, []byte("env-weaver"), 0o755); err != nil {
		t.Fatal(err)
	}
	envFile := filepath.Join(working, "observer.env")
	if err := os.WriteFile(envFile, []byte("WEAVER_PATH=tools/"+filepath.Base(weaver)+"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	launch, err := prepareManagedLaunch(runConfig{envFile: envFile}, false)
	if err != nil {
		t.Fatal(err)
	}
	stagedWeaver := managedEnvironmentValue(launch.environment, "WEAVER_PATH")
	if filepath.Dir(stagedWeaver) != filepath.Dir(launch.executable) {
		t.Fatalf("env-file Weaver was not staged: %q", stagedWeaver)
	}
	if managedEnvironmentValue(launch.state.Env, "WEAVER_PATH") != "" {
		t.Fatal("env-file Weaver leaked into persisted shell environment")
	}
	if managedEnvironmentValue(launch.baseEnvironment, "WEAVER_PATH") != "" {
		t.Fatal("env-file Weaver leaked into the child's inherited shell environment")
	}
}

func TestCurrentManagedEnvironmentCanonicalizesRelativeWeaverPath(t *testing.T) {
	directory := t.TempDir()
	previous, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Chdir(directory); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chdir(previous) })
	t.Setenv("WEAVER_PATH", "bin/weaver")
	resolvedDirectory, err := filepath.EvalSymlinks(directory)
	if err != nil {
		t.Fatal(err)
	}
	if got, want := managedEnvironmentValue(currentManagedEnvironment(), "WEAVER_PATH"), filepath.Join(resolvedDirectory, "bin", "weaver"); got != want {
		t.Fatalf("canonical Weaver path = %q, want %q", got, want)
	}
}

func TestManagedEnvironmentPreservesPublicMCPURLForRestart(t *testing.T) {
	const publicMCPURL = "https://observer.example.test/team/mcp"
	t.Setenv(observerPublicMCPURLEnv, publicMCPURL)

	environment := currentManagedEnvironment()
	if got := managedEnvironmentValue(environment, observerPublicMCPURLEnv); got != publicMCPURL {
		t.Fatalf("managed public MCP URL = %q, want %q", got, publicMCPURL)
	}

	t.Setenv(observerPublicMCPURLEnv, "")
	resolved := resolveManagedRunConfig(runConfig{}, environment)
	if resolved.publicMCPURL != publicMCPURL {
		t.Fatalf("restored public MCP URL = %q, want %q", resolved.publicMCPURL, publicMCPURL)
	}
	if err := validateRunConfig(resolved); err != nil {
		t.Fatal(err)
	}
}

func TestStageManagedRuntimeIsBundleVersioned(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	sourceDir := t.TempDir()
	executable := filepath.Join(sourceDir, "obstudio")
	if runtime.GOOS == "windows" {
		executable += ".exe"
	}
	if err := os.WriteFile(executable, []byte("version-one"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(sourceDir, installedWeaverName(executable)), []byte("weaver-one"), 0o755); err != nil {
		t.Fatal(err)
	}
	first, err := stageManagedRuntime(executable)
	if err != nil {
		t.Fatal(err)
	}
	again, err := stageManagedRuntime(executable)
	if err != nil {
		t.Fatal(err)
	}
	if first != again {
		t.Fatalf("same bundle staged at %q and %q", first, again)
	}
	if err := os.WriteFile(executable, []byte("version-two"), 0o755); err != nil {
		t.Fatal(err)
	}
	second, err := stageManagedRuntime(executable)
	if err != nil {
		t.Fatal(err)
	}
	if first == second {
		t.Fatal("higher-version runtime reused the old bundle path")
	}
	if _, err := os.Stat(filepath.Join(filepath.Dir(second), installedWeaverName(executable))); err != nil {
		t.Fatalf("staged Weaver: %v", err)
	}
}

func TestPruneManagedRuntimesKeepsActiveAndRollback(t *testing.T) {
	root := t.TempDir()
	active := filepath.Join(root, strings.Repeat("a", 64))
	rollback := filepath.Join(root, strings.Repeat("b", 64))
	old := filepath.Join(root, strings.Repeat("c", 64))
	other := filepath.Join(root, "user-content")
	for _, path := range []string{active, rollback, old, other} {
		if err := os.Mkdir(path, 0o700); err != nil {
			t.Fatal(err)
		}
	}
	now := time.Now()
	if err := os.Chtimes(rollback, now, now); err != nil {
		t.Fatal(err)
	}
	if err := os.Chtimes(old, now.Add(-time.Hour), now.Add(-time.Hour)); err != nil {
		t.Fatal(err)
	}
	if err := pruneManagedRuntimes(active); err != nil {
		t.Fatal(err)
	}
	for _, path := range []string{active, rollback, other} {
		if _, err := os.Stat(path); err != nil {
			t.Fatalf("retained path %s: %v", path, err)
		}
	}
	if _, err := os.Stat(old); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("old runtime still exists: %v", err)
	}
}

func TestManagedObserverHealthPreservesOwnership(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_ = json.NewEncoder(w).Encode(sharedObserverHealth{Kind: "obstudio", APIVersion: "v1", Owner: "extension", Mode: "managed", Version: "v1"})
	}))
	defer server.Close()
	if err := writeSharedObserverState(managedControlStatePath(), sharedObserverState{HealthURL: server.URL, ControlToken: "secret"}); err != nil {
		t.Fatal(err)
	}
	health, _, err := managedObserverHealth(server.Client())
	if err != nil {
		t.Fatal(err)
	}
	if health.Owner != "extension" || health.Mode != "managed" {
		t.Fatalf("health = %+v", health)
	}
}

func TestManagedObserverDiscoveryIgnoresSharedOwnerReplacement(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	managed := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_ = json.NewEncoder(w).Encode(sharedObserverHealth{Kind: "obstudio", APIVersion: "v1", Owner: "cli", Mode: managedObserverMode})
	}))
	defer managed.Close()
	foreground := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_ = json.NewEncoder(w).Encode(sharedObserverHealth{Kind: "obstudio", APIVersion: "v1", Owner: "cli", Mode: "standalone"})
	}))
	defer foreground.Close()
	if err := writeSharedObserverState(managedControlStatePath(), sharedObserverState{HealthURL: managed.URL, ControlToken: "managed"}); err != nil {
		t.Fatal(err)
	}
	if err := writeSharedObserverState(sharedObserverStatePath(), sharedObserverState{HealthURL: foreground.URL, ControlToken: "foreground"}); err != nil {
		t.Fatal(err)
	}
	health, state, err := managedObserverHealth(managed.Client())
	if err != nil {
		t.Fatal(err)
	}
	if health.Mode != managedObserverMode || state.ControlToken != "managed" {
		t.Fatalf("managed discovery = %+v, %+v", health, state)
	}
}

func TestManagedObserverMatchesConfiguredMCPURL(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_ = json.NewEncoder(w).Encode(sharedObserverHealth{
			Kind: "obstudio", APIVersion: "v1", Owner: "cli", Mode: managedObserverMode,
		})
	}))
	defer server.Close()
	state := sharedObserverState{HealthURL: server.URL, MCPURL: server.URL + "/mcp"}
	if err := writeSharedObserverState(managedControlStatePath(), state); err != nil {
		t.Fatal(err)
	}
	if !managedObserverMatchesURL(server.URL+"/mcp/", server.Client()) {
		t.Fatal("expected configured managed MCP endpoint to match")
	}
	localhostURL := strings.Replace(server.URL, "127.0.0.1", "LOCALHOST", 1) + "/mcp"
	if !managedObserverMatchesURL(localhostURL, server.Client()) {
		t.Fatal("expected equivalent localhost managed MCP endpoint to match")
	}
	otherLoopbackURL := strings.Replace(server.URL, "127.0.0.1", "127.0.0.2", 1) + "/mcp"
	if managedObserverMatchesURL(otherLoopbackURL, server.Client()) {
		t.Fatal("distinct loopback addresses must not identify the same managed endpoint")
	}
	ipv6LoopbackURL := "http://[::1]:" + strings.TrimPrefix(server.URL, "http://127.0.0.1:") + "/mcp"
	if managedObserverMatchesURL(ipv6LoopbackURL, server.Client()) {
		t.Fatal("IPv4 and IPv6 loopback addresses must not identify the same managed endpoint")
	}
	if managedObserverMatchesURL(server.URL+"/other/mcp", server.Client()) {
		t.Fatal("mismatched shared endpoint must not recommend managed restart")
	}
}

func TestLifecycleRefusesUncertainManagedHealth(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	if err := writeSharedObserverState(managedControlStatePath(), sharedObserverState{
		HealthURL: "http://127.0.0.1:1/api/health",
		MCPURL:    "http://127.0.0.1:1/mcp",
	}); err != nil {
		t.Fatal(err)
	}
	client := &http.Client{Timeout: 50 * time.Millisecond}
	if err := stopManagedObserver(client); err == nil || !strings.Contains(err.Error(), "refusing to assume it stopped") {
		t.Fatalf("stop with uncertain health = %v", err)
	}
	if err := startManagedObserver(runConfig{}); err == nil || !strings.Contains(err.Error(), "health is unavailable") {
		t.Fatalf("start with uncertain health = %v", err)
	}
	if err := newStatusCmd().Execute(); err == nil || !strings.Contains(err.Error(), "health is unavailable") {
		t.Fatalf("status with uncertain health = %v", err)
	}
}

func TestStatusDoesNotAttributeStalePIDToReplacementOwner(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_ = json.NewEncoder(w).Encode(sharedObserverHealth{
			Kind: "obstudio", APIVersion: "v1", Owner: "extension", Mode: "managed", Version: "replacement",
		})
	}))
	defer server.Close()
	if err := writeSharedObserverState(managedControlStatePath(), sharedObserverState{HealthURL: server.URL, BaseURL: server.URL, PID: 4242}); err != nil {
		t.Fatal(err)
	}
	err := newStatusCmd().Execute()
	if err == nil || !strings.Contains(err.Error(), "extension ownership") || strings.Contains(err.Error(), "4242") {
		t.Fatalf("status with replacement owner = %v", err)
	}
}

func TestPrepareManagedLaunchRejectsNonLoopbackGRPCHost(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("OTLP_GRPC_HOST", "0.0.0.0")
	if _, err := prepareManagedLaunch(runConfig{}, false); err == nil || !strings.Contains(err.Error(), "loopback OTLP_GRPC_HOST") {
		t.Fatalf("prepare with non-loopback gRPC host = %v", err)
	}
}

func TestResolveManagedRunConfigUsesChildEnvironmentPrecedence(t *testing.T) {
	t.Setenv("PORT", "invalid")
	resolved := resolveManagedRunConfig(runConfig{}, []string{"PORT=4123"})
	if resolved.observerHTTPPort != "4123" {
		t.Fatalf("resolved port = %q", resolved.observerHTTPPort)
	}
	if err := validateRunConfig(resolved); err != nil {
		t.Fatal(err)
	}
}

func TestStageManagedRuntimeIncludesConfiguredWeaver(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	sourceDir := t.TempDir()
	executable := filepath.Join(sourceDir, smokeBinaryName())
	weaver := filepath.Join(t.TempDir(), installedWeaverName(executable))
	if err := os.WriteFile(executable, []byte("observer"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(sourceDir, installedWeaverName(executable)), []byte("sibling-weaver"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(weaver, []byte("path-weaver"), 0o755); err != nil {
		t.Fatal(err)
	}
	staged, err := stageManagedRuntimeWithWeaver(executable, weaver)
	if err != nil {
		t.Fatal(err)
	}
	got, err := os.ReadFile(filepath.Join(filepath.Dir(staged), installedWeaverName(executable)))
	if err != nil || string(got) != "path-weaver" {
		t.Fatalf("staged configured Weaver = %q, %v", got, err)
	}
}

func TestStageManagedRuntimeRejectsConfiguredWeaverDirectory(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	executable := filepath.Join(t.TempDir(), smokeBinaryName())
	if err := os.WriteFile(executable, []byte("observer"), 0o755); err != nil {
		t.Fatal(err)
	}
	if _, err := stageManagedRuntimeWithWeaver(executable, t.TempDir()); err == nil || !strings.Contains(err.Error(), "not a regular file") {
		t.Fatalf("stage with Weaver directory = %v", err)
	}
}

func TestManagedBundleDigestPreservesFileBoundaries(t *testing.T) {
	directory := t.TempDir()
	paths := func(first, second string) []string {
		firstPath, secondPath := filepath.Join(directory, first+second+"-first"), filepath.Join(directory, first+second+"-second")
		if err := os.WriteFile(firstPath, []byte(first), 0o600); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(secondPath, []byte(second), 0o600); err != nil {
			t.Fatal(err)
		}
		return []string{firstPath, secondPath}
	}
	left, err := managedBundleDigest(paths("ab", "c"))
	if err != nil {
		t.Fatal(err)
	}
	right, err := managedBundleDigest(paths("a", "bc"))
	if err != nil {
		t.Fatal(err)
	}
	if left == right {
		t.Fatal("bundle digest ignored file boundaries")
	}
}

func TestRestartRefusesForegroundObserverWithoutManagedState(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_ = json.NewEncoder(w).Encode(sharedObserverHealth{Kind: "obstudio", APIVersion: "v1", Owner: "extension", Mode: "managed"})
	}))
	defer server.Close()
	if err := writeSharedObserverState(sharedObserverStatePath(), sharedObserverState{HealthURL: server.URL, MCPURL: server.URL + "/mcp"}); err != nil {
		t.Fatal(err)
	}
	err := newRestartCmd().Execute()
	if err == nil || !strings.Contains(err.Error(), "another Observer is already running") {
		t.Fatalf("restart with foreground owner = %v", err)
	}
}

func TestRestartRechecksSharedOwnerAfterManagedStop(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	var extension *httptest.Server
	extension = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_ = json.NewEncoder(w).Encode(sharedObserverHealth{Kind: "obstudio", APIVersion: "v1", Owner: "extension", Mode: "managed", Endpoints: map[string]string{"mcp": extension.URL + "/mcp"}})
	}))
	defer extension.Close()
	var managed *httptest.Server
	managed = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == managedStopPath {
			_ = os.Remove(managedControlStatePath())
			_ = writeSharedObserverState(sharedObserverStatePath(), sharedObserverState{HealthURL: extension.URL, MCPURL: extension.URL + "/mcp"})
			w.WriteHeader(http.StatusAccepted)
			return
		}
		_ = json.NewEncoder(w).Encode(sharedObserverHealth{Kind: "obstudio", APIVersion: "v1", Owner: "cli", Mode: managedObserverMode, Endpoints: map[string]string{"mcp": managed.URL + "/mcp"}})
	}))
	defer managed.Close()
	managedState := sharedObserverState{HealthURL: managed.URL + "/api/health", MCPURL: managed.URL + "/mcp", ControlToken: "secret"}
	if err := writeSharedObserverState(managedControlStatePath(), managedState); err != nil {
		t.Fatal(err)
	}
	if err := writeSharedObserverState(sharedObserverStatePath(), managedState); err != nil {
		t.Fatal(err)
	}
	err := newRestartCmd().Execute()
	if err == nil || !strings.Contains(err.Error(), "another Observer is already running") {
		t.Fatalf("restart after shared owner replacement = %v", err)
	}
	if _, statErr := os.Stat(managedControlStatePath()); !errors.Is(statErr, os.ErrNotExist) {
		t.Fatalf("managed state after cooperative stop = %v", statErr)
	}
}

func TestManagedLifecycleRealBinary(t *testing.T) {
	moduleRoot := observerModuleRoot(t)
	home := t.TempDir()
	binary := filepath.Join(t.TempDir(), smokeBinaryName())
	build := exec.Command("go", "build", "-o", binary, "./cmd/obstudio")
	build.Dir = moduleRoot
	if output, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build lifecycle binary: %v\n%s", err, output)
	}
	httpPorts := []int{pickSmokePort(t), pickSmokePort(t)}
	otlpHTTPPort, otlpGRPCPort := pickSmokePort(t), pickSmokePort(t)
	baseEnv := append(os.Environ(), smokeHomeEnv(home)...)
	baseEnv = append(baseEnv, disableSharedObserverDetectionEnv+"=1")
	envFile := filepath.Join(t.TempDir(), "observer.env")
	if err := os.WriteFile(envFile, []byte(fmt.Sprintf("OTLP_HTTP_PORT=%d\nOTLP_GRPC_PORT=%d\n", otlpHTTPPort, otlpGRPCPort)), 0o600); err != nil {
		t.Fatal(err)
	}
	previewPath := filepath.Join(home, "preview.json")
	startEnv := append(append([]string{}, baseEnv...), "OBSTUDIO_ENV_FILE="+envFile, "OBSTUDIO_DASHBOARDS_PREVIEW="+previewPath)
	runIn := func(dir string, env []string, args ...string) (string, error) {
		command := exec.Command(binary, args...)
		command.Env = env
		command.Dir = dir
		output, err := command.CombinedOutput()
		return string(output), err
	}
	run := func(env []string, args ...string) (string, error) { return runIn("", env, args...) }
	t.Cleanup(func() { _, _ = run(baseEnv, "stop") })
	type startResult struct {
		port   int
		output string
		err    error
	}
	results := make(chan startResult, len(httpPorts))
	for _, port := range httpPorts {
		go func() {
			output, err := run(startEnv, "start", "--observer-http-port", strconv.Itoa(port))
			results <- startResult{port: port, output: output, err: err}
		}()
	}
	httpPort := 0
	failedStarts := 0
	for range httpPorts {
		result := <-results
		if result.err == nil {
			httpPort = result.port
		} else if strings.Contains(result.output, "already running") {
			failedStarts++
		} else {
			t.Fatalf("concurrent start on %d: %v\n%s", result.port, result.err, result.output)
		}
	}
	if httpPort == 0 || failedStarts != 1 {
		t.Fatalf("concurrent starts: successful port %d, failed starts %d", httpPort, failedStarts)
	}
	missingEnv := filepath.Join(t.TempDir(), "missing.env")
	if output, err := run(baseEnv, "restart", "--env-file", missingEnv); err == nil || !strings.Contains(output, "load env file") {
		t.Fatalf("restart with missing env = %v, output %q", err, output)
	}
	if output, err := run(baseEnv, "status"); err != nil || !strings.Contains(output, fmt.Sprintf(":%d", httpPort)) {
		t.Fatalf("status after failed restart: %v\n%s", err, output)
	}
	if output, err := run(baseEnv, "restart", "--observer-http-port", "invalid"); err == nil || !strings.Contains(output, "valid TCP port") {
		t.Fatalf("restart with invalid port = %v, output %q", err, output)
	}
	if output, err := run(baseEnv, "status"); err != nil || !strings.Contains(output, fmt.Sprintf(":%d", httpPort)) {
		t.Fatalf("status after invalid restart: %v\n%s", err, output)
	}
	restartedPort := pickSmokePort(t)
	otherDirectory := t.TempDir()
	if output, err := runIn(otherDirectory, baseEnv, "restart", "--observer-http-port", strconv.Itoa(restartedPort)); err != nil {
		t.Fatalf("restart: %v\n%s", err, output)
	}
	if output, err := run(baseEnv, "status"); err != nil || !strings.Contains(output, fmt.Sprintf(":%d", restartedPort)) {
		t.Fatalf("status after restart: %v\n%s", err, output)
	}
	state, err := readSharedObserverState(filepath.Join(home, sharedObserverStateDirName, managedControlFileName))
	if err != nil {
		t.Fatal(err)
	}
	response, err := http.Get(state.HealthURL)
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	var health sharedObserverHealth
	if err := json.NewDecoder(response.Body).Decode(&health); err != nil {
		t.Fatal(err)
	}
	if got, want := health.Endpoints["otlpHttp"], fmt.Sprintf("http://127.0.0.1:%d", otlpHTTPPort); got != want {
		t.Fatalf("OTLP/HTTP after restart = %q, want %q", got, want)
	}
	if got, want := health.Endpoints["otlpGrpc"], fmt.Sprintf("127.0.0.1:%d", otlpGRPCPort); got != want {
		t.Fatalf("OTLP/gRPC after restart = %q, want %q", got, want)
	}
	launchData, err := os.ReadFile(filepath.Join(home, sharedObserverStateDirName, managedStateFileName))
	if err != nil {
		t.Fatal(err)
	}
	var launchState managedLaunch
	if err := json.Unmarshal(launchData, &launchState); err != nil {
		t.Fatal(err)
	}
	if launchState.WorkingDirectory == otherDirectory {
		t.Fatalf("restart replaced saved working directory with %q", otherDirectory)
	}
	if !slices.Contains(launchState.Env, "OBSTUDIO_DASHBOARDS_PREVIEW="+previewPath) {
		t.Fatalf("non-network launch environment was not preserved: %v", launchState.Env)
	}
	if output, err := run(baseEnv, "stop"); err != nil {
		t.Fatalf("stop: %v\n%s", err, output)
	}
}

func TestManagedUpgradeActivatesOnlyAfterRestart(t *testing.T) {
	moduleRoot := observerModuleRoot(t)
	home := t.TempDir()
	buildBinary := func(version string) string {
		binary := filepath.Join(t.TempDir(), smokeBinaryName())
		command := exec.Command("go", "build", "-ldflags", "-X main.version="+version, "-o", binary, "./cmd/obstudio")
		command.Dir = moduleRoot
		if output, err := command.CombinedOutput(); err != nil {
			t.Fatalf("build %s lifecycle binary: %v\n%s", version, err, output)
		}
		weaver := filepath.Join(filepath.Dir(binary), installedWeaverName(binary))
		if err := copyFile(binary, weaver); err != nil {
			t.Fatalf("bundle %s lifecycle Weaver: %v", version, err)
		}
		if err := os.Chmod(weaver, 0o755); err != nil {
			t.Fatalf("chmod %s lifecycle Weaver: %v", version, err)
		}
		return binary
	}
	v1, v2 := buildBinary("upgrade-v1"), buildBinary("upgrade-v2")
	httpPort, otlpHTTPPort, otlpGRPCPort := pickSmokePort(t), pickSmokePort(t), pickSmokePort(t)
	baseEnv := append(os.Environ(), smokeHomeEnv(home)...)
	baseEnv = append(baseEnv, disableSharedObserverDetectionEnv+"=1",
		"OTLP_HTTP_PORT="+strconv.Itoa(otlpHTTPPort), "OTLP_GRPC_PORT="+strconv.Itoa(otlpGRPCPort))
	run := func(binary string, args ...string) (string, error) {
		command := exec.Command(binary, args...)
		command.Env = baseEnv
		output, err := command.CombinedOutput()
		return string(output), err
	}
	sharedMCP := fmt.Sprintf("http://127.0.0.1:%d/mcp", httpPort)
	if output, err := run(v1, "install", "--target", "codex"); err != nil {
		t.Fatalf("install v1: %v\n%s", err, output)
	}
	installed := filepath.Join(home, ".codex", "skills", "obstudio", smokeBinaryName())
	t.Cleanup(func() { _, _ = run(installed, "stop") })
	if output, err := run(installed, "start", "--observer-http-port", strconv.Itoa(httpPort)); err != nil {
		t.Fatalf("start v1: %v\n%s", err, output)
	}
	statePath := filepath.Join(home, sharedObserverStateDirName, managedControlFileName)
	before, err := readSharedObserverState(statePath)
	if err != nil {
		t.Fatal(err)
	}
	if output, err := run(v2, "install", "--target", "codex", "--shared-url", sharedMCP); err != nil {
		t.Fatalf("install v2 while v1 runs: %v\n%s", err, output)
	}
	response, err := http.Get(before.HealthURL)
	if err != nil {
		t.Fatal(err)
	}
	var health sharedObserverHealth
	if err := json.NewDecoder(response.Body).Decode(&health); err != nil {
		response.Body.Close()
		t.Fatal(err)
	}
	response.Body.Close()
	if health.Version != "upgrade-v1" {
		t.Fatalf("install activated before restart: version %q", health.Version)
	}
	afterInstall, err := readSharedObserverState(statePath)
	if err != nil {
		t.Fatal(err)
	}
	if afterInstall.PID != before.PID {
		t.Fatalf("install replaced PID %d with %d before restart", before.PID, afterInstall.PID)
	}
	if output, err := run(installed, "restart"); err != nil {
		t.Fatalf("restart into v2: %v\n%s", err, output)
	}
	afterRestart, err := readSharedObserverState(statePath)
	if err != nil {
		t.Fatal(err)
	}
	response, err = http.Get(afterRestart.HealthURL)
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	if err := json.NewDecoder(response.Body).Decode(&health); err != nil {
		t.Fatal(err)
	}
	if health.Version != "upgrade-v2" {
		t.Fatalf("restart health = %+v", health)
	}
}

func TestManagedRunArgsPersistsEnvironmentEnvFile(t *testing.T) {
	envFile := filepath.Join(t.TempDir(), "observer.env")
	t.Setenv("OBSTUDIO_ENV_FILE", envFile)
	args, err := managedRunArgs(runConfig{})
	if err != nil {
		t.Fatal(err)
	}
	if got := managedArgValue(args, "--env-file"); got != envFile {
		t.Fatalf("persisted env file = %q, want %q", got, envFile)
	}
}

func TestRotateManagedLogRetainsOneBoundedBackup(t *testing.T) {
	path := filepath.Join(t.TempDir(), "observer.log")
	writer := &rollingLogWriter{path: path, maxBytes: 8}
	if _, err := writer.Write([]byte("first")); err != nil {
		t.Fatal(err)
	}
	if _, err := writer.Write([]byte("second")); err != nil {
		t.Fatal(err)
	}
	if got, err := os.ReadFile(path + ".1"); err != nil || string(got) != "first" {
		t.Fatalf("rotated log = %q, %v", got, err)
	}
	if got, err := os.ReadFile(path); err != nil || string(got) != "second" {
		t.Fatalf("active log = %q, %v", got, err)
	}
}

func TestManagedLaunchTimeoutTerminatesDelayedChild(t *testing.T) {
	if os.Getenv("OBSTUDIO_TEST_DELAYED_CHILD") == "1" || os.Getenv("OBSTUDIO_TEST_EXIT_CHILD") == "1" {
		if os.Getenv("OBSTUDIO_TEST_WRITE_STATE") == "1" {
			state := sharedObserverState{HealthURL: "http://127.0.0.1:1/api/health", PID: os.Getpid()}
			if err := writeSharedObserverState(managedControlStatePath(), state); err != nil {
				t.Fatal(err)
			}
			if err := writeSharedObserverState(sharedObserverStatePath(), state); err != nil {
				t.Fatal(err)
			}
		}
		if os.Getenv("OBSTUDIO_TEST_EXIT_CHILD") == "1" {
			return
		}
		time.Sleep(10 * time.Second)
		return
	}
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	started := time.Now()
	err := launchManagedObserverWithTimeout(preparedManagedLaunch{
		executable:  os.Args[0],
		args:        []string{"-test.run=^TestManagedLaunchTimeoutTerminatesDelayedChild$"},
		environment: []string{"OBSTUDIO_TEST_DELAYED_CHILD=1", "OBSTUDIO_TEST_WRITE_STATE=1"},
	}, 100*time.Millisecond)
	if err == nil || !strings.Contains(err.Error(), "did not become healthy") {
		t.Fatalf("launch timeout = %v", err)
	}
	if elapsed := time.Since(started); elapsed > 3*time.Second {
		t.Fatalf("timed-out child cleanup took %s", elapsed)
	}
	for _, path := range []string{managedControlStatePath(), sharedObserverStatePath()} {
		if _, statErr := os.Stat(path); !errors.Is(statErr, os.ErrNotExist) {
			t.Fatalf("timed-out child left state %s: %v", path, statErr)
		}
	}
}

func TestManagedLaunchExitCleansPublishedState(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	err := launchManagedObserverWithTimeout(preparedManagedLaunch{
		executable: os.Args[0],
		args:       []string{"-test.run=^TestManagedLaunchTimeoutTerminatesDelayedChild$"},
		environment: []string{
			"OBSTUDIO_TEST_EXIT_CHILD=1", "OBSTUDIO_TEST_WRITE_STATE=1",
		},
	}, 2*time.Second)
	if err == nil || !strings.Contains(err.Error(), "exited before becoming healthy") {
		t.Fatalf("early child exit = %v", err)
	}
	for _, path := range []string{managedControlStatePath(), sharedObserverStatePath()} {
		if _, statErr := os.Stat(path); !errors.Is(statErr, os.ErrNotExist) {
			t.Fatalf("early child exit left state %s: %v", path, statErr)
		}
	}
}
