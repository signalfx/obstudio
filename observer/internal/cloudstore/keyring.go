package cloudstore

import (
	"encoding/json"
	"errors"
	"fmt"

	"github.com/zalando/go-keyring"

	"github.com/signalfx/obstudio/observer/internal/o11yoauth"
)

const (
	keyringService = "com.splunk.obstudio"
	keyringAccount = "o11y-cloud-connection"
)

var ErrNotFound = errors.New("Splunk Observability Cloud connection not found")

type Store interface {
	Delete() error
	Load() (o11yoauth.Connection, error)
	Save(o11yoauth.Connection) error
}

type Keyring struct{}

func (Keyring) Save(connection o11yoauth.Connection) error {
	payload, err := json.Marshal(connection)
	if err != nil {
		return fmt.Errorf("encode cloud connection: %w", err)
	}
	if err := keyring.Set(keyringService, keyringAccount, string(payload)); err != nil {
		return fmt.Errorf("store cloud connection in OS keychain: %w", err)
	}
	return nil
}

func (Keyring) Load() (o11yoauth.Connection, error) {
	payload, err := keyring.Get(keyringService, keyringAccount)
	if errors.Is(err, keyring.ErrNotFound) {
		return o11yoauth.Connection{}, ErrNotFound
	}
	if err != nil {
		return o11yoauth.Connection{}, fmt.Errorf("read cloud connection from OS keychain: %w", err)
	}
	var connection o11yoauth.Connection
	if err := json.Unmarshal([]byte(payload), &connection); err != nil {
		return o11yoauth.Connection{}, fmt.Errorf("decode cloud connection from OS keychain: %w", err)
	}
	if err := o11yoauth.ValidateConnection(connection); err != nil {
		return o11yoauth.Connection{}, fmt.Errorf("OS keychain contains an invalid cloud connection: %w", err)
	}
	return connection, nil
}

func (Keyring) Delete() error {
	err := keyring.Delete(keyringService, keyringAccount)
	if errors.Is(err, keyring.ErrNotFound) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("delete cloud connection from OS keychain: %w", err)
	}
	return nil
}
