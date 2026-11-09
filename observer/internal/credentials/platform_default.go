//go:build !linux

package credentials

import (
	"errors"
	"github.com/zalando/go-keyring"
)

type platformBackend struct{}

func (platformBackend) Get(key string) (string, error) {
	value, err := keyring.Get(serviceName, key)
	if errors.Is(err, keyring.ErrNotFound) {
		return "", ErrNotFound
	}
	return value, err
}
func (platformBackend) Set(key, value string) error { return keyring.Set(serviceName, key, value) }
func (platformBackend) Delete(key string) error {
	err := keyring.Delete(serviceName, key)
	if errors.Is(err, keyring.ErrNotFound) {
		return ErrNotFound
	}
	return err
}
