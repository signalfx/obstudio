//go:build windows

package main

import (
	"os"
	"os/exec"
	"syscall"

	"golang.org/x/sys/windows"
)

func configureManagedProcess(command *exec.Cmd) {
	command.SysProcAttr = &syscall.SysProcAttr{CreationFlags: 0x00000008 | 0x00000200}
}

func tryLockManagedFile(file *os.File) (bool, error) {
	overlapped := new(windows.Overlapped)
	err := windows.LockFileEx(windows.Handle(file.Fd()), windows.LOCKFILE_EXCLUSIVE_LOCK|windows.LOCKFILE_FAIL_IMMEDIATELY, 0, 1, 0, overlapped)
	if err == windows.ERROR_LOCK_VIOLATION {
		return false, nil
	}
	return err == nil, err
}

func unlockManagedFile(file *os.File) error {
	return windows.UnlockFileEx(windows.Handle(file.Fd()), 0, 1, 0, new(windows.Overlapped))
}
