package main

import (
	"bytes"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"time"

	"github.com/spf13/cobra"
)

const (
	managedObserverMode       = "managed-background"
	managedStopPath           = "/api/runtime/stop"
	managedStateFileName      = "managed-observer.json"
	managedControlFileName    = "managed-control.json"
	managedLockDirName        = "managed-lifecycle.lock"
	managedStartTimeout       = 15 * time.Second
	managedStopTimeout        = 15 * time.Second
	managedLifecyclePollDelay = 100 * time.Millisecond
	managedLogMaxBytes        = 10 * 1024 * 1024
	managedLogPathEnv         = "OBSTUDIO_MANAGED_LOG_PATH"
	managedLaunchFileEnv      = "OBSTUDIO_MANAGED_LAUNCH_FILE"
	managedLaunchTokenEnv     = "OBSTUDIO_MANAGED_LAUNCH_TOKEN"
)

func newLifecycleCommands() []*cobra.Command {
	return []*cobra.Command{newStartCmd(), newStopCmd(), newRestartCmd(), newStatusCmd()}
}

func newStartCmd() *cobra.Command {
	var config runConfig
	cmd := &cobra.Command{Use: "start", Short: "Start a managed Observer in the background", RunE: func(*cobra.Command, []string) error {
		return startManagedObserver(config)
	}}
	cmd.Flags().StringVar(&config.host, "host", "", "Bind address for the Observer UI, MCP HTTP endpoint, and OTLP/HTTP")
	cmd.Flags().StringVar(&config.observerHTTPPort, "observer-http-port", "", "Observer web UI, REST API, and MCP HTTP port")
	cmd.Flags().StringVar(&config.envFile, "env-file", "", "Load KEY=VALUE settings from an env file before startup")
	return cmd
}

func newStopCmd() *cobra.Command {
	return &cobra.Command{Use: "stop", Short: "Stop the managed background Observer", RunE: func(*cobra.Command, []string) error {
		release, err := acquireManagedLifecycleLock()
		if err != nil {
			return err
		}
		defer release()
		return stopManagedObserver(http.DefaultClient)
	}}
}

func newRestartCmd() *cobra.Command {
	var config runConfig
	cmd := &cobra.Command{Use: "restart", Short: "Restart the managed background Observer", RunE: func(*cobra.Command, []string) error {
		release, err := acquireManagedLifecycleLock()
		if err != nil {
			return err
		}
		defer release()
		launch, err := prepareManagedLaunch(config, true)
		if err != nil {
			return err
		}
		if os.Getenv(disableSharedObserverDetectionEnv) == "" {
			if _, managedState, healthErr := managedObserverHealth(http.DefaultClient); healthErr == nil {
				if detected, configured := detectConfiguredSharedObserverURL(http.DefaultClient); configured && !managedEndpointsEqual(detected, managedState.MCPURL) {
					return errors.New("another Observer is already running; stop it from its owner before using obstudio restart")
				}
			}
		}
		if err := stopManagedObserver(http.DefaultClient); err != nil && !errors.Is(err, os.ErrNotExist) {
			return err
		}
		if os.Getenv(disableSharedObserverDetectionEnv) == "" {
			if _, configured := detectConfiguredSharedObserverURL(http.DefaultClient); configured {
				return errors.New("another Observer is already running; stop it from its owner before using obstudio restart")
			}
		}
		return launchManagedObserver(launch)
	}}
	cmd.Flags().StringVar(&config.host, "host", "", "Bind address for the Observer UI, MCP HTTP endpoint, and OTLP/HTTP")
	cmd.Flags().StringVar(&config.observerHTTPPort, "observer-http-port", "", "Observer web UI, REST API, and MCP HTTP port")
	cmd.Flags().StringVar(&config.envFile, "env-file", "", "Load KEY=VALUE settings from an env file before startup")
	return cmd
}

func managedEndpointsEqual(left, right string) bool {
	leftEndpoint, leftErr := canonicalManagedEndpoint(left)
	rightEndpoint, rightErr := canonicalManagedEndpoint(right)
	return leftErr == nil && rightErr == nil && leftEndpoint == rightEndpoint
}

func newStatusCmd() *cobra.Command {
	return &cobra.Command{Use: "status", Short: "Show Observer status and ownership", RunE: func(*cobra.Command, []string) error {
		health, state, err := managedObserverHealth(http.DefaultClient)
		if err != nil {
			if errors.Is(err, os.ErrNotExist) {
				fmt.Println("Managed Observer is not running.")
				return nil
			}
			return fmt.Errorf("managed Observer state exists but health is unavailable: %w", err)
		}
		if health.Owner != "cli" || health.Mode != managedObserverMode {
			return fmt.Errorf("Observer at %s is running under %s ownership in %s mode; managed CLI state is stale", state.BaseURL, health.Owner, health.Mode)
		}
		fmt.Printf("Observer %s is running (%s, PID %d)\n%s\n", health.Version, health.Mode, state.PID, state.BaseURL)
		return nil
	}}
}

func startManagedObserver(config runConfig) error {
	release, err := acquireManagedLifecycleLock()
	if err != nil {
		return err
	}
	defer release()
	if health, _, healthErr := managedObserverHealth(http.DefaultClient); healthErr == nil {
		if health.Mode == managedObserverMode {
			return errors.New("managed Observer is already running")
		}
		return fmt.Errorf("Observer is already running in %s mode; stop it from its owner before using obstudio start", health.Mode)
	} else if !errors.Is(healthErr, os.ErrNotExist) {
		return fmt.Errorf("managed Observer state exists but health is unavailable; run `obstudio status` and retry or remove stale state after verifying the process is stopped: %w", healthErr)
	}
	if os.Getenv(disableSharedObserverDetectionEnv) == "" {
		if _, ok := detectConfiguredSharedObserverURL(http.DefaultClient); ok {
			return errors.New("Observer is already running; stop it from its owner before using obstudio start")
		}
	}
	launch, err := prepareManagedLaunch(config, false)
	if err != nil {
		return err
	}
	return launchManagedObserver(launch)
}

type preparedManagedLaunch struct {
	executable                         string
	args, baseEnvironment, environment []string
	workingDirectory                   string
	state                              managedLaunch
}

func prepareManagedLaunch(config runConfig, restoreSaved bool) (preparedManagedLaunch, error) {
	args, err := managedRunArgs(config)
	if err != nil {
		return preparedManagedLaunch{}, err
	}
	managedEnv := currentManagedEnvironment()
	workingDirectory, err := os.Getwd()
	if err != nil {
		return preparedManagedLaunch{}, fmt.Errorf("resolve managed Observer working directory: %w", err)
	}
	if restoreSaved {
		if saved, loadErr := readManagedLaunch(); loadErr == nil {
			args = mergeManagedArgs(saved.Args, args)
			managedEnv = mergeManagedEnvironment(saved.Env, managedEnv)
			if saved.WorkingDirectory != "" {
				workingDirectory = saved.WorkingDirectory
			}
		} else if !errors.Is(loadErr, os.ErrNotExist) {
			return preparedManagedLaunch{}, fmt.Errorf("read managed Observer configuration: %w", loadErr)
		}
	}
	if info, statErr := os.Stat(workingDirectory); statErr != nil || !info.IsDir() {
		if statErr == nil {
			statErr = errors.New("not a directory")
		}
		return preparedManagedLaunch{}, fmt.Errorf("managed Observer working directory %q is unavailable: %w", workingDirectory, statErr)
	}
	effectiveEnvFile := managedArgValue(args, "--env-file")
	childBaseEnvironment := os.Environ()
	if err := loadConfiguredEnvFile(effectiveEnvFile); err != nil {
		return preparedManagedLaunch{}, err
	}
	effectiveConfig := config
	effectiveConfig.host = managedArgValue(args, "--host")
	effectiveConfig.observerHTTPPort = managedArgValue(args, "--observer-http-port")
	resolvedConfig := resolveManagedRunConfig(effectiveConfig, managedEnv)
	if !isLoopbackBindHost(resolvedConfig.host) {
		return preparedManagedLaunch{}, errors.New("managed Observer requires a loopback --host; use foreground mode for LAN binding")
	}
	if !isLoopbackBindHost(resolvedConfig.otlpGRPCHost) {
		return preparedManagedLaunch{}, errors.New("managed Observer requires a loopback OTLP_GRPC_HOST; use foreground mode for LAN binding")
	}
	if err := validateRunConfig(resolvedConfig); err != nil {
		return preparedManagedLaunch{}, err
	}
	executable, err := os.Executable()
	if err != nil {
		return preparedManagedLaunch{}, fmt.Errorf("resolve obstudio executable: %w", err)
	}
	executable, err = filepath.EvalSymlinks(executable)
	if err != nil {
		return preparedManagedLaunch{}, fmt.Errorf("resolve obstudio executable symlinks: %w", err)
	}
	persistedEnv := slices.Clone(managedEnv)
	effectiveWeaver := managedEnvironmentValue(managedEnv, "WEAVER_PATH")
	if effectiveWeaver == "" {
		effectiveWeaver = strings.TrimSpace(os.Getenv("WEAVER_PATH"))
		if effectiveWeaver != "" && !filepath.IsAbs(effectiveWeaver) {
			effectiveWeaver = filepath.Join(workingDirectory, effectiveWeaver)
		}
	}
	executable, err = stageManagedRuntimeWithWeaver(executable, effectiveWeaver)
	if err != nil {
		return preparedManagedLaunch{}, err
	}
	if stagedWeaver := filepath.Join(filepath.Dir(executable), installedWeaverName(executable)); fileExists(stagedWeaver) {
		managedEnv = mergeManagedEnvironment(managedEnv, []string{"WEAVER_PATH=" + stagedWeaver})
	}
	state := managedLaunch{Args: args, Env: persistedEnv, WorkingDirectory: workingDirectory}
	return preparedManagedLaunch{
		executable: executable, args: args, baseEnvironment: childBaseEnvironment,
		environment: managedEnv, workingDirectory: workingDirectory, state: state,
	}, nil
}

func launchManagedObserver(launch preparedManagedLaunch) error {
	return launchManagedObserverWithTimeout(launch, managedStartTimeout)
}

func launchManagedObserverWithTimeout(launch preparedManagedLaunch, startTimeout time.Duration) error {
	command := exec.Command(launch.executable, launch.args...)
	command.Dir = launch.workingDirectory
	baseEnvironment := launch.baseEnvironment
	if baseEnvironment == nil {
		baseEnvironment = os.Environ()
	}
	command.Env = append(slices.Clone(baseEnvironment), launch.environment...)
	command.Env = append(command.Env, "OBSTUDIO_OWNER=cli", "OBSTUDIO_MODE="+managedObserverMode)
	capabilityEnv, cleanupCapability, err := createManagedLaunchCapability()
	if err != nil {
		return err
	}
	defer cleanupCapability()
	command.Env = append(command.Env, capabilityEnv...)
	logPath := filepath.Join(userHome(), sharedObserverStateDirName, "observer.log")
	if err := os.MkdirAll(filepath.Dir(logPath), 0o700); err != nil {
		return err
	}
	command.Env = append(command.Env, managedLogPathEnv+"="+logPath)
	logFile, err := os.OpenFile(os.DevNull, os.O_WRONLY, 0)
	if err != nil {
		return err
	}
	defer logFile.Close()
	command.Stdin = nil
	command.Stdout = logFile
	command.Stderr = logFile
	configureManagedProcess(command)
	if err := command.Start(); err != nil {
		return fmt.Errorf("start managed Observer: %w", err)
	}
	exited := make(chan error, 1)
	go func() { exited <- command.Wait() }()
	deadline := time.Now().Add(startTimeout)
	for time.Now().Before(deadline) {
		select {
		case waitErr := <-exited:
			removeObserverStateForPID(managedControlStatePath(), command.Process.Pid)
			removeObserverStateForPID(sharedObserverStatePath(), command.Process.Pid)
			if waitErr == nil {
				return fmt.Errorf("managed Observer exited before becoming healthy; see %s", logPath)
			}
			return fmt.Errorf("managed Observer exited before becoming healthy: %w; see %s", waitErr, logPath)
		default:
		}
		if health, _, healthErr := managedObserverHealth(http.DefaultClient); healthErr == nil && health.Mode == managedObserverMode {
			if err := writeManagedLaunch(launch.state); err != nil {
				saveErr := fmt.Errorf("save managed Observer configuration: %w", err)
				if cleanupErr := stopManagedObserver(http.DefaultClient); cleanupErr != nil {
					return errors.Join(saveErr, fmt.Errorf("cleanup managed Observer after save failure: %w", cleanupErr))
				}
				return saveErr
			}
			_ = pruneManagedRuntimes(filepath.Dir(launch.executable))
			fmt.Printf("Managed Observer %s started at %s\n", health.Version, health.Endpoints["rest"])
			return nil
		}
		time.Sleep(managedLifecyclePollDelay)
	}
	if killErr := command.Process.Kill(); killErr != nil {
		return fmt.Errorf("managed Observer did not become healthy and could not be terminated: %w; state was preserved; see %s", killErr, logPath)
	}
	select {
	case <-exited:
	case <-time.After(5 * time.Second):
		return fmt.Errorf("managed Observer did not become healthy and termination was not confirmed; state was preserved; see %s", logPath)
	}
	removeObserverStateForPID(managedControlStatePath(), command.Process.Pid)
	removeObserverStateForPID(sharedObserverStatePath(), command.Process.Pid)
	return fmt.Errorf("managed Observer did not become healthy; see %s", logPath)
}

func createManagedLaunchCapability() ([]string, func(), error) {
	directory := filepath.Join(userHome(), sharedObserverStateDirName)
	if err := os.MkdirAll(directory, 0o700); err != nil {
		return nil, nil, err
	}
	tokenBytes := make([]byte, 32)
	if _, err := rand.Read(tokenBytes); err != nil {
		return nil, nil, err
	}
	token := base64.RawURLEncoding.EncodeToString(tokenBytes)
	file, err := os.CreateTemp(directory, ".managed-launch-*")
	if err != nil {
		return nil, nil, err
	}
	path := file.Name()
	cleanup := func() { _ = os.Remove(path) }
	if err := file.Chmod(0o600); err != nil {
		file.Close()
		cleanup()
		return nil, nil, err
	}
	if _, err := file.WriteString(token); err != nil {
		file.Close()
		cleanup()
		return nil, nil, err
	}
	if err := file.Close(); err != nil {
		cleanup()
		return nil, nil, err
	}
	return []string{managedLaunchFileEnv + "=" + path, managedLaunchTokenEnv + "=" + token}, cleanup, nil
}

func consumeManagedLaunchCapability() bool {
	path := strings.TrimSpace(os.Getenv(managedLaunchFileEnv))
	token := strings.TrimSpace(os.Getenv(managedLaunchTokenEnv))
	_ = os.Unsetenv(managedLaunchFileEnv)
	_ = os.Unsetenv(managedLaunchTokenEnv)
	if path == "" || token == "" {
		return false
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return false
	}
	_ = os.Remove(path)
	return subtle.ConstantTimeCompare(data, []byte(token)) == 1
}

func removeObserverStateForPID(path string, pid int) {
	state, err := readSharedObserverState(path)
	if err == nil && state.PID == pid {
		_ = os.Remove(path)
	}
}

type rollingLogWriter struct {
	sync.Mutex
	path     string
	maxBytes int64
}

func (writer *rollingLogWriter) Write(data []byte) (int, error) {
	writer.Lock()
	defer writer.Unlock()
	if info, err := os.Stat(writer.path); err == nil && info.Size()+int64(len(data)) > writer.maxBytes {
		backup := writer.path + ".1"
		if err := os.Remove(backup); err != nil && !errors.Is(err, os.ErrNotExist) {
			return 0, err
		}
		if err := os.Rename(writer.path, backup); err != nil {
			return 0, err
		}
	} else if err != nil && !errors.Is(err, os.ErrNotExist) {
		return 0, err
	}
	file, err := os.OpenFile(writer.path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		return 0, err
	}
	written, writeErr := file.Write(data)
	closeErr := file.Close()
	if writeErr != nil {
		return written, writeErr
	}
	return written, closeErr
}

func configureManagedLogging() {
	if path := strings.TrimSpace(os.Getenv(managedLogPathEnv)); path != "" {
		log.SetOutput(&rollingLogWriter{path: path, maxBytes: managedLogMaxBytes})
	}
}

func managedArgValue(args []string, flag string) string {
	for index := 0; index+1 < len(args); index += 2 {
		if args[index] == flag {
			return args[index+1]
		}
	}
	return ""
}

func managedRunArgs(config runConfig) ([]string, error) {
	args := []string{}
	if config.host != "" {
		args = append(args, "--host", config.host)
	}
	if config.observerHTTPPort != "" {
		args = append(args, "--observer-http-port", config.observerHTTPPort)
	}
	envFile := config.envFile
	if envFile == "" {
		envFile = strings.TrimSpace(os.Getenv("OBSTUDIO_ENV_FILE"))
	}
	if envFile != "" {
		absolute, err := filepath.Abs(envFile)
		if err != nil {
			return nil, fmt.Errorf("resolve env file: %w", err)
		}
		args = append(args, "--env-file", absolute)
	}
	return args, nil
}

func acquireManagedLifecycleLock() (func(), error) {
	path := filepath.Join(userHome(), sharedObserverStateDirName, managedLockDirName)
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return nil, err
	}
	file, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0o600)
	if err != nil {
		return nil, err
	}
	deadline := time.Now().Add(managedStartTimeout + managedStopTimeout + 5*time.Second)
	for {
		locked, lockErr := tryLockManagedFile(file)
		if lockErr != nil {
			file.Close()
			return nil, fmt.Errorf("lock managed Observer lifecycle: %w", lockErr)
		}
		if locked {
			return func() {
				_ = unlockManagedFile(file)
				_ = file.Close()
			}, nil
		}
		if time.Now().After(deadline) {
			file.Close()
			return nil, errors.New("another managed Observer lifecycle command is still running")
		}
		time.Sleep(managedLifecyclePollDelay)
	}
}

func mergeManagedArgs(saved, current []string) []string {
	values := map[string]string{}
	for _, args := range [][]string{saved, current} {
		for index := 0; index+1 < len(args); index += 2 {
			values[args[index]] = args[index+1]
		}
	}
	result := []string{}
	for _, flag := range []string{"--host", "--observer-http-port", "--env-file"} {
		if value := values[flag]; value != "" {
			result = append(result, flag, value)
		}
	}
	return result
}

func isLoopbackBindHost(host string) bool {
	host = strings.TrimSpace(host)
	if strings.ContainsAny(host, "[]") {
		return false
	}
	host = strings.TrimSuffix(strings.ToLower(host), ".")
	if host == "localhost" {
		return true
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

func stopManagedObserver(client *http.Client) error {
	health, state, err := managedObserverHealth(client)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			fmt.Println("Managed Observer is not running.")
			return nil
		}
		return fmt.Errorf("managed Observer health is unavailable; refusing to assume it stopped: %w", err)
	}
	if health.Owner != "cli" || health.Mode != managedObserverMode {
		return fmt.Errorf("refusing to stop Observer owned by %s in %s mode", health.Owner, health.Mode)
	}
	endpoint, err := lifecycleEndpoint(state.HealthURL, managedStopPath)
	if err != nil {
		return err
	}
	request, err := http.NewRequest(http.MethodPost, endpoint, bytes.NewReader([]byte("{}")))
	if err != nil {
		return err
	}
	request.Header.Set("Authorization", "Bearer "+state.ControlToken)
	if client == nil {
		client = http.DefaultClient
	}
	requestClient := *client
	requestClient.Timeout = sharedObserverHealthTimeout
	requestClient.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	response, err := requestClient.Do(request)
	if err != nil {
		return err
	}
	response.Body.Close()
	if response.StatusCode != http.StatusAccepted {
		return fmt.Errorf("managed Observer stop returned HTTP %d", response.StatusCode)
	}
	deadline := time.Now().Add(managedStopTimeout)
	for time.Now().Before(deadline) {
		if _, stateErr := os.Stat(managedControlStatePath()); errors.Is(stateErr, os.ErrNotExist) {
			fmt.Println("Managed Observer stopped.")
			return nil
		}
		time.Sleep(managedLifecyclePollDelay)
	}
	return errors.New("managed Observer did not stop before the deadline")
}

func stageManagedRuntime(executable string) (string, error) {
	return stageManagedRuntimeWithWeaver(executable, strings.TrimSpace(os.Getenv("WEAVER_PATH")))
}

func stageManagedRuntimeWithWeaver(executable, configuredWeaver string) (string, error) {
	weaverName := installedWeaverName(executable)
	weaverSource := filepath.Join(filepath.Dir(executable), weaverName)
	weaverPresent := false
	weaverCandidate := strings.TrimSpace(configuredWeaver)
	if weaverCandidate != "" {
		absolute, absoluteErr := filepath.Abs(weaverCandidate)
		if absoluteErr != nil {
			return "", absoluteErr
		}
		if info, statErr := os.Stat(absolute); statErr == nil && info.Mode().IsRegular() {
			weaverSource, weaverPresent = absolute, true
		} else if statErr != nil {
			return "", fmt.Errorf("resolve Weaver runtime: %w", statErr)
		} else {
			return "", fmt.Errorf("resolve Weaver runtime: %s is not a regular file", absolute)
		}
	} else {
		if info, err := os.Stat(weaverSource); err == nil && info.Mode().IsRegular() {
			weaverPresent = true
		} else if err != nil && !errors.Is(err, os.ErrNotExist) {
			return "", err
		} else if pathWeaver, lookErr := exec.LookPath("weaver"); lookErr == nil {
			absolute, absoluteErr := filepath.Abs(pathWeaver)
			if absoluteErr != nil {
				return "", absoluteErr
			}
			weaverSource, weaverPresent = absolute, true
		}
	}
	sourceInfo := map[string]os.FileInfo{}
	for _, source := range []string{executable, weaverSource} {
		if source == weaverSource && !weaverPresent {
			continue
		}
		info, err := os.Stat(source)
		if err != nil {
			return "", err
		}
		sourceInfo[source] = info
	}
	root := filepath.Join(userHome(), sharedObserverStateDirName, "runtime")
	if err := os.MkdirAll(root, 0o700); err != nil {
		return "", err
	}
	temporary, err := os.MkdirTemp(root, ".managed-runtime-*")
	if err != nil {
		return "", err
	}
	defer os.RemoveAll(temporary)
	temporaryExecutable := filepath.Join(temporary, filepath.Base(executable))
	if err := copyStableManagedFile(executable, temporaryExecutable); err != nil {
		return "", err
	}
	if err := os.Chmod(temporaryExecutable, 0o755); err != nil {
		return "", err
	}
	stagedFiles := []string{temporaryExecutable}
	if weaverPresent {
		temporaryWeaver := filepath.Join(temporary, weaverName)
		if err := copyStableManagedFile(weaverSource, temporaryWeaver); err != nil {
			return "", err
		}
		if err := os.Chmod(temporaryWeaver, 0o755); err != nil {
			return "", err
		}
		stagedFiles = append(stagedFiles, temporaryWeaver)
	}
	for source, before := range sourceInfo {
		after, err := os.Stat(source)
		if err != nil {
			return "", err
		}
		if before.Size() != after.Size() || !before.ModTime().Equal(after.ModTime()) {
			return "", fmt.Errorf("runtime bundle changed while it was being staged; retry")
		}
	}
	bundleDigest, err := managedBundleDigest(stagedFiles)
	if err != nil {
		return "", err
	}
	finalDir := filepath.Join(root, bundleDigest)
	finalExecutable := filepath.Join(finalDir, filepath.Base(executable))
	finalFiles := []string{finalExecutable}
	if weaverPresent {
		finalFiles = append(finalFiles, filepath.Join(finalDir, weaverName))
	}
	if existingDigest, digestErr := managedBundleDigest(finalFiles); digestErr == nil && existingDigest == bundleDigest {
		return finalExecutable, nil
	}
	if err := os.RemoveAll(finalDir); err != nil {
		return "", err
	}
	if err := os.Rename(temporary, finalDir); err != nil {
		if existingDigest, digestErr := managedBundleDigest(finalFiles); digestErr == nil && existingDigest == bundleDigest {
			return finalExecutable, nil
		}
		return "", err
	}
	return finalExecutable, nil
}

func managedEnvironmentValue(environment []string, wanted string) string {
	for _, entry := range environment {
		if key, value, ok := strings.Cut(entry, "="); ok && key == wanted {
			return value
		}
	}
	return ""
}

func fileExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.Mode().IsRegular()
}

func copyStableManagedFile(source, destination string) error {
	before, err := os.Stat(source)
	if err != nil {
		return err
	}
	if err := copyFile(source, destination); err != nil {
		return err
	}
	after, err := os.Stat(source)
	if err != nil {
		return err
	}
	if before.Size() != after.Size() || !before.ModTime().Equal(after.ModTime()) {
		return fmt.Errorf("runtime %s changed while it was being staged; retry", source)
	}
	return nil
}

func managedBundleDigest(paths []string) (string, error) {
	digest := sha256.New()
	for _, path := range paths {
		fileDigest := sha256.New()
		if err := hashManagedFile(fileDigest, path); err != nil {
			return "", err
		}
		if _, err := digest.Write(fileDigest.Sum(nil)); err != nil {
			return "", err
		}
	}
	return hex.EncodeToString(digest.Sum(nil)), nil
}

func hashManagedFile(destination io.Writer, path string) error {
	file, err := os.Open(path)
	if err != nil {
		return err
	}
	defer file.Close()
	_, err = io.Copy(destination, file)
	return err
}

func pruneManagedRuntimes(activeDir string) error {
	root := filepath.Dir(activeDir)
	entries, err := os.ReadDir(root)
	if err != nil {
		return err
	}
	type candidate struct {
		path     string
		modified time.Time
	}
	candidates := []candidate{}
	for _, entry := range entries {
		if !entry.IsDir() || entry.Name() == filepath.Base(activeDir) || len(entry.Name()) != sha256.Size*2 {
			continue
		}
		if _, err := hex.DecodeString(entry.Name()); err != nil {
			continue
		}
		info, err := entry.Info()
		if err != nil {
			continue
		}
		candidates = append(candidates, candidate{path: filepath.Join(root, entry.Name()), modified: info.ModTime()})
	}
	slices.SortFunc(candidates, func(left, right candidate) int { return right.modified.Compare(left.modified) })
	for _, candidate := range candidates[clampIndex(1, len(candidates)):] {
		if err := os.RemoveAll(candidate.path); err != nil {
			return err
		}
	}
	return nil
}

func clampIndex(want, length int) int {
	if want < length {
		return want
	}
	return length
}

func managedStatePath() string {
	return filepath.Join(userHome(), sharedObserverStateDirName, managedStateFileName)
}

func managedControlStatePath() string {
	return filepath.Join(userHome(), sharedObserverStateDirName, managedControlFileName)
}

type managedLaunch struct {
	Args             []string `json:"args"`
	Env              []string `json:"env,omitempty"`
	WorkingDirectory string   `json:"workingDirectory,omitempty"`
}

func writeManagedLaunch(state managedLaunch) error {
	if err := os.MkdirAll(filepath.Dir(managedStatePath()), 0o700); err != nil {
		return err
	}
	data, err := json.Marshal(state)
	if err != nil {
		return err
	}
	temporary, err := os.CreateTemp(filepath.Dir(managedStatePath()), ".managed-observer-*")
	if err != nil {
		return err
	}
	temporaryPath := temporary.Name()
	defer os.Remove(temporaryPath)
	if err := temporary.Chmod(0o600); err != nil {
		temporary.Close()
		return err
	}
	if _, err := temporary.Write(append(data, '\n')); err != nil {
		temporary.Close()
		return err
	}
	if err := temporary.Close(); err != nil {
		return err
	}
	return os.Rename(temporaryPath, managedStatePath())
}

func readManagedLaunch() (managedLaunch, error) {
	data, err := os.ReadFile(managedStatePath())
	if err != nil {
		return managedLaunch{}, err
	}
	var state managedLaunch
	if err := json.Unmarshal(data, &state); err != nil {
		return managedLaunch{}, err
	}
	return state, nil
}

func currentManagedEnvironment() []string {
	keys := []string{
		"HOST", "PORT", "OTLP_HOST", "OTLP_PORT", "OTLP_HTTP_PORT", "OTLP_GRPC_HOST", "OTLP_GRPC_PORT",
		"OBSTUDIO_WORKSPACE_ROOT", "OBSTUDIO_DASHBOARDS_PREVIEW", "OBSTUDIO_AUDIT_REPORT",
		"OBSTUDIO_SPLUNK_REALM", "SPLUNK_REALM", "SPLUNK_ACCESS_TOKEN",
		"OBSTUDIO_SPLUNK_METRICS_EXPORT", "SPLUNK_METRICS_EXPORT", "OBSTUDIO_SPLUNK_TRACES_EXPORT", "SPLUNK_TRACES_EXPORT",
		"OBSTUDIO_SPLUNK_METRICS_ENDPOINT", "OBSTUDIO_SPLUNK_TRACES_ENDPOINT",
		"OBSTUDIO_SPLUNK_METRICS_TIMEOUT", "OBSTUDIO_SPLUNK_TRACES_TIMEOUT", "OBSTUDIO_VALIDATOR_HEALTH_TIMEOUT",
		"WEAVER_PATH", "MAX_FLOW_NODE_SPAN_LIST_SIZE",
	}
	values := make([]string, 0, len(keys))
	for _, key := range keys {
		if value, ok := os.LookupEnv(key); ok {
			if key == "WEAVER_PATH" && value != "" && !filepath.IsAbs(value) {
				if absolute, err := filepath.Abs(value); err == nil {
					value = absolute
				}
			}
			values = append(values, key+"="+value)
		}
	}
	return values
}

func mergeManagedEnvironment(saved, current []string) []string {
	merged := make(map[string]string, len(saved)+len(current))
	for _, entry := range append(append([]string{}, saved...), current...) {
		if key, value, ok := strings.Cut(entry, "="); ok {
			merged[key] = value
		}
	}
	keys := make([]string, 0, len(merged))
	for key := range merged {
		keys = append(keys, key)
	}
	slices.Sort(keys)
	result := make([]string, 0, len(keys))
	for _, key := range keys {
		result = append(result, key+"="+merged[key])
	}
	return result
}

func resolveManagedRunConfig(config runConfig, overrides []string) runConfig {
	values := map[string]string{}
	for _, entry := range os.Environ() {
		if key, value, ok := strings.Cut(entry, "="); ok {
			values[key] = value
		}
	}
	for _, entry := range overrides {
		if key, value, ok := strings.Cut(entry, "="); ok {
			values[key] = value
		}
	}
	valueOr := func(value, key, fallback string) string {
		if value != "" {
			return value
		}
		if configured := values[key]; configured != "" {
			return configured
		}
		return fallback
	}
	host := valueOr(config.host, "HOST", "127.0.0.1")
	return runConfig{
		host:             host,
		observerHTTPPort: valueOr(config.observerHTTPPort, "PORT", "3000"),
		otlpHTTPPort:     valueOr(config.otlpHTTPPort, "OTLP_HTTP_PORT", valueOr("", "OTLP_PORT", "4318")),
		otlpGRPCHost:     valueOr(config.otlpGRPCHost, "OTLP_GRPC_HOST", host),
		otlpGRPCPort:     valueOr(config.otlpGRPCPort, "OTLP_GRPC_PORT", "4317"),
		envFile:          config.envFile,
	}
}

func managedObserverHealth(client *http.Client) (sharedObserverHealth, sharedObserverState, error) {
	state, err := readSharedObserverState(managedControlStatePath())
	if err != nil {
		return sharedObserverHealth{}, sharedObserverState{}, err
	}
	if client == nil {
		client = http.DefaultClient
	}
	requestClient := *client
	if requestClient.Timeout == 0 {
		requestClient.Timeout = sharedObserverHealthTimeout
	}
	response, err := requestClient.Get(state.HealthURL)
	if err != nil {
		return sharedObserverHealth{}, state, errors.New("Observer is not running")
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return sharedObserverHealth{}, state, errors.New("Observer is not running")
	}
	var health sharedObserverHealth
	if err := json.NewDecoder(response.Body).Decode(&health); err != nil || health.Kind != "obstudio" || health.APIVersion != "v1" {
		return sharedObserverHealth{}, state, errors.New("Observer health response is invalid")
	}
	return health, state, nil
}

func lifecycleEndpoint(healthURL, path string) (string, error) {
	parsed, err := url.Parse(healthURL)
	if err != nil || parsed.Scheme != "http" || parsed.User != nil {
		return "", errors.New("managed Observer requires a loopback HTTP endpoint")
	}
	host := strings.TrimSuffix(strings.ToLower(parsed.Hostname()), ".")
	ip := net.ParseIP(host)
	if host != "localhost" && (ip == nil || !ip.IsLoopback()) {
		return "", errors.New("managed Observer endpoint is not loopback")
	}
	parsed.Path, parsed.RawQuery, parsed.Fragment = path, "", ""
	return parsed.String(), nil
}

func registerManagedStop(mux *http.ServeMux, token string, stop chan<- struct{}) {
	mux.HandleFunc("POST "+managedStopPath, func(w http.ResponseWriter, r *http.Request) {
		if !loopbackRemote(r.RemoteAddr) || !validBearer(r.Header.Get("Authorization"), token) {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		select {
		case stop <- struct{}{}:
			w.WriteHeader(http.StatusAccepted)
		default:
			w.WriteHeader(http.StatusConflict)
		}
	})
}

func loopbackRemote(remote string) bool {
	host, _, err := net.SplitHostPort(remote)
	if err != nil {
		return false
	}
	ip := net.ParseIP(strings.Trim(host, "[]"))
	return ip != nil && ip.IsLoopback()
}
func validBearer(header, token string) bool {
	if token == "" {
		return false
	}
	provided := strings.TrimPrefix(header, "Bearer ")
	return strings.HasPrefix(header, "Bearer ") && len(provided) == len(token) && subtle.ConstantTimeCompare([]byte(provided), []byte(token)) == 1
}
