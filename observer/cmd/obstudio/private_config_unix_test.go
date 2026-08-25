//go:build !windows

package main

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestWritePrivateConfigAtomicallyRejectsWritableParent(t *testing.T) {
	for _, test := range []struct {
		name string
		mode os.FileMode
	}{
		{name: "group", mode: 0o720},
		{name: "world", mode: 0o702},
	} {
		t.Run(test.name, func(t *testing.T) {
			directory := filepath.Join(t.TempDir(), "configs")
			if err := os.Mkdir(directory, 0o700); err != nil {
				t.Fatalf("create config directory: %v", err)
			}
			configPath := filepath.Join(directory, "mcp.json")
			original := []byte("existing private config")
			if err := os.WriteFile(configPath, original, 0o600); err != nil {
				t.Fatalf("write original config: %v", err)
			}
			if err := os.Chmod(directory, test.mode); err != nil {
				t.Fatalf("make config directory %s-writable: %v", test.name, err)
			}

			err := writePrivateConfigAtomically(configPath, []byte("replacement secret"))
			if err == nil || !strings.Contains(err.Error(), "must not be group- or world-writable") {
				t.Fatalf("write error = %v, want writable-parent rejection", err)
			}
			got, readErr := os.ReadFile(configPath)
			if readErr != nil {
				t.Fatalf("read preserved config: %v", readErr)
			}
			if !bytes.Equal(got, original) {
				t.Fatalf("rejected write changed config to %q", got)
			}
			entries, readErr := os.ReadDir(directory)
			if readErr != nil {
				t.Fatalf("read config directory: %v", readErr)
			}
			if len(entries) != 1 || entries[0].Name() != filepath.Base(configPath) {
				t.Fatalf("rejected write left temporary files: %#v", entries)
			}
		})
	}
}

func TestWritePrivateConfigAtomicallyAcceptsNonWritableParent(t *testing.T) {
	directory := filepath.Join(t.TempDir(), "configs")
	if err := os.Mkdir(directory, 0o755); err != nil {
		t.Fatalf("create config directory: %v", err)
	}
	configPath := filepath.Join(directory, "mcp.json")
	want := []byte("private config")
	if err := writePrivateConfigAtomically(configPath, want); err != nil {
		t.Fatalf("write private config: %v", err)
	}
	got, err := os.ReadFile(configPath)
	if err != nil {
		t.Fatalf("read private config: %v", err)
	}
	if !bytes.Equal(got, want) {
		t.Fatalf("private config = %q, want %q", got, want)
	}
	info, err := os.Stat(configPath)
	if err != nil {
		t.Fatalf("stat private config: %v", err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Fatalf("private config mode = %#o, want 0600", info.Mode().Perm())
	}
}

func TestWritePrivateConfigAtomicallyRejectsSymlinkParentBeforeWriting(t *testing.T) {
	root := t.TempDir()
	target := filepath.Join(root, "target")
	if err := os.Mkdir(target, 0o700); err != nil {
		t.Fatalf("create symlink target: %v", err)
	}
	link := filepath.Join(root, "link")
	if err := os.Symlink(target, link); err != nil {
		t.Fatalf("create parent symlink: %v", err)
	}

	err := writePrivateConfigAtomically(filepath.Join(link, "mcp.json"), []byte("must-not-be-written"))
	if err == nil || !strings.Contains(err.Error(), "parent is not a directory") {
		t.Fatalf("write error = %v, want symlink-parent rejection", err)
	}
	entries, readErr := os.ReadDir(target)
	if readErr != nil {
		t.Fatalf("read symlink target: %v", readErr)
	}
	if len(entries) != 0 {
		t.Fatalf("symlink target received private config data: %#v", entries)
	}
}

func TestWritePrivateConfigAtomicallyRejectsSymlinkTargetBeforeWriting(t *testing.T) {
	directory := t.TempDir()
	victimPath := filepath.Join(directory, "victim")
	victim := []byte("do not replace")
	if err := os.WriteFile(victimPath, victim, 0o600); err != nil {
		t.Fatalf("write symlink victim: %v", err)
	}
	configPath := filepath.Join(directory, "mcp.json")
	if err := os.Symlink(victimPath, configPath); err != nil {
		t.Fatalf("create config symlink: %v", err)
	}

	err := writePrivateConfigAtomically(configPath, []byte("replacement secret"))
	if err == nil || !strings.Contains(err.Error(), "target is not a regular file") {
		t.Fatalf("write error = %v, want symlink-target rejection", err)
	}
	got, readErr := os.ReadFile(victimPath)
	if readErr != nil {
		t.Fatalf("read symlink victim: %v", readErr)
	}
	if !bytes.Equal(got, victim) {
		t.Fatalf("symlink victim changed to %q", got)
	}
}

func TestReadSharedObserverStateRejectsInsecureFileMode(t *testing.T) {
	statePath := filepath.Join(t.TempDir(), sharedObserverStateFileName)
	if err := os.WriteFile(statePath, []byte("{}"), 0o644); err != nil {
		t.Fatalf("write shared observer state: %v", err)
	}
	if _, err := readSharedObserverState(statePath); err == nil || !strings.Contains(err.Error(), "want 0600") {
		t.Fatalf("read error = %v, want insecure-mode rejection", err)
	}
}

func TestReadSharedObserverStateRejectsSymlink(t *testing.T) {
	directory := t.TempDir()
	victimPath := filepath.Join(directory, "victim.json")
	if err := os.WriteFile(victimPath, []byte("{}"), 0o600); err != nil {
		t.Fatalf("write symlink victim: %v", err)
	}
	statePath := filepath.Join(directory, sharedObserverStateFileName)
	if err := os.Symlink(victimPath, statePath); err != nil {
		t.Fatalf("create state symlink: %v", err)
	}
	if _, err := readSharedObserverState(statePath); err == nil {
		t.Fatal("readSharedObserverState accepted a symlink")
	}
}

func TestReadSharedObserverStateRejectsUntrustedParent(t *testing.T) {
	directory := t.TempDir()
	statePath := filepath.Join(directory, sharedObserverStateFileName)
	if err := os.WriteFile(statePath, []byte("{}"), 0o600); err != nil {
		t.Fatalf("write shared observer state: %v", err)
	}
	if err := os.Chmod(directory, 0o770); err != nil {
		t.Fatalf("make state parent group-writable: %v", err)
	}
	t.Cleanup(func() { _ = os.Chmod(directory, 0o700) })
	if _, err := readSharedObserverState(statePath); err == nil || !strings.Contains(err.Error(), "must not be group- or world-writable") {
		t.Fatalf("read error = %v, want untrusted-parent rejection", err)
	}
}

func TestSecurePrivateConfigTemporaryRejectsSymlinkReplacement(t *testing.T) {
	directory := t.TempDir()
	temporary, err := os.CreateTemp(directory, ".mcp.json.tmp-*")
	if err != nil {
		t.Fatalf("create temporary config: %v", err)
	}
	defer temporary.Close()
	temporaryPath := temporary.Name()
	victimPath := filepath.Join(directory, "victim")
	victim := []byte("do not change")
	if err := os.WriteFile(victimPath, victim, 0o600); err != nil {
		t.Fatalf("write symlink victim: %v", err)
	}
	if err := os.Remove(temporaryPath); err != nil {
		t.Fatalf("remove temporary path: %v", err)
	}
	if err := os.Symlink(victimPath, temporaryPath); err != nil {
		t.Fatalf("replace temporary path with symlink: %v", err)
	}

	if _, err := securePrivateConfigTemporaryForWrite(temporary); err == nil {
		t.Fatal("securing replaced temporary config unexpectedly succeeded")
	}
	got, readErr := os.ReadFile(victimPath)
	if readErr != nil {
		t.Fatalf("read symlink victim: %v", readErr)
	}
	if !bytes.Equal(got, victim) {
		t.Fatalf("symlink victim changed to %q", got)
	}
}

func TestVerifyPrivateConfigPathIdentityRejectsRegularReplacement(t *testing.T) {
	directory := t.TempDir()
	temporary, err := os.CreateTemp(directory, ".mcp.json.tmp-*")
	if err != nil {
		t.Fatalf("create temporary config: %v", err)
	}
	info, err := temporary.Stat()
	if err != nil {
		t.Fatalf("stat temporary config: %v", err)
	}
	if err := temporary.Close(); err != nil {
		t.Fatalf("close temporary config: %v", err)
	}
	originalPath := temporary.Name() + ".original"
	if err := os.Rename(temporary.Name(), originalPath); err != nil {
		t.Fatalf("move original temporary config: %v", err)
	}
	if err := os.WriteFile(temporary.Name(), []byte("replacement"), 0o600); err != nil {
		t.Fatalf("replace temporary config: %v", err)
	}

	err = verifyPrivateConfigPathIdentity(temporary.Name(), info)
	if err == nil || !strings.Contains(err.Error(), "was replaced") {
		t.Fatalf("identity error = %v, want replacement rejection", err)
	}
}

func TestPublishPrivateConfigFileSyncsDirectoryAfterRename(t *testing.T) {
	t.Parallel()

	directory := t.TempDir()
	temporaryPath := filepath.Join(directory, ".mcp.json.tmp")
	targetPath := filepath.Join(directory, "mcp.json")
	want := []byte("private config")
	if err := os.WriteFile(temporaryPath, want, 0o600); err != nil {
		t.Fatalf("write temporary config: %v", err)
	}

	syncErr := errors.New("forced directory sync failure")
	err := publishPrivateConfigFileWithSync(temporaryPath, targetPath, func(path string) error {
		if path != directory {
			t.Fatalf("sync directory = %q, want %q", path, directory)
		}
		got, readErr := os.ReadFile(targetPath)
		if readErr != nil {
			t.Fatalf("read config before directory sync: %v", readErr)
		}
		if string(got) != string(want) {
			t.Fatalf("published config = %q, want %q", got, want)
		}
		return syncErr
	})
	if !errors.Is(err, syncErr) {
		t.Fatalf("publish error = %v, want %v", err, syncErr)
	}
	if _, err := os.Lstat(temporaryPath); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("temporary config still exists after rename: %v", err)
	}
}

func TestSyncPrivateConfigDirectory(t *testing.T) {
	t.Parallel()

	if err := syncPrivateConfigDirectory(t.TempDir()); err != nil {
		t.Fatalf("sync private config directory: %v", err)
	}
}
