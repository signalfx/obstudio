package credentials

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
)

const serviceName = "Splunk Observability Studio"
const nativeChunkBytes = 1536

type nativeBackend struct{ store Backend }

func (b nativeBackend) keyring() Backend {
	if b.store != nil {
		return b.store
	}
	return platformBackend{}
}

type nativeManifest struct {
	Chunks int    `json:"chunks"`
	Digest string `json:"digest"`
}

func (b nativeBackend) Set(key, value string) error {
	manifest := nativeManifest{Chunks: (len(value) + nativeChunkBytes - 1) / nativeChunkBytes}
	digest := sha256.Sum256([]byte(value))
	manifest.Digest = hex.EncodeToString(digest[:])
	for i := 0; i < manifest.Chunks; i++ {
		end := min((i+1)*nativeChunkBytes, len(value))
		if err := b.keyring().Set(fmt.Sprintf("%s.%d", key, i), value[i*nativeChunkBytes:end]); err != nil {
			if errors.Is(err, ErrWritePending) {
				return ErrWritePending
			}
			return ErrUnavailable
		}
	}
	encoded, _ := json.Marshal(manifest)
	if err := b.keyring().Set(key, string(encoded)); err != nil {
		if errors.Is(err, ErrWritePending) {
			return ErrWritePending
		}
		return ErrUnavailable
	}
	return nil
}

func (b nativeBackend) Get(key string) (string, error) {
	encoded, err := b.keyring().Get(key)
	if errors.Is(err, ErrNotFound) {
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
		chunk, err := b.keyring().Get(fmt.Sprintf("%s.%d", key, i))
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

func (b nativeBackend) Delete(key string) error {
	var failed bool
	for i := 0; i < 3; i++ {
		if err := b.keyring().Delete(fmt.Sprintf("%s.%d", key, i)); err != nil && !errors.Is(err, ErrNotFound) {
			failed = true
		}
	}
	if failed {
		return ErrUnavailable
	}
	if err := b.keyring().Delete(key); err != nil && !errors.Is(err, ErrNotFound) {
		return ErrUnavailable
	}
	return nil
}
