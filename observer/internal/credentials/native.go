package credentials

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"strings"

	"github.com/zalando/go-keyring"
)

const serviceName = "Splunk Observability Studio"
const nativeChunkBytes = 1536

type nativeBackend struct{}
type nativeManifest struct {
	Chunks int    `json:"chunks"`
	Digest string `json:"digest"`
}

func (nativeBackend) Set(key, value string) error {
	manifest := nativeManifest{Chunks: (len(value) + nativeChunkBytes - 1) / nativeChunkBytes}
	digest := sha256.Sum256([]byte(value))
	manifest.Digest = hex.EncodeToString(digest[:])
	for i := 0; i < manifest.Chunks; i++ {
		end := min((i+1)*nativeChunkBytes, len(value))
		if err := keyring.Set(serviceName, fmt.Sprintf("%s.%d", key, i), value[i*nativeChunkBytes:end]); err != nil {
			return ErrUnavailable
		}
	}
	encoded, _ := json.Marshal(manifest)
	if err := keyring.Set(serviceName, key, string(encoded)); err != nil {
		return ErrUnavailable
	}
	return nil
}

func (nativeBackend) Get(key string) (string, error) {
	encoded, err := keyring.Get(serviceName, key)
	if errors.Is(err, keyring.ErrNotFound) {
		return "", ErrNotFound
	}
	if err != nil {
		return "", ErrUnavailable
	}
	var manifest nativeManifest
	if json.Unmarshal([]byte(encoded), &manifest) != nil || manifest.Chunks < 1 || manifest.Chunks > 3 {
		return "", ErrUnavailable
	}
	var value strings.Builder
	for i := 0; i < manifest.Chunks; i++ {
		chunk, err := keyring.Get(serviceName, fmt.Sprintf("%s.%d", key, i))
		if err != nil {
			return "", ErrUnavailable
		}
		value.WriteString(chunk)
	}
	digest := sha256.Sum256([]byte(value.String()))
	if hex.EncodeToString(digest[:]) != manifest.Digest {
		return "", ErrUnavailable
	}
	return value.String(), nil
}

func (nativeBackend) Delete(key string) error {
	for i := 0; i < 3; i++ {
		_ = keyring.Delete(serviceName, fmt.Sprintf("%s.%d", key, i))
	}
	if err := keyring.Delete(serviceName, key); err != nil && !errors.Is(err, keyring.ErrNotFound) {
		return ErrUnavailable
	}
	return nil
}
