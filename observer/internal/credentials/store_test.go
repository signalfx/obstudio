package credentials

import (
	"errors"
	"os"
	"strings"
	"testing"

	"github.com/zalando/go-keyring"
)

type memoryBackend struct {
	values      map[string]string
	unavailable bool
	discard     bool
}

func (b *memoryBackend) Get(key string) (string, error) {
	if b.unavailable {
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
func (b *memoryBackend) Delete(key string) error { delete(b.values, key); return nil }
func memory() *memoryBackend                     { return &memoryBackend{values: map[string]string{}} }

func TestStoreSavesBothDestinationsAndBindsReferences(t *testing.T) {
	store := NewWithBackend(memory())
	for _, kind := range []string{"cloud", "logs"} {
		ref, err := store.Put("profile", kind, "destination", "test-token")
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
	previous, err := store.Put("profile", "logs", "endpoint", "first-token")
	if err != nil {
		t.Fatal(err)
	}
	current, err := store.Put("profile", "logs", "endpoint", "second-token")
	if err != nil || current == previous {
		t.Fatal("new save did not create a revision")
	}
	if value, err := store.Get("profile", "logs", "endpoint", previous); err != nil || value != "first-token" {
		t.Fatal("new save replaced previous revision")
	}
	native.unavailable = true
	if _, err := store.Put("profile", "logs", "endpoint", "secret"); !errors.Is(err, ErrUnavailable) {
		t.Fatal("unavailable vault accepted a save")
	}
	native.unavailable = false
	native.discard = true
	if _, err := store.Put("profile", "logs", "endpoint", "secret"); !errors.Is(err, ErrUnavailable) {
		t.Fatal("save without readback was accepted")
	}
}

func TestStoreReportsUnavailableProviders(t *testing.T) {
	for _, backend := range []Backend{nil, &memoryBackend{unavailable: true}} {
		store := NewWithBackend(backend)
		if _, err := store.Put("profile", "logs", "destination", "test-token"); err != ErrUnavailable {
			t.Fatalf("unavailable provider returned %v", err)
		}
		ref := strings.Repeat("a", 43)
		if _, err := store.Get("profile", "logs", "destination", ref); err != ErrUnavailable {
			t.Fatalf("unavailable provider read returned %v", err)
		}
		store.Delete("profile", "logs", "destination", ref)
	}
}

func TestStoreValidatesCredentialValuesAndReferences(t *testing.T) {
	backend := memory()
	store := NewWithBackend(backend)
	for _, value := range []string{"", strings.Repeat("x", 4097)} {
		if _, err := store.Put("profile", "cloud", "destination", value); err != ErrUnavailable {
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
	if os.Getenv("OBSTUDIO_TEST_SYSTEM_KEYRING") == "1" {
		t.Skip("OS credential check runs without the mock provider")
	}
	keyring.MockInit()
	native := nativeBackend{}
	value := strings.Repeat("x", 4096)
	if err := native.Set("test-account", value); err != nil {
		t.Fatal(err)
	}
	if got, err := native.Get("test-account"); err != nil || got != value {
		t.Fatal("maximum-size credential did not reload")
	}
	if err := keyring.Set(serviceName, "test-account.1", "corrupted"); err != nil {
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
		t.Run(kind, func(t *testing.T) {
			store := New()
			ref, err := store.Put(profile, kind, "https://test.invalid", "synthetic-keychain-test")
			if err != nil {
				t.Fatal(err)
			}
			t.Cleanup(func() { store.Delete(profile, kind, "https://test.invalid", ref) })
			reloaded := New()
			if value, err := reloaded.Get(profile, kind, "https://test.invalid", ref); err != nil || value != "synthetic-keychain-test" {
				t.Fatal("OS credential did not reload")
			}
			reloaded.Delete(profile, kind, "https://test.invalid", ref)
			if _, err := New().Get(profile, kind, "https://test.invalid", ref); !errors.Is(err, ErrNotFound) {
				t.Fatal("deleted OS credential remains available")
			}
		})
	}
}
