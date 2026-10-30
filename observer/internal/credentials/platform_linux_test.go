//go:build linux

package credentials

import (
	"bufio"
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/godbus/dbus/v5"
	ss "github.com/zalando/go-keyring/secret_service"
)

type unavailableSecretService struct {
	block   <-chan struct{}
	prompts atomic.Int32
}

func (s *unavailableSecretService) Get(iface, property string) (dbus.Variant, *dbus.Error) {
	if s.block != nil {
		<-s.block
	}
	if iface == secretServiceInterface && property == "Collections" {
		return dbus.MakeVariant([]dbus.ObjectPath{"/org/freedesktop/secrets/collection/login"}), nil
	}
	return dbus.MakeVariant(true), nil
}

func (s *unavailableSecretService) Unlock(paths []dbus.ObjectPath) ([]dbus.ObjectPath, dbus.ObjectPath, *dbus.Error) {
	s.prompts.Add(1)
	return nil, "/", nil
}

func TestLinuxCredentialProviderDoesNotPromptOrWaitIndefinitely(t *testing.T) {
	for _, blocked := range []bool{false, true} {
		name := "locked"
		if blocked {
			name = "unresponsive"
		}
		t.Run(name, func(t *testing.T) {
			provider := &unavailableSecretService{}
			if blocked {
				release := make(chan struct{})
				provider.block = release
				defer close(release)
			}
			startTestSecretService(t, provider)
			started := time.Now()
			_, err := (platformBackend{}).Get("synthetic-account")
			if !errors.Is(err, ErrUnavailable) || time.Since(started) > 2*credentialOperationTimeout {
				t.Fatal("unavailable provider did not return within the deadline", err)
			}
			if provider.prompts.Load() != 0 {
				t.Fatal("credential access tried to unlock the desktop")
			}
		})
	}
}

func startTestSecretService(t *testing.T, provider any) *dbus.Conn {
	t.Helper()
	binary, err := exec.LookPath("dbus-daemon")
	if err != nil {
		t.Skip("dbus-daemon is required for the isolated Secret Service test")
	}
	ctx, cancel := context.WithTimeout(t.Context(), 20*time.Second)
	t.Cleanup(cancel)
	daemon := exec.CommandContext(ctx, binary, "--session", "--nofork", "--print-address=1")
	stdout, err := daemon.StdoutPipe()
	if err != nil {
		t.Fatal(err)
	}
	if err := daemon.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = daemon.Process.Kill(); _ = daemon.Wait() })
	scanner := bufio.NewScanner(stdout)
	if !scanner.Scan() {
		t.Fatal("private D-Bus daemon did not provide its address")
	}
	address := scanner.Text()
	t.Setenv("DBUS_SESSION_BUS_ADDRESS", address)
	conn, err := dbus.Connect(address)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	for _, entry := range []struct {
		path  dbus.ObjectPath
		iface string
	}{
		{secretServicePath, "org.freedesktop.DBus.Properties"},
		{"/org/freedesktop/secrets/collection/login", "org.freedesktop.DBus.Properties"},
		{secretServicePath, secretServiceInterface},
		{"/org/freedesktop/secrets/collection/login", secretCollectionInterface},
		{"/org/freedesktop/secrets/session/test", "org.freedesktop.Secret.Session"},
	} {
		if err := conn.Export(provider, entry.path, entry.iface); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := conn.RequestName(secretServiceName, dbus.NameFlagDoNotQueue); err != nil {
		t.Fatal(err)
	}
	return conn
}

type delayedSecretService struct {
	started chan struct{}
	release chan struct{}
}

func (s *delayedSecretService) Get(iface, property string) (dbus.Variant, *dbus.Error) {
	if property == "Collections" {
		return dbus.MakeVariant([]dbus.ObjectPath{"/org/freedesktop/secrets/collection/login"}), nil
	}
	return dbus.MakeVariant(false), nil
}
func (s *delayedSecretService) OpenSession(string, dbus.Variant) (dbus.Variant, dbus.ObjectPath, *dbus.Error) {
	return dbus.MakeVariant(""), "/org/freedesktop/secrets/session/test", nil
}
func (s *delayedSecretService) Close() *dbus.Error { return nil }
func (s *delayedSecretService) CreateItem(map[string]dbus.Variant, ss.Secret, bool) (dbus.ObjectPath, dbus.ObjectPath, *dbus.Error) {
	close(s.started)
	<-s.release
	return "/org/freedesktop/secrets/collection/login/item", "/", nil
}

func TestLinuxDelayedWriteRetainsOwnershipUntilProviderReply(t *testing.T) {
	provider := &delayedSecretService{started: make(chan struct{}), release: make(chan struct{})}
	startTestSecretService(t, provider)
	released := false
	defer func() {
		if !released {
			close(provider.release)
		}
	}()
	lockPath := filepath.Join(t.TempDir(), "native.lock")
	guard := &boundedBackend{backend: platformBackend{}, timeout: 20 * time.Millisecond, lockPath: lockPath}
	if err := guard.Set("synthetic-account", "synthetic-value"); !errors.Is(err, ErrUnavailable) {
		t.Fatal(err)
	}
	select {
	case <-provider.started:
	case <-time.After(time.Second):
		t.Fatal("test did not reach CreateItem")
	}
	finished := make(chan struct{})
	go func() { guard.mu.Lock(); guard.mu.Unlock(); close(finished) }()
	select {
	case <-finished:
		t.Fatal("write ownership ended before the provider replied")
	case <-time.After(credentialOperationTimeout + 250*time.Millisecond):
	}
	if release, err := tryCredentialOperationLock(lockPath); err == nil {
		release()
		t.Fatal("another collector could discard cleanup while CreateItem was pending")
	}
	// Keep ownership until the provider confirms its outstanding write.
	close(provider.release)
	released = true
	select {
	case <-finished:
	case <-time.After(time.Second):
		t.Fatal("write did not release ownership after the reply")
	}
	release, err := tryCredentialOperationLock(lockPath)
	if err != nil {
		t.Fatal("completed write retained its operation lock", err)
	}
	release()
}

type interruptedSecretService struct {
	delayedSecretService
	mu            sync.Mutex
	values        map[string]string
	replyError    bool
	blockedSuffix string
	completed     chan struct{}
}

func interruptedItemPath(key string) dbus.ObjectPath {
	for _, suffix := range []string{"0", "1", "2"} {
		if strings.HasSuffix(key, "."+suffix) {
			return dbus.ObjectPath("/org/freedesktop/secrets/collection/login/item" + suffix)
		}
	}
	return "/org/freedesktop/secrets/collection/login/manifest"
}
func (s *interruptedSecretService) CreateItem(properties map[string]dbus.Variant, secret ss.Secret, _ bool) (dbus.ObjectPath, dbus.ObjectPath, *dbus.Error) {
	key := properties[secretItemInterface+".Attributes"].Value().(map[string]string)["username"]
	blocked := strings.HasSuffix(key, s.blockedSuffix)
	if blocked {
		close(s.started)
		<-s.release
	}
	s.mu.Lock()
	s.values[key] = string(secret.Value)
	s.mu.Unlock()
	if blocked {
		close(s.completed)
	}
	if s.replyError {
		return "/", "/", dbus.NewError("org.freedesktop.DBus.Error.NoReply", nil)
	}
	return interruptedItemPath(key), "/", nil
}
func (s *interruptedSecretService) SearchItems(attributes map[string]string) ([]dbus.ObjectPath, *dbus.Error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	key := attributes["username"]
	if _, ok := s.values[key]; ok {
		return []dbus.ObjectPath{interruptedItemPath(key)}, nil
	}
	return nil, nil
}

type interruptedSecretItem struct {
	provider *interruptedSecretService
	path     dbus.ObjectPath
}

func (i *interruptedSecretItem) Delete() (dbus.ObjectPath, *dbus.Error) {
	i.provider.mu.Lock()
	defer i.provider.mu.Unlock()
	for key := range i.provider.values {
		if interruptedItemPath(key) == i.path {
			delete(i.provider.values, key)
		}
	}
	return "/", nil
}
func (i *interruptedSecretItem) GetSecret(session dbus.ObjectPath) (ss.Secret, *dbus.Error) {
	i.provider.mu.Lock()
	defer i.provider.mu.Unlock()
	for key, value := range i.provider.values {
		if interruptedItemPath(key) == i.path {
			return ss.NewSecret(session, value), nil
		}
	}
	return ss.Secret{}, nil
}

func TestLinuxKilledCredentialWriter(t *testing.T) {
	if os.Getenv("OBSTUDIO_TEST_KILLED_SECRET_WRITE") != "1" {
		return
	}
	profile := os.Getenv("HOME")
	_, _ = New().Put(profile, "cloud", "destination", strings.Repeat("x", 4096), func(ref string) error { return os.WriteFile(filepath.Join(profile, "reference"), []byte(ref), 0o600) })
	t.Fatal("writer returned before termination")
}

func TestLinuxKilledWriterRetainsCleanupUntilLateProviderWrite(t *testing.T) {
	for _, suffix := range []string{".0", ".1"} {
		t.Run(suffix, func(t *testing.T) {
			provider := &interruptedSecretService{delayedSecretService: delayedSecretService{started: make(chan struct{}), release: make(chan struct{})}, values: map[string]string{}, blockedSuffix: suffix, completed: make(chan struct{})}
			conn := startTestSecretService(t, provider)
			for _, name := range []string{"item0", "item1", "item2", "manifest"} {
				path := dbus.ObjectPath("/org/freedesktop/secrets/collection/login/" + name)
				if err := conn.Export(&interruptedSecretItem{provider: provider, path: path}, path, secretItemInterface); err != nil {
					t.Fatal(err)
				}
			}
			profile := t.TempDir()
			t.Setenv("HOME", profile)
			binary, err := os.Executable()
			if err != nil {
				t.Fatal(err)
			}
			writer := exec.Command(binary, "-test.run=^TestLinuxKilledCredentialWriter$", "-test.timeout=15s")
			writer.Env = append(os.Environ(), "OBSTUDIO_TEST_KILLED_SECRET_WRITE=1")
			if err := writer.Start(); err != nil {
				t.Fatal(err)
			}
			exited, released := false, false
			defer func() {
				if !exited {
					_ = writer.Process.Kill()
					_ = writer.Wait()
				}
				if !released {
					close(provider.release)
				}
			}()
			select {
			case <-provider.started:
			case <-time.After(3 * time.Second):
				t.Fatal("writer did not reach the separate provider")
			}
			if err := writer.Process.Kill(); err != nil {
				t.Fatal(err)
			}
			_ = writer.Wait()
			exited = true
			data, err := os.ReadFile(filepath.Join(profile, "reference"))
			if err != nil {
				t.Fatal(err)
			}
			ref := string(data)
			store := New()
			if err := store.DeleteUnconfirmed(profile, "cloud", "destination", ref, func() error { return nil }); !errors.Is(err, ErrUnavailable) {
				t.Fatal("partial cleanup discarded a pending provider write after writer exit", err)
			}
			close(provider.release)
			released = true
			select {
			case <-provider.completed:
			case <-time.After(time.Second):
				t.Fatal("provider did not finish its late write")
			}
			if err := store.DeleteUnconfirmed(profile, "cloud", "destination", ref, func() error { return nil }); !errors.Is(err, ErrUnavailable) {
				t.Fatal("partial credential proved completion without its manifest", err)
			}
			provider.mu.Lock()
			remaining := len(provider.values)
			provider.mu.Unlock()
			retained, err := os.ReadFile(filepath.Join(profile, "reference"))
			if remaining != 0 || err != nil || string(retained) != ref {
				t.Fatal("late chunks must be removed while retaining the uncertain reference", err)
			}
		})
	}
}

func TestLinuxWriteReplyFailureRetainsUnconfirmedCreation(t *testing.T) {
	provider := &interruptedSecretService{delayedSecretService: delayedSecretService{started: make(chan struct{}), release: make(chan struct{})}, values: map[string]string{}, blockedSuffix: ".0", replyError: true, completed: make(chan struct{})}
	close(provider.release)
	conn := startTestSecretService(t, provider)
	path := dbus.ObjectPath("/org/freedesktop/secrets/collection/login/item0")
	if err := conn.Export(&interruptedSecretItem{provider: provider, path: path}, path, secretItemInterface); err != nil {
		t.Fatal(err)
	}
	profile := t.TempDir()
	t.Setenv("HOME", profile)
	retained := ""
	store := New()
	_, err := store.Put(profile, "cloud", "destination", "synthetic-token", func(ref string) error { retained = ref; return nil })
	if !errors.Is(err, ErrWritePending) || retained == "" {
		t.Fatal("missing creation acknowledgement was treated as completion", err)
	}
	if err := store.DeleteUnconfirmed(profile, "cloud", "destination", retained, func() error { return nil }); !errors.Is(err, ErrUnavailable) {
		t.Fatal("partial cleanup proved an unacknowledged creation", err)
	}
}
