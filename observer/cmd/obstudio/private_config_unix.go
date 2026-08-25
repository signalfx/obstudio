//go:build !windows

package main

import (
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"syscall"

	"golang.org/x/sys/unix"
)

func validatePrivateConfigDirectory(path string) error {
	info, err := os.Lstat(path)
	if err != nil {
		return err
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		return errors.New("private config parent is not a directory")
	}
	if err := validatePrivateConfigOwner(info, "private config parent"); err != nil {
		return err
	}
	if info.Mode().Perm()&0o022 != 0 {
		return errors.New("private config parent must not be group- or world-writable")
	}

	directory, err := openPrivateConfigPath(path, unix.O_RDONLY|unix.O_DIRECTORY)
	if err != nil {
		return err
	}
	defer directory.Close()
	openedInfo, err := directory.Stat()
	if err != nil {
		return err
	}
	if !os.SameFile(info, openedInfo) {
		return errors.New("private config parent changed while opening it")
	}
	return nil
}

func securePrivateConfigFile(path string) error {
	file, err := openPrivateConfigPath(path, unix.O_WRONLY)
	if err != nil {
		return err
	}
	defer file.Close()
	if err := securePrivateConfigDescriptor(file); err != nil {
		return err
	}
	info, err := file.Stat()
	if err != nil {
		return err
	}
	return verifyPrivateConfigPathIdentity(path, info)
}

func readPrivateConfigFile(path string) ([]byte, error) {
	file, err := openPrivateConfigPath(path, unix.O_RDONLY)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() {
		return nil, errors.New("private config path is not a regular file")
	}
	if err := validatePrivateConfigOwner(info, "private config"); err != nil {
		return nil, err
	}
	if info.Mode().Perm() != 0o600 {
		return nil, fmt.Errorf("private config mode is %#o, want 0600", info.Mode().Perm())
	}
	if err := verifyPrivateConfigPathIdentity(path, info); err != nil {
		return nil, err
	}
	return io.ReadAll(file)
}

func createPrivateConfigTemporary(directory, prefix string) (privateConfigTemporary, error) {
	file, err := os.CreateTemp(directory, prefix+"*")
	if err != nil {
		return nil, err
	}
	return securePrivateConfigTemporaryForWrite(file)
}

func securePrivateConfigTemporaryForWrite(file *os.File) (*os.File, error) {
	if file == nil {
		return nil, errors.New("temporary private config is nil")
	}
	if err := securePrivateConfigDescriptor(file); err != nil {
		_ = file.Close()
		return nil, err
	}
	info, err := file.Stat()
	if err != nil {
		_ = file.Close()
		return nil, err
	}
	if err := verifyPrivateConfigPathIdentity(file.Name(), info); err != nil {
		_ = file.Close()
		return nil, err
	}
	return file, nil
}

func securePrivateConfigDescriptor(file *os.File) error {
	info, err := file.Stat()
	if err != nil {
		return err
	}
	if !info.Mode().IsRegular() {
		return errors.New("private MCP config path is not a regular file")
	}
	if err := validatePrivateConfigOwner(info, "private MCP config"); err != nil {
		return err
	}
	if err := file.Chmod(0o600); err != nil {
		return err
	}
	securedInfo, err := file.Stat()
	if err != nil {
		return err
	}
	if securedInfo.Mode().Perm() != 0o600 {
		return fmt.Errorf("private MCP config mode is %#o, want 0600", securedInfo.Mode().Perm())
	}
	return nil
}

func verifyPrivateConfigPathIdentity(path string, expected os.FileInfo) error {
	info, err := os.Lstat(path)
	if err != nil {
		return err
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		return errors.New("private MCP config path is not a regular file")
	}
	if !os.SameFile(info, expected) {
		return errors.New("private MCP config path was replaced")
	}
	if err := validatePrivateConfigOwner(info, "private MCP config"); err != nil {
		return err
	}
	return nil
}

func validatePrivateConfigOwner(info os.FileInfo, description string) error {
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok {
		return fmt.Errorf("read %s owner", description)
	}
	if int(stat.Uid) != os.Geteuid() {
		return fmt.Errorf("%s is not owned by the current user", description)
	}
	return nil
}

func openPrivateConfigPath(path string, flags int) (*os.File, error) {
	fd, err := unix.Open(path, flags|unix.O_CLOEXEC|unix.O_NOFOLLOW, 0)
	if err != nil {
		return nil, err
	}
	file := os.NewFile(uintptr(fd), path)
	if file == nil {
		_ = unix.Close(fd)
		return nil, errors.New("wrap private MCP config descriptor")
	}
	return file, nil
}

func publishPrivateConfigFile(temporary privateConfigTemporary, _ os.FileInfo, targetPath string) error {
	if temporary == nil {
		return errors.New("temporary private config is nil")
	}
	return publishPrivateConfigFileWithSync(temporary.Name(), targetPath, syncPrivateConfigDirectory)
}

func publishPrivateConfigFileWithSync(temporaryPath, targetPath string, syncDirectory func(string) error) error {
	if err := os.Rename(temporaryPath, targetPath); err != nil {
		return err
	}
	return syncDirectory(filepath.Dir(targetPath))
}

func syncPrivateConfigDirectory(path string) error {
	directory, err := openPrivateConfigPath(path, unix.O_RDONLY|unix.O_DIRECTORY)
	if err != nil {
		return err
	}
	if err := directory.Sync(); err != nil {
		_ = directory.Close()
		return err
	}
	return directory.Close()
}
