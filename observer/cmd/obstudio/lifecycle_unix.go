//go:build !windows

package main

import (
	"os"
	"os/exec"
	"syscall"
)

func configureManagedProcess(command *exec.Cmd) {
	command.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
}

func tryLockManagedFile(file *os.File) (bool, error) {
	err := syscall.Flock(int(file.Fd()), syscall.LOCK_EX|syscall.LOCK_NB)
	if err == syscall.EWOULDBLOCK {
		return false, nil
	}
	return err == nil, err
}

func unlockManagedFile(file *os.File) error {
	return syscall.Flock(int(file.Fd()), syscall.LOCK_UN)
}
