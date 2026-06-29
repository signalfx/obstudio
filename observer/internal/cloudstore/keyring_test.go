package cloudstore

import (
	"errors"
	"testing"

	"github.com/zalando/go-keyring"

	"github.com/signalfx/obstudio/observer/internal/o11yoauth"
)

func TestKeyringRoundTripAndDelete(t *testing.T) {
	keyring.MockInit()
	store := Keyring{}
	connection := o11yoauth.Connection{
		AccessToken: "secret-token",
		ConnectedAt: "2026-06-29T12:00:00Z",
		Endpoint:    "https://ingest.us1.signalfx.com",
		Issuer:      "https://app.us1.signalfx.com",
		Realm:       "us1",
		Scope:       "api ingest",
		TokenType:   "Bearer",
	}
	if err := store.Save(connection); err != nil {
		t.Fatalf("Save() error = %v", err)
	}
	loaded, err := store.Load()
	if err != nil {
		t.Fatalf("Load() error = %v", err)
	}
	if loaded != connection {
		t.Fatalf("Load() = %+v, want %+v", loaded, connection)
	}
	if err := store.Delete(); err != nil {
		t.Fatalf("Delete() error = %v", err)
	}
	if _, err := store.Load(); !errors.Is(err, ErrNotFound) {
		t.Fatalf("Load() after delete error = %v, want ErrNotFound", err)
	}
}

func TestKeyringRejectsInvalidStoredConnection(t *testing.T) {
	keyring.MockInit()
	if err := keyring.Set(keyringService, keyringAccount, `{"accessToken":"secret","issuer":"https://attacker.example","tokenType":"Bearer"}`); err != nil {
		t.Fatalf("seed keyring: %v", err)
	}
	if _, err := (Keyring{}).Load(); err == nil {
		t.Fatal("Load() accepted an invalid stored connection")
	}
}

func TestKeyringProviderErrorsAreWrapped(t *testing.T) {
	keyring.MockInitWithError(errors.New("provider unavailable"))
	t.Cleanup(keyring.MockInit)
	if _, err := (Keyring{}).Load(); err == nil || err.Error() != "read cloud connection from OS keychain: provider unavailable" {
		t.Fatalf("Load() error = %v", err)
	}
}
