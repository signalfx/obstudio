//go:build windows

package main

import (
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"unsafe"

	"golang.org/x/sys/windows"
)

const (
	privateConfigTemporaryCreateAttempts = 100
	privateConfigFileRenameInformationEx = 65
)

type privateConfigWindowsRenameInformation struct {
	ReplaceIfExists uint32
	RootDirectory   windows.Handle
	FileNameLength  uint32
	FileName        [1]uint16
}

type windowsPrivateConfigTemporary struct {
	*os.File
	directoryHandle windows.Handle
	directoryInfo   windows.ByHandleFileInformation
}

func (temporary *windowsPrivateConfigTemporary) Close() error {
	if temporary == nil {
		return nil
	}
	var fileErr error
	if temporary.File != nil {
		fileErr = temporary.File.Close()
		temporary.File = nil
	}
	var directoryErr error
	if temporary.directoryHandle != windows.InvalidHandle {
		directoryErr = windows.CloseHandle(temporary.directoryHandle)
		temporary.directoryHandle = windows.InvalidHandle
	}
	return errors.Join(fileErr, directoryErr)
}

func validatePrivateConfigDirectory(path string) error {
	if err := rejectMCPConfigReparsePoints(path); err != nil {
		return err
	}
	handle, info, err := openMCPConfigWindowsObject(path, windows.FILE_READ_ATTRIBUTES)
	if err != nil {
		return err
	}
	defer windows.CloseHandle(handle)
	if info.FileAttributes&windows.FILE_ATTRIBUTE_REPARSE_POINT != 0 {
		return errors.New("private config parent is a reparse point")
	}
	if info.FileAttributes&windows.FILE_ATTRIBUTE_DIRECTORY == 0 {
		return errors.New("private config parent is not a directory")
	}
	return nil
}

func securePrivateConfigFile(path string) error {
	if err := rejectMCPConfigReparsePoints(path); err != nil {
		return err
	}
	handle, info, err := openMCPConfigWindowsObject(path, windows.READ_CONTROL|windows.WRITE_DAC|windows.FILE_READ_ATTRIBUTES)
	if err != nil {
		return err
	}
	defer windows.CloseHandle(handle)
	return secureMCPConfigWindowsHandle(handle, info)
}

func readPrivateConfigFile(path string) ([]byte, error) {
	if err := rejectMCPConfigReparsePoints(path); err != nil {
		return nil, err
	}
	handle, info, err := openMCPConfigWindowsObject(path, windows.GENERIC_READ|windows.READ_CONTROL|windows.FILE_READ_ATTRIBUTES)
	if err != nil {
		return nil, err
	}
	file := os.NewFile(uintptr(handle), path)
	if file == nil {
		_ = windows.CloseHandle(handle)
		return nil, errors.New("wrap private config descriptor")
	}
	defer file.Close()
	if info.FileAttributes&windows.FILE_ATTRIBUTE_REPARSE_POINT != 0 {
		return nil, errors.New("private config path is a reparse point")
	}
	if info.FileAttributes&windows.FILE_ATTRIBUTE_DIRECTORY != 0 {
		return nil, errors.New("private config path is not a regular file")
	}
	userSID, err := currentMCPConfigWindowsUserSID()
	if err != nil {
		return nil, fmt.Errorf("resolve current Windows user: %w", err)
	}
	if err := verifyMCPConfigOwnerOnlyDACL(handle, userSID); err != nil {
		return nil, err
	}
	return io.ReadAll(file)
}

func createPrivateConfigTemporary(directory, prefix string) (privateConfigTemporary, error) {
	if err := rejectMCPConfigReparsePoints(directory); err != nil {
		return nil, err
	}
	directoryHandle, directoryInfo, err := openMCPConfigWindowsObject(
		directory,
		windows.FILE_READ_ATTRIBUTES|windows.FILE_WRITE_DATA|windows.FILE_TRAVERSE,
	)
	if err != nil {
		return nil, err
	}
	if directoryInfo.FileAttributes&windows.FILE_ATTRIBUTE_REPARSE_POINT != 0 || directoryInfo.FileAttributes&windows.FILE_ATTRIBUTE_DIRECTORY == 0 {
		_ = windows.CloseHandle(directoryHandle)
		return nil, errors.New("private config parent is not a regular directory")
	}
	userSID, err := currentMCPConfigWindowsUserSID()
	if err != nil {
		_ = windows.CloseHandle(directoryHandle)
		return nil, fmt.Errorf("resolve current Windows user: %w", err)
	}
	userSIDString := userSID.String()
	if userSIDString == "" {
		_ = windows.CloseHandle(directoryHandle)
		return nil, errors.New("format current Windows user SID")
	}
	securityDescriptor, err := windows.SecurityDescriptorFromString(
		fmt.Sprintf("O:%sD:P(A;;GA;;;%s)", userSIDString, userSIDString),
	)
	if err != nil {
		_ = windows.CloseHandle(directoryHandle)
		return nil, fmt.Errorf("build owner-only Windows security descriptor: %w", err)
	}

	for range privateConfigTemporaryCreateAttempts {
		var suffix [16]byte
		if _, err := rand.Read(suffix[:]); err != nil {
			_ = windows.CloseHandle(directoryHandle)
			return nil, fmt.Errorf("generate private config temporary name: %w", err)
		}
		name := prefix + hex.EncodeToString(suffix[:])
		path := filepath.Join(directory, name)
		objectName, err := windows.NewNTUnicodeString(name)
		if err != nil {
			_ = windows.CloseHandle(directoryHandle)
			return nil, err
		}
		objectAttributes := windows.OBJECT_ATTRIBUTES{
			Length:             uint32(unsafe.Sizeof(windows.OBJECT_ATTRIBUTES{})),
			RootDirectory:      directoryHandle,
			ObjectName:         objectName,
			Attributes:         windows.OBJ_CASE_INSENSITIVE | windows.OBJ_DONT_REPARSE,
			SecurityDescriptor: securityDescriptor,
		}
		var handle windows.Handle
		var status windows.IO_STATUS_BLOCK
		allocationSize := int64(0)
		err = windows.NtCreateFile(
			&handle,
			windows.FILE_GENERIC_READ|windows.FILE_GENERIC_WRITE|windows.DELETE|windows.READ_CONTROL|windows.WRITE_DAC|windows.WRITE_OWNER,
			&objectAttributes,
			&status,
			&allocationSize,
			windows.FILE_ATTRIBUTE_NORMAL,
			windows.FILE_SHARE_READ|windows.FILE_SHARE_WRITE|windows.FILE_SHARE_DELETE,
			windows.FILE_CREATE,
			windows.FILE_NON_DIRECTORY_FILE|windows.FILE_OPEN_REPARSE_POINT|windows.FILE_SYNCHRONOUS_IO_NONALERT|windows.FILE_WRITE_THROUGH,
			0,
			0,
		)
		if err == windows.STATUS_OBJECT_NAME_COLLISION {
			continue
		}
		if err != nil {
			_ = windows.CloseHandle(directoryHandle)
			return nil, err
		}
		var info windows.ByHandleFileInformation
		if err := windows.GetFileInformationByHandle(handle, &info); err != nil {
			_ = windows.CloseHandle(handle)
			_ = windows.CloseHandle(directoryHandle)
			_ = os.Remove(path)
			return nil, err
		}
		if err := secureMCPConfigWindowsHandle(handle, info); err != nil {
			_ = windows.CloseHandle(handle)
			_ = windows.CloseHandle(directoryHandle)
			_ = os.Remove(path)
			return nil, err
		}
		file := os.NewFile(uintptr(handle), path)
		if file == nil {
			_ = windows.CloseHandle(handle)
			_ = windows.CloseHandle(directoryHandle)
			_ = os.Remove(path)
			return nil, errors.New("wrap secured Windows config handle")
		}
		return &windowsPrivateConfigTemporary{
			File:            file,
			directoryHandle: directoryHandle,
			directoryInfo:   directoryInfo,
		}, nil
	}
	_ = windows.CloseHandle(directoryHandle)
	return nil, errors.New("exhausted private config temporary file attempts")
}

func verifyPrivateConfigPathIdentity(path string, expected os.FileInfo) error {
	if expected == nil {
		return errors.New("expected private MCP config identity is missing")
	}
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
	return nil
}

func secureMCPConfigWindowsHandle(handle windows.Handle, info windows.ByHandleFileInformation) error {
	if info.FileAttributes&windows.FILE_ATTRIBUTE_REPARSE_POINT != 0 {
		return errors.New("private MCP config path is a reparse point")
	}
	if info.FileAttributes&windows.FILE_ATTRIBUTE_DIRECTORY != 0 {
		return errors.New("private MCP config path is not a regular file")
	}

	userSID, err := currentMCPConfigWindowsUserSID()
	if err != nil {
		return fmt.Errorf("resolve current Windows user: %w", err)
	}
	if err := verifyMCPConfigWindowsOwner(handle, userSID); err != nil {
		return err
	}
	acl, err := windows.ACLFromEntries([]windows.EXPLICIT_ACCESS{{
		AccessPermissions: windows.GENERIC_ALL,
		AccessMode:        windows.SET_ACCESS,
		Inheritance:       windows.NO_INHERITANCE,
		Trustee: windows.TRUSTEE{
			TrusteeForm:  windows.TRUSTEE_IS_SID,
			TrusteeType:  windows.TRUSTEE_IS_USER,
			TrusteeValue: windows.TrusteeValueFromSID(userSID),
		},
	}}, nil)
	if err != nil {
		return fmt.Errorf("build owner-only Windows ACL: %w", err)
	}
	if err := windows.SetSecurityInfo(
		handle,
		windows.SE_FILE_OBJECT,
		windows.DACL_SECURITY_INFORMATION|windows.PROTECTED_DACL_SECURITY_INFORMATION,
		nil,
		nil,
		acl,
		nil,
	); err != nil {
		return fmt.Errorf("set owner-only Windows ACL: %w", err)
	}
	if err := verifyMCPConfigOwnerOnlyDACL(handle, userSID); err != nil {
		return fmt.Errorf("verify owner-only Windows ACL: %w", err)
	}
	return nil
}

func publishPrivateConfigFile(temporary privateConfigTemporary, expected os.FileInfo, targetPath string) error {
	if temporary == nil {
		return errors.New("temporary private config is nil")
	}
	windowsTemporary, ok := temporary.(*windowsPrivateConfigTemporary)
	if !ok || windowsTemporary.File == nil || windowsTemporary.directoryHandle == windows.InvalidHandle {
		return errors.New("temporary private config has no secured Windows handles")
	}
	if expected == nil {
		return errors.New("expected private MCP config identity is missing")
	}
	temporaryDirectory, err := filepath.Abs(filepath.Dir(temporary.Name()))
	if err != nil {
		return err
	}
	targetDirectory, err := filepath.Abs(filepath.Dir(targetPath))
	if err != nil {
		return err
	}
	if !strings.EqualFold(filepath.Clean(temporaryDirectory), filepath.Clean(targetDirectory)) {
		return errors.New("private config temporary and target must share a directory")
	}
	if err := rejectMCPConfigReparsePoints(targetDirectory); err != nil {
		return err
	}
	if targetInfo, err := os.Lstat(targetPath); err == nil {
		if targetInfo.Mode()&os.ModeSymlink != 0 || !targetInfo.Mode().IsRegular() {
			return errors.New("private config target is not a regular file")
		}
		if err := rejectMCPConfigReparsePoints(targetPath); err != nil {
			return err
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return err
	}

	openedInfo, err := temporary.Stat()
	if err != nil {
		return err
	}
	if !os.SameFile(openedInfo, expected) {
		return errors.New("private MCP config descriptor was replaced")
	}
	temporaryHandle := windows.Handle(windowsTemporary.Fd())
	var handleInfo windows.ByHandleFileInformation
	if err := windows.GetFileInformationByHandle(temporaryHandle, &handleInfo); err != nil {
		return err
	}
	userSID, err := currentMCPConfigWindowsUserSID()
	if err != nil {
		return fmt.Errorf("resolve current Windows user: %w", err)
	}
	if err := verifyMCPConfigOwnerOnlyDACL(temporaryHandle, userSID); err != nil {
		return fmt.Errorf("verify temporary Windows config ACL before publishing: %w", err)
	}
	if handleInfo.FileAttributes&windows.FILE_ATTRIBUTE_REPARSE_POINT != 0 || handleInfo.FileAttributes&windows.FILE_ATTRIBUTE_DIRECTORY != 0 {
		return errors.New("private MCP config descriptor is not a regular file")
	}

	directoryHandle, directoryInfo, err := openMCPConfigWindowsObject(
		targetDirectory,
		windows.FILE_READ_ATTRIBUTES|windows.FILE_TRAVERSE,
	)
	if err != nil {
		return err
	}
	defer windows.CloseHandle(directoryHandle)
	if directoryInfo.FileAttributes&windows.FILE_ATTRIBUTE_REPARSE_POINT != 0 || directoryInfo.FileAttributes&windows.FILE_ATTRIBUTE_DIRECTORY == 0 {
		return errors.New("private config parent is not a regular directory")
	}
	if !sameMCPConfigWindowsObject(directoryInfo, windowsTemporary.directoryInfo) {
		return errors.New("private config parent changed before publishing")
	}

	targetName, err := windows.UTF16FromString(filepath.Base(targetPath))
	if err != nil {
		return err
	}
	fileNameBytes := (len(targetName) - 1) * 2
	var template privateConfigWindowsRenameInformation
	bufferSize := int(unsafe.Offsetof(template.FileName)) + fileNameBytes
	buffer := make([]byte, bufferSize)
	rename := (*privateConfigWindowsRenameInformation)(unsafe.Pointer(&buffer[0]))
	rename.ReplaceIfExists = windows.FILE_RENAME_REPLACE_IF_EXISTS | windows.FILE_RENAME_POSIX_SEMANTICS
	rename.RootDirectory = windowsTemporary.directoryHandle
	rename.FileNameLength = uint32(fileNameBytes)
	copy(unsafe.Slice(&rename.FileName[0], len(targetName)-1), targetName[:len(targetName)-1])

	var status windows.IO_STATUS_BLOCK
	if err := windows.NtSetInformationFile(
		temporaryHandle,
		&status,
		&buffer[0],
		uint32(bufferSize),
		privateConfigFileRenameInformationEx,
	); err != nil {
		rename.ReplaceIfExists = windows.FILE_RENAME_REPLACE_IF_EXISTS
		if fallbackErr := windows.NtSetInformationFile(
			temporaryHandle,
			&status,
			&buffer[0],
			uint32(bufferSize),
			windows.FileRenameInformation,
		); fallbackErr != nil {
			return fallbackErr
		}
	}
	if err := windows.FlushFileBuffers(temporaryHandle); err != nil {
		return fmt.Errorf("flush published private config: %w", err)
	}
	publishedInfo, err := os.Stat(targetPath)
	if err != nil {
		return fmt.Errorf("stat published private config: %w", err)
	}
	if !os.SameFile(publishedInfo, expected) {
		return errors.New("published private MCP config identity changed")
	}
	return nil
}

func currentMCPConfigWindowsUserSID() (*windows.SID, error) {
	user, err := windows.GetCurrentProcessToken().GetTokenUser()
	if err != nil {
		return nil, err
	}
	return user.User.Sid.Copy()
}

func verifyMCPConfigWindowsOwner(handle windows.Handle, userSID *windows.SID) error {
	descriptor, err := windows.GetSecurityInfo(handle, windows.SE_FILE_OBJECT, windows.OWNER_SECURITY_INFORMATION)
	if err != nil {
		return fmt.Errorf("read Windows config owner: %w", err)
	}
	if descriptor == nil {
		return errors.New("Windows config has no security descriptor")
	}
	owner, _, err := descriptor.Owner()
	if err != nil {
		return fmt.Errorf("read Windows config owner SID: %w", err)
	}
	if owner == nil || !owner.Equals(userSID) {
		return errors.New("private MCP config is not owned by the current user")
	}
	return nil
}

func verifyMCPConfigOwnerOnlyDACL(handle windows.Handle, userSID *windows.SID) error {
	descriptor, err := windows.GetSecurityInfo(
		handle,
		windows.SE_FILE_OBJECT,
		windows.OWNER_SECURITY_INFORMATION|windows.DACL_SECURITY_INFORMATION,
	)
	if err != nil {
		return err
	}
	if descriptor == nil {
		return errors.New("Windows config has no security descriptor")
	}
	owner, _, err := descriptor.Owner()
	if err != nil {
		return err
	}
	if owner == nil || !owner.Equals(userSID) {
		return errors.New("Windows config owner changed while securing it")
	}
	control, _, err := descriptor.Control()
	if err != nil {
		return err
	}
	if control&windows.SE_DACL_PROTECTED == 0 {
		return errors.New("Windows config DACL still inherits access")
	}
	dacl, _, err := descriptor.DACL()
	if err != nil {
		return err
	}
	if dacl == nil || dacl.AceCount != 1 {
		return errors.New("Windows config DACL is not owner-only")
	}
	var ace *windows.ACCESS_ALLOWED_ACE
	if err := windows.GetAce(dacl, 0, &ace); err != nil {
		return err
	}
	if ace == nil || ace.Header.AceType != windows.ACCESS_ALLOWED_ACE_TYPE {
		return errors.New("Windows config DACL contains a non-allow entry")
	}
	aceSID := (*windows.SID)(unsafe.Pointer(&ace.SidStart))
	if !aceSID.IsValid() || !aceSID.Equals(userSID) {
		return errors.New("Windows config DACL grants access to another principal")
	}
	if !mcpConfigWindowsFullControlMask(ace.Mask) {
		return errors.New("Windows config DACL does not grant the owner full control")
	}
	return nil
}

func mcpConfigWindowsFullControlMask(mask windows.ACCESS_MASK) bool {
	if mask&windows.GENERIC_ALL == windows.GENERIC_ALL {
		return true
	}
	required := windows.ACCESS_MASK(
		windows.FILE_READ_DATA |
			windows.FILE_WRITE_DATA |
			windows.FILE_APPEND_DATA |
			windows.FILE_READ_EA |
			windows.FILE_WRITE_EA |
			windows.FILE_EXECUTE |
			windows.FILE_READ_ATTRIBUTES |
			windows.FILE_WRITE_ATTRIBUTES |
			windows.DELETE |
			windows.READ_CONTROL |
			windows.WRITE_DAC |
			windows.WRITE_OWNER |
			windows.SYNCHRONIZE,
	)
	return mask&required == required
}

func sameMCPConfigWindowsObject(left, right windows.ByHandleFileInformation) bool {
	return left.VolumeSerialNumber == right.VolumeSerialNumber &&
		left.FileIndexHigh == right.FileIndexHigh &&
		left.FileIndexLow == right.FileIndexLow
}

func rejectMCPConfigReparsePoints(path string) error {
	cleaned, err := filepath.Abs(path)
	if err != nil {
		return fmt.Errorf("resolve private MCP config path: %w", err)
	}
	cleaned = filepath.Clean(cleaned)
	volume := filepath.VolumeName(cleaned)
	if volume == "" {
		return errors.New("private MCP config path has no Windows volume")
	}
	if strings.HasPrefix(volume, `\\`) {
		return errors.New("private MCP config path cannot use a network share")
	}
	current := volume + string(filepath.Separator)
	parts := strings.FieldsFunc(strings.TrimPrefix(cleaned, current), func(character rune) bool {
		return character == '\\' || character == '/'
	})
	for _, part := range parts {
		current = filepath.Join(current, part)
		handle, info, err := openMCPConfigWindowsObject(current, windows.FILE_READ_ATTRIBUTES)
		if err != nil {
			return fmt.Errorf("inspect private MCP config path component: %w", err)
		}
		closeErr := windows.CloseHandle(handle)
		if closeErr != nil {
			return fmt.Errorf("close private MCP config path component: %w", closeErr)
		}
		if info.FileAttributes&windows.FILE_ATTRIBUTE_REPARSE_POINT != 0 {
			return fmt.Errorf("private MCP config path component %q is a reparse point", current)
		}
	}
	return nil
}

func openMCPConfigWindowsObject(path string, access uint32) (windows.Handle, windows.ByHandleFileInformation, error) {
	var info windows.ByHandleFileInformation
	pathPointer, err := windows.UTF16PtrFromString(path)
	if err != nil {
		return windows.InvalidHandle, info, err
	}
	handle, err := windows.CreateFile(
		pathPointer,
		access,
		windows.FILE_SHARE_READ|windows.FILE_SHARE_WRITE|windows.FILE_SHARE_DELETE,
		nil,
		windows.OPEN_EXISTING,
		windows.FILE_FLAG_OPEN_REPARSE_POINT|windows.FILE_FLAG_BACKUP_SEMANTICS,
		0,
	)
	if err != nil {
		return windows.InvalidHandle, info, err
	}
	if err := windows.GetFileInformationByHandle(handle, &info); err != nil {
		_ = windows.CloseHandle(handle)
		return windows.InvalidHandle, info, err
	}
	return handle, info, nil
}
