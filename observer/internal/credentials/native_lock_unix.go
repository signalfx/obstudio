//go:build !windows

package credentials

import (
	"golang.org/x/sys/unix"
	"os"
)

func tryLockCredentialFile(file *os.File) (func() error, error) {
	if err := unix.Flock(int(file.Fd()), unix.LOCK_EX|unix.LOCK_NB); err != nil {
		return nil, err
	}
	return func() error { return unix.Flock(int(file.Fd()), unix.LOCK_UN) }, nil
}
