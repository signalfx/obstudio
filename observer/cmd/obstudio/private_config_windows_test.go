//go:build windows

package main

import (
	"bytes"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"golang.org/x/sys/windows"
)

func TestWritePrivateConfigAtomicallySecuresAndReplacesOnWindows(t *testing.T) {
	directory := filepath.Join(t.TempDir(), "configs")
	if err := os.Mkdir(directory, 0o700); err != nil {
		t.Fatalf("create config directory: %v", err)
	}
	configPath := filepath.Join(directory, "mcp.json")
	if err := os.WriteFile(configPath, []byte("existing private config"), 0o600); err != nil {
		t.Fatalf("write existing config: %v", err)
	}
	want := []byte(`{"headers":{"Authorization":"Bearer secret"}}`)
	if err := writePrivateConfigAtomically(configPath, want); err != nil {
		t.Fatalf("write private config: %v", err)
	}
	got, err := readPrivateConfigFile(configPath)
	if err != nil {
		t.Fatalf("read private config: %v", err)
	}
	if !bytes.Equal(got, want) {
		t.Fatalf("private config = %q, want %q", got, want)
	}
	entries, err := os.ReadDir(directory)
	if err != nil {
		t.Fatalf("read config directory: %v", err)
	}
	if len(entries) != 1 || entries[0].Name() != filepath.Base(configPath) {
		t.Fatalf("private config write left temporary files: %#v", entries)
	}
}

func TestWriteSharedObserverStatePublishesSecureControlStateOnWindows(t *testing.T) {
	directory := filepath.Join(t.TempDir(), "state")
	statePath := filepath.Join(directory, sharedObserverStateFileName)
	want := sharedObserverState{
		BaseURL:      "http://127.0.0.1:3000",
		HealthURL:    "http://127.0.0.1:3000/api/health",
		ControlToken: "shared-control-token",
		MCPURL:       "http://127.0.0.1:3000/mcp",
	}
	if err := writeSharedObserverState(statePath, want); err != nil {
		t.Fatalf("write shared Observer state: %v", err)
	}
	got, err := readSharedObserverState(statePath)
	if err != nil {
		t.Fatalf("read shared Observer state: %v", err)
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("shared Observer state = %#v, want %#v", got, want)
	}
}

func TestWritePrivateConfigRejectsWindowsReparseParentBeforeTokenWrite(t *testing.T) {
	root := t.TempDir()
	target := filepath.Join(root, "target")
	if err := os.Mkdir(target, 0o700); err != nil {
		t.Fatalf("create reparse target: %v", err)
	}
	link := filepath.Join(root, "link")
	if err := os.Symlink(target, link); err != nil {
		t.Skipf("Windows symlink creation is unavailable: %v", err)
	}
	err := writePrivateConfigAtomically(filepath.Join(link, "mcp.json"), []byte("Bearer must-not-be-written"))
	if err == nil || !strings.Contains(strings.ToLower(err.Error()), "reparse") {
		t.Fatalf("write through reparse parent error = %v, want reparse rejection", err)
	}
	entries, readErr := os.ReadDir(target)
	if readErr != nil {
		t.Fatalf("read reparse target: %v", readErr)
	}
	if len(entries) != 0 {
		t.Fatalf("reparse target received private config data: %#v", entries)
	}
}

func TestCreatePrivateConfigTemporaryUsesOwnerOnlyDACLOnWindows(t *testing.T) {
	directory := t.TempDir()
	temporary, err := createPrivateConfigTemporary(directory, ".mcp.json.tmp-")
	if err != nil {
		t.Fatalf("create private temporary config: %v", err)
	}
	t.Cleanup(func() {
		_ = temporary.Close()
		_ = os.Remove(temporary.Name())
	})
	userSID, err := currentMCPConfigWindowsUserSID()
	if err != nil {
		t.Fatalf("current user SID: %v", err)
	}
	windowsTemporary, ok := temporary.(*windowsPrivateConfigTemporary)
	if !ok {
		t.Fatalf("temporary config type = %T, want secured Windows temporary", temporary)
	}
	if err := verifyMCPConfigOwnerOnlyDACL(windows.Handle(windowsTemporary.Fd()), userSID); err != nil {
		t.Fatalf("temporary config ACL: %v", err)
	}
}

func TestPublishPrivateConfigFileAtomicallyReplacesOnWindows(t *testing.T) {
	directory := t.TempDir()
	targetPath := filepath.Join(directory, "mcp.json")
	temporaryData := []byte("temporary secret")
	targetData := []byte("existing config")
	temporary, err := createPrivateConfigTemporary(directory, ".mcp.json.tmp-")
	if err != nil {
		t.Fatalf("create temporary config: %v", err)
	}
	temporaryPath := temporary.Name()
	if _, err := temporary.Write(temporaryData); err != nil {
		t.Fatalf("write temporary config: %v", err)
	}
	if err := temporary.Sync(); err != nil {
		t.Fatalf("sync temporary config: %v", err)
	}
	temporaryInfo, err := temporary.Stat()
	if err != nil {
		t.Fatalf("stat temporary config: %v", err)
	}
	if err := os.WriteFile(targetPath, targetData, 0o600); err != nil {
		t.Fatalf("write target config: %v", err)
	}

	if err := publishPrivateConfigFile(temporary, temporaryInfo, targetPath); err != nil {
		_ = temporary.Close()
		t.Fatalf("publish private config: %v", err)
	}
	if err := temporary.Close(); err != nil {
		t.Fatalf("close published config: %v", err)
	}
	if _, err := os.Lstat(temporaryPath); !os.IsNotExist(err) {
		t.Fatalf("temporary path remains after publish: %v", err)
	}
	gotTarget, err := readPrivateConfigFile(targetPath)
	if err != nil {
		t.Fatalf("read target config: %v", err)
	}
	if !bytes.Equal(gotTarget, temporaryData) {
		t.Fatalf("target config = %q, want %q", gotTarget, temporaryData)
	}
}

func TestPublishPrivateConfigFileReplacesOpenDestinationOnWindows(t *testing.T) {
	directory := t.TempDir()
	temporary, err := createPrivateConfigTemporary(directory, ".mcp.json.tmp-")
	if err != nil {
		t.Fatalf("create temporary config: %v", err)
	}
	defer temporary.Close()
	defer os.Remove(temporary.Name())
	want := []byte("replacement config")
	if _, err := temporary.Write(want); err != nil {
		t.Fatalf("write temporary config: %v", err)
	}
	if err := temporary.Sync(); err != nil {
		t.Fatalf("sync temporary config: %v", err)
	}
	temporaryInfo, err := temporary.Stat()
	if err != nil {
		t.Fatalf("stat temporary config: %v", err)
	}
	targetPath := filepath.Join(directory, "mcp.json")
	if err := os.WriteFile(targetPath, []byte("existing config"), 0o600); err != nil {
		t.Fatalf("write target config: %v", err)
	}
	targetPointer, err := windows.UTF16PtrFromString(targetPath)
	if err != nil {
		t.Fatalf("encode target path: %v", err)
	}
	openTarget, err := windows.CreateFile(
		targetPointer,
		windows.GENERIC_READ,
		windows.FILE_SHARE_READ|windows.FILE_SHARE_WRITE,
		nil,
		windows.OPEN_EXISTING,
		windows.FILE_ATTRIBUTE_NORMAL,
		0,
	)
	if err != nil {
		t.Fatalf("open target without delete sharing: %v", err)
	}
	defer windows.CloseHandle(openTarget)

	if err := publishPrivateConfigFile(temporary, temporaryInfo, targetPath); err != nil {
		t.Fatalf("replace open destination: %v", err)
	}
	got, err := readPrivateConfigFile(targetPath)
	if err != nil {
		t.Fatalf("read replacement config: %v", err)
	}
	if !bytes.Equal(got, want) {
		t.Fatalf("replacement config = %q, want %q", got, want)
	}
}

func TestPublishPrivateConfigFileRejectsDescriptorIdentityMismatchOnWindows(t *testing.T) {
	directory := t.TempDir()
	temporary, err := createPrivateConfigTemporary(directory, ".mcp.json.tmp-")
	if err != nil {
		t.Fatalf("create temporary config: %v", err)
	}
	defer temporary.Close()
	defer os.Remove(temporary.Name())
	other, err := createPrivateConfigTemporary(directory, ".other.tmp-")
	if err != nil {
		t.Fatalf("create identity source: %v", err)
	}
	otherInfo, err := other.Stat()
	if err != nil {
		t.Fatalf("stat identity source: %v", err)
	}
	if err := other.Close(); err != nil {
		t.Fatalf("close identity source: %v", err)
	}
	defer os.Remove(other.Name())
	targetPath := filepath.Join(directory, "mcp.json")
	want := []byte("existing config")
	if err := os.WriteFile(targetPath, want, 0o600); err != nil {
		t.Fatalf("write target config: %v", err)
	}

	err = publishPrivateConfigFile(temporary, otherInfo, targetPath)
	if err == nil || !strings.Contains(err.Error(), "descriptor was replaced") {
		t.Fatalf("publish identity error = %v, want descriptor replacement rejection", err)
	}
	got, err := os.ReadFile(targetPath)
	if err != nil {
		t.Fatalf("read preserved target: %v", err)
	}
	if !bytes.Equal(got, want) {
		t.Fatalf("target config = %q, want %q", got, want)
	}
}

func TestPublishPrivateConfigFileRejectsWindowsReparseTarget(t *testing.T) {
	directory := t.TempDir()
	temporary, err := createPrivateConfigTemporary(directory, ".mcp.json.tmp-")
	if err != nil {
		t.Fatalf("create temporary config: %v", err)
	}
	defer temporary.Close()
	defer os.Remove(temporary.Name())
	temporaryInfo, err := temporary.Stat()
	if err != nil {
		t.Fatalf("stat temporary config: %v", err)
	}
	victimPath := filepath.Join(directory, "victim.json")
	want := []byte("do not replace")
	if err := os.WriteFile(victimPath, want, 0o600); err != nil {
		t.Fatalf("write reparse target: %v", err)
	}
	targetPath := filepath.Join(directory, "mcp.json")
	if err := os.Symlink(victimPath, targetPath); err != nil {
		t.Skipf("Windows symlink creation is unavailable: %v", err)
	}

	err = publishPrivateConfigFile(temporary, temporaryInfo, targetPath)
	if err == nil || !strings.Contains(strings.ToLower(err.Error()), "regular file") {
		t.Fatalf("publish through reparse target error = %v, want target rejection", err)
	}
	got, err := os.ReadFile(victimPath)
	if err != nil {
		t.Fatalf("read reparse target: %v", err)
	}
	if !bytes.Equal(got, want) {
		t.Fatalf("reparse target = %q, want %q", got, want)
	}
}

func TestVerifyPrivateConfigPathIdentityRejectsWindowsReplacement(t *testing.T) {
	path := filepath.Join(t.TempDir(), "mcp.json")
	if err := os.WriteFile(path, []byte("original"), 0o600); err != nil {
		t.Fatalf("write original config: %v", err)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatalf("stat original config: %v", err)
	}
	if err := os.Rename(path, path+".replaced"); err != nil {
		t.Fatalf("move original config: %v", err)
	}
	if err := os.WriteFile(path, []byte("replacement"), 0o600); err != nil {
		t.Fatalf("write replacement config: %v", err)
	}
	if err := verifyPrivateConfigPathIdentity(path, info); err == nil || !strings.Contains(err.Error(), "replaced") {
		t.Fatalf("replacement identity error = %v, want replacement rejection", err)
	}
}
