package credentials

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"regexp"
)

var (
	ErrNotFound      = errors.New("saved credential is unavailable")
	ErrUnavailable   = errors.New("secure credential storage is unavailable; unlock the system credential store and try again")
	ErrWritePending  = errors.Join(ErrUnavailable, errors.New("credential write completion is unconfirmed"))
	referencePattern = regexp.MustCompile(`^[A-Za-z0-9_-]{43}$`)
)

type Backend interface {
	Get(string) (string, error)
	Set(string, string) error
	Delete(string) error
}

type Store struct {
	backend Backend
}

var systemBackend = &boundedBackend{backend: nativeBackend{}, timeout: credentialOperationTimeout, shared: true}

func New() *Store { return &Store{backend: systemBackend} }

func NewWithBackend(backend Backend) *Store {
	if backend == nil {
		return &Store{}
	}
	if _, ok := backend.(*boundedBackend); !ok {
		backend = &boundedBackend{backend: backend, timeout: credentialOperationTimeout}
	}
	return &Store{backend: backend}
}

func account(scope, kind, destination, ref string) string {
	profile := sha256.Sum256([]byte(scope))
	target := sha256.Sum256([]byte(destination))
	return hex.EncodeToString(profile[:]) + "." + kind + "." + hex.EncodeToString(target[:]) + "." + ref
}

// Put retains the reference before writing so interrupted or failed writes can be cleaned up.
func (s *Store) Put(scope, kind, destination, secret string, retain func(string) error) (string, error) {
	if s.backend == nil || secret == "" || len(secret) > 4096 || retain == nil {
		return "", ErrUnavailable
	}
	var nonce [32]byte
	if _, err := rand.Read(nonce[:]); err != nil {
		return "", ErrUnavailable
	}
	ref := base64.RawURLEncoding.EncodeToString(nonce[:])
	if err := retain(ref); err != nil {
		return "", ErrUnavailable
	}
	key := account(scope, kind, destination, ref)
	if err := s.backend.Set(key, secret); errors.Is(err, errOperationPending) || errors.Is(err, ErrWritePending) {
		return "", ErrWritePending
	} else if err == nil {
		if value, err := s.backend.Get(key); err == nil && value == secret {
			return ref, nil
		}
	}
	return "", ErrUnavailable
}

func (s *Store) Get(scope, kind, destination, ref string) (string, error) {
	if !referencePattern.MatchString(ref) {
		return "", ErrNotFound
	}
	if s.backend == nil {
		return "", ErrUnavailable
	}
	value, err := s.backend.Get(account(scope, kind, destination, ref))
	if errors.Is(err, ErrNotFound) {
		return "", ErrNotFound
	}
	if err == nil && value != "" && len(value) <= 4096 {
		return value, nil
	}
	return "", ErrUnavailable
}

func (s *Store) Delete(scope, kind, destination, ref string) error {
	if ref == "" {
		return nil
	}
	if !referencePattern.MatchString(ref) {
		return ErrNotFound
	}
	if s.backend == nil {
		return ErrUnavailable
	}
	if err := s.backend.Delete(account(scope, kind, destination, ref)); err != nil && !errors.Is(err, ErrNotFound) {
		return ErrUnavailable
	}
	return nil
}

// Only a complete credential proves creation finished. Partial chunks can be
// removed, but their reference must survive a provider write that is still pending.
func (s *Store) DeleteUnconfirmed(scope, kind, destination, ref string, confirm func() error) error {
	_, readErr := s.Get(scope, kind, destination, ref)
	if readErr != nil {
		if errors.Is(readErr, ErrNotFound) {
			_ = s.Delete(scope, kind, destination, ref)
		}
		return ErrUnavailable
	}
	if confirm == nil || confirm() != nil {
		return ErrUnavailable
	}
	return s.Delete(scope, kind, destination, ref)
}
