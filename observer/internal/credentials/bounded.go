package credentials

import (
	"errors"
	"os"
	"path/filepath"
	"sync"
	"time"
)

const credentialOperationTimeout = 5 * time.Second

var errOperationPending = errors.Join(ErrUnavailable, errors.New("native operation completion is unconfirmed"))

type boundedBackend struct {
	backend  Backend
	timeout  time.Duration
	mu       sync.Mutex
	shared   bool
	lockPath string
}

type backendResult struct {
	value string
	err   error
}

// A timed-out write retains ownership until it finishes. Cleanup cannot race a
// late write and discard the reference needed to remove its credential.
func (b *boundedBackend) run(operation func() (string, error)) (string, error) {
	if !b.mu.TryLock() {
		return "", ErrUnavailable
	}
	release := func() {}
	if b.shared || b.lockPath != "" {
		path := b.lockPath
		if path == "" {
			home, err := os.UserHomeDir()
			if err != nil || home == "" {
				b.mu.Unlock()
				return "", ErrUnavailable
			}
			path = filepath.Join(home, ".obstudio", "credential-operation.lock")
		}
		var err error
		release, err = tryCredentialOperationLock(path)
		if err != nil {
			b.mu.Unlock()
			return "", ErrUnavailable
		}
	}
	result := make(chan backendResult, 1)
	go func() {
		value, err := operation()
		release()
		b.mu.Unlock()
		result <- backendResult{value, err}
	}()
	timer := time.NewTimer(b.timeout)
	defer timer.Stop()
	select {
	case completed := <-result:
		return completed.value, completed.err
	case <-timer.C:
		return "", errOperationPending
	}
}

func (b *boundedBackend) Get(key string) (string, error) {
	return b.run(func() (string, error) { return b.backend.Get(key) })
}

func (b *boundedBackend) Set(key, value string) error {
	_, err := b.run(func() (string, error) { return "", b.backend.Set(key, value) })
	return err
}

func (b *boundedBackend) Delete(key string) error {
	_, err := b.run(func() (string, error) { return "", b.backend.Delete(key) })
	return err
}
