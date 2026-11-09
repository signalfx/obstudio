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
	backend      Backend
	timeout      time.Duration
	mu           sync.Mutex
	shared       bool
	lockPath     string
	failedWrites sync.Map
}

type backendResult struct {
	value string
	err   error
}

// A timed-out write retains ownership until it finishes. Cleanup cannot race a
// late write and discard the reference needed to remove its credential.
func (b *boundedBackend) run(operation func() (string, error), waitForAccess bool) (string, error) {
	path := b.lockPath
	if b.shared && path == "" {
		home, err := os.UserHomeDir()
		if err != nil || home == "" {
			return "", ErrUnavailable
		}
		path = filepath.Join(home, ".obstudio", "credential-operation.lock")
	}
	timer := time.NewTimer(b.timeout)
	defer timer.Stop()
	retry := time.NewTicker(10 * time.Millisecond)
	defer retry.Stop()
	release := func() {}
	for {
		if b.mu.TryLock() {
			var err error
			if path != "" {
				release, err = tryCredentialOperationLock(path)
			}
			if err == nil {
				break
			}
			b.mu.Unlock()
		}
		if !waitForAccess {
			return "", ErrUnavailable
		}
		select {
		case <-timer.C:
			return "", ErrUnavailable
		case <-retry.C:
		}
	}
	select {
	case <-timer.C:
		release()
		b.mu.Unlock()
		return "", ErrUnavailable
	default:
	}
	result := make(chan backendResult, 1)
	go func() {
		value, err := operation()
		release()
		b.mu.Unlock()
		result <- backendResult{value, err}
	}()
	select {
	case completed := <-result:
		return completed.value, completed.err
	case <-timer.C:
		return "", errOperationPending
	}
}

func (b *boundedBackend) Get(key string) (string, error) {
	return b.get(key, true)
}

func (b *boundedBackend) get(key string, waitForAccess bool) (string, error) {
	return b.run(func() (string, error) { return b.backend.Get(key) }, waitForAccess)
}

func (b *boundedBackend) Set(key, value string) error {
	_, err := b.run(func() (string, error) {
		b.failedWrites.Delete(key)
		err := b.backend.Set(key, value)
		if errors.Is(err, ErrWriteNotStarted) {
			b.failedWrites.Store(key, ErrWriteNotStarted)
			return "", ErrWriteNotStarted
		}
		if err != nil && !errors.Is(err, ErrWritePending) && !errors.Is(err, errOperationPending) {
			b.failedWrites.Store(key, true)
			return "", ErrStorageRefused
		}
		return "", err
	}, true)
	return err
}

func (b *boundedBackend) Delete(key string) error {
	_, err := b.run(func() (string, error) {
		err := b.backend.Delete(key)
		if err == nil || errors.Is(err, ErrNotFound) {
			b.failedWrites.Delete(key)
		}
		return "", err
	}, false)
	return err
}
