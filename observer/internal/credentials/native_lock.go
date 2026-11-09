package credentials

import (
	"os"
	"path/filepath"
)

func tryCredentialOperationLock(path string) (func(), error) {
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return nil, err
	}
	file, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0o600)
	if err != nil {
		return nil, err
	}
	unlock, err := tryLockCredentialFile(file)
	if err != nil {
		_ = file.Close()
		return nil, err
	}
	return func() { _ = unlock(); _ = file.Close() }, nil
}
