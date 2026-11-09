package credentials

import (
	"bufio"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

type memoryBackend struct {
	values          map[string]string
	unavailable     bool
	readUnavailable bool
	discard         bool
}

type refusingNativeBackend struct {
	*memoryBackend
	calls, refuseAt int
}

func (b *refusingNativeBackend) Set(key, value string) error {
	b.calls++
	if b.calls == b.refuseAt {
		return ErrWriteNotStarted
	}
	return b.memoryBackend.Set(key, value)
}

func TestNativeWriteRefusalDistinguishesUnwrittenAndPartialCredentials(t *testing.T) {
	for _, refuseAt := range []int{1, 2, 3} {
		t.Run(fmt.Sprint(refuseAt), func(t *testing.T) {
			backend := &refusingNativeBackend{memoryBackend: memory(), refuseAt: refuseAt}
			vault := NewWithBackend(nativeBackend{store: backend})
			var retained string
			_, err := vault.Put("profile", "cloud", "destination", strings.Repeat("x", 2048), func(ref string) error { retained = ref; return nil })
			if retained == "" || !errors.Is(err, ErrStorageRefused) || errors.Is(err, ErrWriteNotStarted) != (refuseAt == 1) || len(backend.values) != refuseAt-1 {
				t.Fatal("incorrect native write outcome", err, len(backend.values))
			}
			if err := vault.Delete("profile", "cloud", "destination", retained); err != nil || len(backend.values) != 0 {
				t.Fatal("partial credential could not be removed", err)
			}
		})
	}
}

func (b *memoryBackend) Get(key string) (string, error) {
	if b.unavailable || b.readUnavailable {
		return "", errors.New("provider secret must stay private")
	}
	value, ok := b.values[key]
	if !ok {
		return "", ErrNotFound
	}
	return value, nil
}
func (b *memoryBackend) Set(key, value string) error {
	if b.unavailable {
		return errors.New("provider secret must stay private")
	}
	if !b.discard {
		b.values[key] = value
	}
	return nil
}
func (b *memoryBackend) Delete(key string) error {
	if b.unavailable {
		return errors.New("provider secret must stay private")
	}
	if _, exists := b.values[key]; !exists {
		return ErrNotFound
	}
	delete(b.values, key)
	return nil
}
func retainForTest(string) error { return nil }

func memory() *memoryBackend { return &memoryBackend{values: map[string]string{}} }

type delayedWriteBackend struct {
	*memoryBackend
	release  chan struct{}
	writeErr error
}

func (b *delayedWriteBackend) Set(key, value string) error {
	<-b.release
	if b.writeErr != nil {
		return b.writeErr
	}
	return b.memoryBackend.Set(key, value)
}

type concurrentBackend struct {
	started chan struct{}
	release chan struct{}
}

func (b *concurrentBackend) Set(string, string) error {
	close(b.started)
	<-b.release
	return nil
}
func (*concurrentBackend) Get(string) (string, error) { return "saved-value", nil }
func (*concurrentBackend) Delete(string) error        { return nil }

func TestConcurrentCredentialOperationsWaitForHealthyStore(t *testing.T) {
	for _, shared := range []bool{false, true} {
		t.Run(map[bool]string{false: "same process", true: "shared file lock"}[shared], func(t *testing.T) {
			backend := &concurrentBackend{started: make(chan struct{}), release: make(chan struct{})}
			defer close(backend.release)
			first := &boundedBackend{backend: backend, timeout: time.Second}
			second := first
			if shared {
				first.lockPath = filepath.Join(t.TempDir(), "credential.lock")
				second = &boundedBackend{backend: backend, timeout: time.Second, lockPath: first.lockPath}
			}
			written := make(chan error, 1)
			go func() { written <- first.Set("new-account", "new-value") }()
			select {
			case <-backend.started:
			case err := <-written:
				t.Fatal("credential write failed before reaching the backend", err)
			case <-time.After(2 * time.Second):
				t.Fatal("credential write did not reach the backend")
			}
			read := make(chan backendResult, 1)
			go func() { value, err := second.Get("saved-account"); read <- backendResult{value, err} }()
			select {
			case result := <-read:
				t.Fatal("a healthy concurrent operation failed instead of waiting", result.err)
			case <-time.After(20 * time.Millisecond):
			}
			backend.release <- struct{}{}
			select {
			case err := <-written:
				if err != nil {
					t.Fatal(err)
				}
			case <-time.After(2 * time.Second):
				t.Fatal("credential write did not finish after release")
			}
			select {
			case result := <-read:
				if result.err != nil || result.value != "saved-value" {
					t.Fatal("credential read did not recover after the healthy write", result.err)
				}
			case <-time.After(2 * time.Second):
				t.Fatal("credential read remained blocked after the write")
			}
		})
	}
}

func TestStoreTimeoutRetainsCleanupUntilWriteCompletes(t *testing.T) {
	backend := &delayedWriteBackend{memoryBackend: memory(), release: make(chan struct{})}
	guard := &boundedBackend{backend: backend, timeout: 20 * time.Millisecond}
	store := NewWithBackend(guard)
	var retained string
	if _, err := store.Put("profile", "cloud", "destination", "token", func(ref string) error {
		retained = ref
		return nil
	}); !errors.Is(err, ErrUnavailable) || retained == "" {
		t.Fatal("timed-out save lost its cleanup reference", err)
	}
	if err := store.Delete("profile", "cloud", "destination", retained); !errors.Is(err, ErrUnavailable) {
		t.Fatal("cleanup claimed success while a write could still complete", err)
	}
	close(backend.release)
	guard.mu.Lock()
	guard.mu.Unlock()
	if err := store.Delete("profile", "cloud", "destination", retained); err != nil {
		t.Fatal("cleanup could not retry after completion", err)
	}
	if len(backend.values) != 0 {
		t.Fatal("late write escaped cleanup")
	}
}

func TestStoreTimedOutRejectedWriteCanCompleteCleanup(t *testing.T) {
	backend := &delayedWriteBackend{memoryBackend: memory(), release: make(chan struct{})}
	backend.unavailable = true
	released := false
	defer func() {
		if !released {
			close(backend.release)
		}
	}()
	guard := &boundedBackend{backend: backend, timeout: 20 * time.Millisecond}
	store := NewWithBackend(guard)
	var ref string
	if _, err := store.Put("profile", "cloud", "destination", "token", func(value string) error { ref = value; return nil }); !errors.Is(err, ErrWritePending) {
		t.Fatal("write did not remain pending while the provider was blocked", err)
	}
	if err := store.DeleteUnconfirmed("profile", "cloud", "destination", ref, func() error { t.Fatal("creation was confirmed before its result"); return nil }); !errors.Is(err, ErrUnavailable) {
		t.Fatal("blocked write was discarded", err)
	}
	close(backend.release)
	released = true
	finished := make(chan struct{})
	go func() { guard.mu.Lock(); guard.mu.Unlock(); close(finished) }()
	select {
	case <-finished:
	case <-time.After(time.Second):
		t.Fatal("rejected write did not finish")
	}
	backend.unavailable = false
	confirmed := false
	if err := store.DeleteUnconfirmed("profile", "cloud", "destination", ref, func() error { confirmed = true; return nil }); err != nil || !confirmed {
		t.Fatal("a definite late rejection could not finish cleanup", err)
	}
}

type processWriteBackend struct {
	path string
	wait bool
}

func (b processWriteBackend) Get(string) (string, error) {
	data, err := os.ReadFile(b.path)
	if errors.Is(err, os.ErrNotExist) {
		return "", ErrNotFound
	}
	return string(data), err
}
func (b processWriteBackend) Set(_ string, value string) error {
	if b.wait {
		var signal [1]byte
		if _, err := os.Stdin.Read(signal[:]); err != nil {
			return err
		}
	}
	return os.WriteFile(b.path, []byte(value), 0o600)
}
func (b processWriteBackend) Delete(string) error {
	if err := os.Remove(b.path); !errors.Is(err, os.ErrNotExist) {
		return err
	}
	return ErrNotFound
}

func TestCredentialWriteProcess(t *testing.T) {
	path := os.Getenv("OBSTUDIO_TEST_CREDENTIAL_WRITE")
	if path == "" {
		return
	}
	guard := &boundedBackend{backend: processWriteBackend{path: path, wait: true}, timeout: 20 * time.Millisecond, lockPath: path + ".lock"}
	store := NewWithBackend(guard)
	var reference string
	_, err := store.Put("profile", "cloud", "destination", "synthetic-token", func(ref string) error { reference = ref; return nil })
	if !errors.Is(err, ErrUnavailable) {
		t.Fatal("save did not time out", err)
	}
	if _, err := os.Stdout.WriteString(reference + "\n"); err != nil {
		t.Fatal(err)
	}
	guard.mu.Lock()
	guard.mu.Unlock()
}

func TestStoreTimeoutProtectsCleanupAcrossProcesses(t *testing.T) {
	path := filepath.Join(t.TempDir(), "native-value")
	child := exec.Command(os.Args[0], "-test.run=^TestCredentialWriteProcess$", "-test.timeout=5s")
	child.Env = append(os.Environ(), "OBSTUDIO_TEST_CREDENTIAL_WRITE="+path)
	stdin, err := child.StdinPipe()
	if err != nil {
		t.Fatal(err)
	}
	stdout, err := child.StdoutPipe()
	if err != nil {
		t.Fatal(err)
	}
	if err := child.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = stdin.Close(); _ = child.Process.Kill() })
	reader := bufio.NewReader(stdout)
	line, err := reader.ReadString('\n')
	if err != nil {
		t.Fatal(err)
	}
	ref := strings.TrimSpace(line)
	other := NewWithBackend(&boundedBackend{backend: processWriteBackend{path: path}, timeout: time.Second, lockPath: path + ".lock"})
	if err := other.Delete("profile", "cloud", "destination", ref); !errors.Is(err, ErrUnavailable) {
		t.Fatal("another collector discarded cleanup while the native write was outstanding", err)
	}
	if _, err := stdin.Write([]byte{1}); err != nil {
		t.Fatal(err)
	}
	if err := child.Wait(); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(path); err != nil {
		t.Fatal("late native write did not finish", err)
	}
	if err := other.Delete("profile", "cloud", "destination", ref); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(path); !errors.Is(err, os.ErrNotExist) {
		t.Fatal("late native credential escaped cleanup", err)
	}
}

func TestStoreSavesBothDestinationsAndBindsReferences(t *testing.T) {
	store := NewWithBackend(memory())
	for _, kind := range []string{"cloud", "logs"} {
		ref, err := store.Put("profile", kind, "destination", "test-token", retainForTest)
		if err != nil {
			t.Fatal(err)
		}
		value, err := store.Get("profile", kind, "destination", ref)
		if err != nil || value != "test-token" {
			t.Fatal("credential did not round-trip")
		}
		for _, binding := range [][3]string{{"other-profile", kind, "destination"}, {"profile", kind, "other-destination"}, {"profile", "other-kind", "destination"}} {
			if _, err := store.Get(binding[0], binding[1], binding[2], ref); !errors.Is(err, ErrNotFound) {
				t.Fatal("credential crossed its binding")
			}
		}
		store.Delete("profile", kind, "destination", ref)
		if _, err := store.Get("profile", kind, "destination", ref); !errors.Is(err, ErrNotFound) {
			t.Fatal("credential was not deleted")
		}
	}
}

func TestStoreRequiresDurableReadbackAndKeepsRevisionsIndependent(t *testing.T) {
	native := memory()
	store := NewWithBackend(native)
	previous, err := store.Put("profile", "logs", "endpoint", "first-token", retainForTest)
	if err != nil {
		t.Fatal(err)
	}
	current, err := store.Put("profile", "logs", "endpoint", "second-token", retainForTest)
	if err != nil || current == previous {
		t.Fatal("new save did not create a revision")
	}
	if value, err := store.Get("profile", "logs", "endpoint", previous); err != nil || value != "first-token" {
		t.Fatal("new save replaced previous revision")
	}
	native.discard = true
	if _, err := store.Put("profile", "logs", "endpoint", "secret", retainForTest); !errors.Is(err, ErrUnavailable) {
		t.Fatal("save without readback was accepted")
	}
}

func TestStoreRetainsReferenceBeforeProviderWrite(t *testing.T) {
	backend := memory()
	store := NewWithBackend(backend)
	retained := ""
	ref, err := store.Put("profile", "logs", "endpoint", "token", func(ref string) error {
		if len(backend.values) != 0 {
			t.Fatal("provider write preceded durable reference")
		}
		retained = ref
		return nil
	})
	if err != nil || ref != retained || retained == "" {
		t.Fatal("saved reference was not retained")
	}
	if _, err := store.Put("profile", "logs", "endpoint", "replacement", func(string) error {
		return errors.New("journal unavailable")
	}); !errors.Is(err, ErrUnavailable) {
		t.Fatal("save accepted without retained reference")
	}
	if len(backend.values) != 1 {
		t.Fatal("failed retention reached provider")
	}
}

func TestStoreReportsUnavailableProviders(t *testing.T) {
	for _, backend := range []Backend{nil, &memoryBackend{unavailable: true}} {
		store := NewWithBackend(backend)
		if _, err := store.Put("profile", "logs", "destination", "test-token", retainForTest); !errors.Is(err, ErrUnavailable) {
			t.Fatalf("unavailable provider returned %v", err)
		}
		ref := strings.Repeat("a", 43)
		if _, err := store.Get("profile", "logs", "destination", ref); err != ErrUnavailable {
			t.Fatalf("unavailable provider read returned %v", err)
		}
		if err := store.Delete("profile", "logs", "destination", ref); err != ErrUnavailable {
			t.Fatalf("unavailable provider deletion returned %v", err)
		}
	}
}

func TestStoreValidatesCredentialValuesAndReferences(t *testing.T) {
	backend := memory()
	store := NewWithBackend(backend)
	for _, value := range []string{"", strings.Repeat("x", 4097)} {
		if _, err := store.Put("profile", "cloud", "destination", value, retainForTest); err != ErrUnavailable {
			t.Fatalf("invalid credential returned %v", err)
		}
	}
	if len(backend.values) != 0 {
		t.Fatal("invalid credential reached storage")
	}
	if _, err := store.Get("profile", "logs", "destination", "invalid reference"); err != ErrNotFound {
		t.Fatalf("invalid reference returned %v", err)
	}
	store.Delete("profile", "logs", "destination", "invalid reference")
}

func TestNativeBackendSupportsMaximumTokenAndIntegrity(t *testing.T) {
	backend := memory()
	native := nativeBackend{store: backend}
	value := strings.Repeat("x", 4096)
	if err := native.Set("test-account", value); err != nil {
		t.Fatal(err)
	}
	if got, err := native.Get("test-account"); err != nil || got != value {
		t.Fatal("maximum-size credential did not reload")
	}
	if err := backend.Set("test-account.1", "corrupted"); err != nil {
		t.Fatal(err)
	}
	if _, err := native.Get("test-account"); !errors.Is(err, ErrUnavailable) {
		t.Fatal("corrupt credential accepted")
	}
	if err := native.Delete("test-account"); err != nil {
		t.Fatal(err)
	}
	if _, err := native.Get("test-account"); !errors.Is(err, ErrNotFound) {
		t.Fatal("credential not removed")
	}
}

// Opt in explicitly so ordinary tests never prompt for a workstation keychain.
func TestSystemCredentialStoreRoundTrip(t *testing.T) {
	if os.Getenv("OBSTUDIO_TEST_SYSTEM_KEYRING") != "1" {
		t.Skip("requires an unlocked OS credential store")
	}
	profile := t.TempDir()
	for _, kind := range []string{"cloud", "logs"} {
		for _, value := range []struct{ name, token string }{
			{"short", "synthetic-keychain-test"},
			{"maximum ASCII", strings.Repeat("x", 4096)},
			{"maximum UTF-8", "p" + strings.Repeat("界", 1365)},
		} {
			t.Run(kind+"/"+value.name, func(t *testing.T) {
				store := New()
				ref, err := store.Put(profile, kind, "https://test.invalid", value.token, retainForTest)
				if err != nil {
					t.Fatal(err)
				}
				t.Cleanup(func() {
					if err := store.Delete(profile, kind, "https://test.invalid", ref); err != nil {
						t.Error("could not clean up native test credential", err)
					}
				})
				reloaded := New()
				if got, err := reloaded.Get(profile, kind, "https://test.invalid", ref); err != nil || got != value.token {
					t.Fatal("OS credential did not reload", err)
				}
				if err := reloaded.Delete(profile, kind, "https://test.invalid", ref); err != nil {
					t.Fatal("OS credential deletion failed", err)
				}
				if _, err := New().Get(profile, kind, "https://test.invalid", ref); !errors.Is(err, ErrNotFound) {
					t.Fatal("deleted OS credential remains available", err)
				}
			})
		}
	}
}

func TestUnconfirmedCredentialCleanupWaitsForCompleteWrite(t *testing.T) {
	backend := memory()
	store := NewWithBackend(nativeBackend{store: backend})
	ref := strings.Repeat("a", 43)
	if err := store.DeleteUnconfirmed("profile", "cloud", "destination", ref, func() error { return nil }); !errors.Is(err, ErrUnavailable) {
		t.Fatal("absence discarded an unacknowledged write", err)
	}
	backend.values[account("profile", "cloud", "destination", ref)+".0"] = "late token chunk"
	if err := store.DeleteUnconfirmed("profile", "cloud", "destination", ref, func() error { return nil }); !errors.Is(err, ErrUnavailable) || len(backend.values) != 1 {
		t.Fatal("cleanup removed a chunk before creation completed", err)
	}
	native := nativeBackend{store: backend}
	key := account("profile", "cloud", "destination", ref)
	if err := native.Set(key, strings.Repeat("x", 4096)); err != nil {
		t.Fatal(err)
	}
	manifest := backend.values[key]
	delete(backend.values, key)
	if err := store.DeleteUnconfirmed("profile", "cloud", "destination", ref, func() error { t.Fatal("incomplete creation was confirmed"); return nil }); !errors.Is(err, ErrUnavailable) || len(backend.values) != 3 {
		t.Fatal("cleanup removed completed chunks before manifest publication", err)
	}
	backend.values[key] = manifest
	if err := store.DeleteUnconfirmed("profile", "cloud", "destination", ref, func() error { return errors.New("journal unavailable") }); !errors.Is(err, ErrUnavailable) {
		t.Fatal("cleanup skipped durable confirmation", err)
	}
	if _, err := store.Get("profile", "cloud", "destination", ref); err != nil {
		t.Fatal("confirmation failure removed the complete credential", err)
	}
	confirmed := false
	if err := store.DeleteUnconfirmed("profile", "cloud", "destination", ref, func() error { confirmed = true; return nil }); err != nil || !confirmed || len(backend.values) != 0 {
		t.Fatal("complete credential could not finish cleanup", err)
	}
	if err := store.Delete("profile", "cloud", "destination", ref); err != nil {
		t.Fatal("confirmed cleanup must stay idempotent", err)
	}
}

func TestStoreFailedReadbackKeepsTheJournaledCredential(t *testing.T) {
	backend := memory()
	backend.readUnavailable = true
	store := NewWithBackend(backend)
	reference := ""
	if _, err := store.Put("profile", "cloud", "destination", "synthetic-token", func(ref string) error { reference = ref; return nil }); !errors.Is(err, ErrUnavailable) {
		t.Fatal(err)
	}
	if reference == "" || len(backend.values) != 1 {
		t.Fatal("failed readback deleted a credential before caller confirmation")
	}
	backend.readUnavailable = false
	if _, err := store.Get("profile", "cloud", "destination", reference); err != nil {
		t.Fatal("failed save lost its complete credential", err)
	}
	if err := store.Delete("profile", "cloud", "destination", reference); err != nil {
		t.Fatal(err)
	}
}

func TestUnconfirmedCredentialSurvivesUnavailableRead(t *testing.T) {
	backend := memory()
	store := NewWithBackend(nativeBackend{store: backend})
	ref, err := store.Put("profile", "cloud", "destination", "synthetic-token", retainForTest)
	if err != nil {
		t.Fatal(err)
	}
	backend.readUnavailable = true
	if err := store.DeleteUnconfirmed("profile", "cloud", "destination", ref, func() error { t.Fatal("unavailable read confirmed creation"); return nil }); !errors.Is(err, ErrUnavailable) {
		t.Fatal(err)
	}
	backend.readUnavailable = false
	if _, err := store.Get("profile", "cloud", "destination", ref); err != nil {
		t.Fatal("transient read error destroyed the complete credential", err)
	}
	if err := store.DeleteUnconfirmed("profile", "cloud", "destination", ref, func() error { return nil }); err != nil {
		t.Fatal(err)
	}
}

func TestStoreClassifiesOnlyDefiniteProviderRefusal(t *testing.T) {
	for _, scenario := range []string{"provider refusal", "pending write", "lock timeout", "journal failure", "readback mismatch"} {
		t.Run(scenario, func(t *testing.T) {
			backend := memory()
			guard := &boundedBackend{backend: backend, timeout: 20 * time.Millisecond}
			retain := retainForTest
			switch scenario {
			case "provider refusal":
				backend.unavailable = true
			case "pending write":
				pending := &delayedWriteBackend{memoryBackend: backend, release: make(chan struct{})}
				guard.backend = pending
				defer close(pending.release)
			case "lock timeout":
				guard.mu.Lock()
				defer guard.mu.Unlock()
			case "journal failure":
				retain = func(string) error { return errors.New("journal is not writable") }
			case "readback mismatch":
				backend.discard = true
			}
			_, err := NewWithBackend(guard).Put("profile", "cloud", "destination", "synthetic-token", retain)
			if !errors.Is(err, ErrUnavailable) || errors.Is(err, ErrStorageRefused) != (scenario == "provider refusal") {
				t.Fatalf("incorrect session-fallback classification: %v", err)
			}
		})
	}
}

func TestLateUnsubmittedCredentialWriteDoesNotRequireNativeCleanup(t *testing.T) {
	backend := &delayedWriteBackend{memoryBackend: memory(), release: make(chan struct{}), writeErr: ErrWriteNotStarted}
	released := false
	defer func() {
		if !released {
			close(backend.release)
		}
	}()
	guard := &boundedBackend{backend: backend, timeout: 20 * time.Millisecond}
	vault := NewWithBackend(guard)
	var ref string
	_, err := vault.Put("profile", "cloud", "us1", "synthetic-token", func(value string) error { ref = value; return nil })
	if !errors.Is(err, ErrWritePending) {
		t.Fatal(err)
	}
	confirmed := false
	confirm := func() error { confirmed = true; return nil }
	if err := vault.DeleteUnconfirmed("profile", "cloud", "us1", ref, confirm); err == nil || confirmed {
		t.Fatal("an unfinished provider operation was retired")
	}
	close(backend.release)
	released = true
	guard.mu.Lock()
	guard.mu.Unlock()
	backend.unavailable = true
	if err := vault.DeleteUnconfirmed("profile", "cloud", "us1", ref, confirm); err != nil || !confirmed {
		t.Fatal("an unsubmitted write required unavailable native cleanup", err)
	}
}
