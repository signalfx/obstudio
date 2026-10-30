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

func New() *Store { return NewWithBackend(nativeBackend{}) }

func NewWithBackend(backend Backend) *Store { return &Store{backend: backend} }

func account(scope, kind, destination, ref string) string {
	profile := sha256.Sum256([]byte(scope))
	target := sha256.Sum256([]byte(destination))
	return hex.EncodeToString(profile[:]) + "." + kind + "." + hex.EncodeToString(target[:]) + "." + ref
}

func (s *Store) Put(scope, kind, destination, secret string) (string, error) {
	if s.backend == nil || secret == "" || len(secret) > 4096 {
		return "", ErrUnavailable
	}
	var nonce [32]byte
	if _, err := rand.Read(nonce[:]); err != nil {
		return "", ErrUnavailable
	}
	ref := base64.RawURLEncoding.EncodeToString(nonce[:])
	key := account(scope, kind, destination, ref)
	if s.backend.Set(key, secret) == nil {
		if value, err := s.backend.Get(key); err == nil && value == secret {
			return ref, nil
		}
	}
	_ = s.backend.Delete(key)
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

func (s *Store) Delete(scope, kind, destination, ref string) {
	if s.backend == nil || !referencePattern.MatchString(ref) {
		return
	}
	_ = s.backend.Delete(account(scope, kind, destination, ref))
}
