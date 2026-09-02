package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"golang.org/x/sys/windows"
)

func TestTokenTelemetryOwnershipPathIsCaseInsensitiveOnWindows(t *testing.T) {
	home := t.TempDir()
	path := codexTokenTelemetryConfigPath(home, nil)
	statePath := filepath.Join(home, ".obstudio", tokenTelemetryStateFileName)
	if _, err := enableCodexTokenTelemetry(path, statePath, defaultTokenTelemetryEndpoint); err != nil {
		t.Fatalf("enable Codex telemetry: %v", err)
	}
	state, err := readTokenTelemetryOwnership(statePath)
	if err != nil {
		t.Fatal(err)
	}
	owned := state.Targets["codex"]
	owned.ConfigPath = strings.ToUpper(owned.ConfigPath)
	state.Targets["codex"] = owned
	if err := writeTokenTelemetryOwnership(statePath, state); err != nil {
		t.Fatal(err)
	}
	result, err := disableOwnedCodexTokenTelemetry(path, statePath)
	if err != nil || result.State != "disabled" {
		t.Fatalf("disable with differently cased ownership path = %+v, %v", result, err)
	}
}

func TestWriteAgentConfigCreatesProtectedCurrentUserDACLOnWindows(t *testing.T) {
	path := filepath.Join(t.TempDir(), "settings.json")
	if err := writeAgentConfig(path, []byte("{}\n")); err != nil {
		t.Fatalf("write new config: %v", err)
	}
	descriptor, dacl := readWindowsConfigDACL(t, path)
	control, _, err := descriptor.Control()
	if err != nil {
		t.Fatal(err)
	}
	if control&windows.SE_DACL_PROTECTED == 0 {
		t.Fatalf("new config DACL is not protected: %s", descriptor.String())
	}
	if dacl.AceCount != 1 {
		t.Fatalf("new config DACL ACE count = %d, want 1: %s", dacl.AceCount, descriptor.String())
	}
	user, err := windows.GetCurrentProcessToken().GetTokenUser()
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(descriptor.String(), user.User.Sid.String()) {
		t.Fatalf("new config DACL does not grant the current user: %s", descriptor.String())
	}
}

func TestWriteAgentConfigPreservesExistingDACLOnWindows(t *testing.T) {
	path := filepath.Join(t.TempDir(), "settings.json")
	if err := os.WriteFile(path, []byte("before\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	user, err := windows.GetCurrentProcessToken().GetTokenUser()
	if err != nil {
		t.Fatal(err)
	}
	systemSID, err := windows.CreateWellKnownSid(windows.WinLocalSystemSid)
	if err != nil {
		t.Fatal(err)
	}
	dacl, err := windows.ACLFromEntries([]windows.EXPLICIT_ACCESS{
		{
			AccessPermissions: windows.GENERIC_ALL,
			AccessMode:        windows.SET_ACCESS,
			Trustee: windows.TRUSTEE{
				TrusteeForm: windows.TRUSTEE_IS_SID, TrusteeType: windows.TRUSTEE_IS_USER,
				TrusteeValue: windows.TrusteeValueFromSID(user.User.Sid),
			},
		},
		{
			AccessPermissions: windows.FILE_GENERIC_READ,
			AccessMode:        windows.SET_ACCESS,
			Trustee: windows.TRUSTEE{
				TrusteeForm: windows.TRUSTEE_IS_SID, TrusteeType: windows.TRUSTEE_IS_USER,
				TrusteeValue: windows.TrusteeValueFromSID(systemSID),
			},
		},
	}, nil)
	if err != nil {
		t.Fatal(err)
	}
	if err := windows.SetNamedSecurityInfo(
		path,
		windows.SE_FILE_OBJECT,
		windows.DACL_SECURITY_INFORMATION|windows.PROTECTED_DACL_SECURITY_INFORMATION,
		nil,
		nil,
		dacl,
		nil,
	); err != nil {
		t.Fatal(err)
	}
	before, _ := readWindowsConfigDACL(t, path)
	if err := writeAgentConfig(path, []byte("after\n")); err != nil {
		t.Fatalf("replace existing config: %v", err)
	}
	after, _ := readWindowsConfigDACL(t, path)
	if before.String() != after.String() {
		t.Fatalf("existing config DACL changed across replacement:\nbefore: %s\nafter:  %s", before.String(), after.String())
	}
}

func TestWriteAgentConfigPreservesUnprotectedDACLOnWindows(t *testing.T) {
	path := filepath.Join(t.TempDir(), "settings.json")
	if err := os.WriteFile(path, []byte("before\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	descriptor, dacl := readWindowsConfigDACL(t, path)
	if err := windows.SetNamedSecurityInfo(
		path,
		windows.SE_FILE_OBJECT,
		windows.DACL_SECURITY_INFORMATION|windows.UNPROTECTED_DACL_SECURITY_INFORMATION,
		nil,
		nil,
		dacl,
		nil,
	); err != nil {
		t.Fatal(err)
	}
	before, _ := readWindowsConfigDACL(t, path)
	beforeControl, _, err := before.Control()
	if err != nil {
		t.Fatal(err)
	}
	if beforeControl&windows.SE_DACL_PROTECTED != 0 {
		t.Fatalf("test fixture DACL remained protected: %s (initial: %s)", before.String(), descriptor.String())
	}
	if err := writeAgentConfig(path, []byte("after\n")); err != nil {
		t.Fatalf("replace existing config: %v", err)
	}
	after, _ := readWindowsConfigDACL(t, path)
	afterControl, _, err := after.Control()
	if err != nil {
		t.Fatal(err)
	}
	if afterControl&windows.SE_DACL_PROTECTED != 0 || before.String() != after.String() {
		t.Fatalf("unprotected config DACL changed across replacement:\nbefore: %s\nafter:  %s", before.String(), after.String())
	}
}

func TestObstudioTokenTelemetryStateHardensExistingDACLOnWindows(t *testing.T) {
	for _, test := range []struct {
		name  string
		write func(string) error
	}{
		{
			name: "ownership",
			write: func(path string) error {
				return writeTokenTelemetryOwnership(path, tokenTelemetryOwnership{
					Version: tokenTelemetryStateVersion,
					Targets: map[string]tokenTelemetryTargetOwnership{
						"codex": {ConfigPath: `C:\\Users\\test\\.codex\\config.toml`},
					},
					RepositoryCorrelation: map[string]tokenTelemetryRepositoryCorrelation{},
				})
			},
		},
		{
			name: "recovery journal",
			write: func(path string) error {
				return writeTokenTelemetryPendingTransaction(path, tokenTelemetryPendingTransaction{
					Version:    tokenTelemetryPendingTransactionVersion,
					Target:     "codex",
					ConfigPath: `C:\\Users\\test\\.codex\\config.toml`,
				})
			},
		},
	} {
		t.Run(test.name, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "state.json")
			if err := os.WriteFile(path, []byte("before\n"), 0o600); err != nil {
				t.Fatal(err)
			}
			setSharedWindowsConfigDACL(t, path)
			if err := test.write(path); err != nil {
				t.Fatalf("replace Obstudio-owned file: %v", err)
			}

			descriptor, dacl := readWindowsConfigDACL(t, path)
			control, _, err := descriptor.Control()
			if err != nil {
				t.Fatal(err)
			}
			if control&windows.SE_DACL_PROTECTED == 0 || dacl.AceCount != 1 {
				t.Fatalf("Obstudio-owned file did not receive a protected current-user-only DACL: %s", descriptor.String())
			}
		})
	}
}

func setSharedWindowsConfigDACL(t *testing.T, path string) {
	t.Helper()
	user, err := windows.GetCurrentProcessToken().GetTokenUser()
	if err != nil {
		t.Fatal(err)
	}
	systemSID, err := windows.CreateWellKnownSid(windows.WinLocalSystemSid)
	if err != nil {
		t.Fatal(err)
	}
	dacl, err := windows.ACLFromEntries([]windows.EXPLICIT_ACCESS{
		{
			AccessPermissions: windows.GENERIC_ALL,
			AccessMode:        windows.SET_ACCESS,
			Trustee: windows.TRUSTEE{
				TrusteeForm: windows.TRUSTEE_IS_SID, TrusteeType: windows.TRUSTEE_IS_USER,
				TrusteeValue: windows.TrusteeValueFromSID(user.User.Sid),
			},
		},
		{
			AccessPermissions: windows.FILE_GENERIC_READ,
			AccessMode:        windows.SET_ACCESS,
			Trustee: windows.TRUSTEE{
				TrusteeForm: windows.TRUSTEE_IS_SID, TrusteeType: windows.TRUSTEE_IS_USER,
				TrusteeValue: windows.TrusteeValueFromSID(systemSID),
			},
		},
	}, nil)
	if err != nil {
		t.Fatal(err)
	}
	if err := windows.SetNamedSecurityInfo(
		path,
		windows.SE_FILE_OBJECT,
		windows.DACL_SECURITY_INFORMATION|windows.UNPROTECTED_DACL_SECURITY_INFORMATION,
		nil,
		nil,
		dacl,
		nil,
	); err != nil {
		t.Fatal(err)
	}
}

func readWindowsConfigDACL(t *testing.T, path string) (*windows.SECURITY_DESCRIPTOR, *windows.ACL) {
	t.Helper()
	descriptor, err := windows.GetNamedSecurityInfo(
		path,
		windows.SE_FILE_OBJECT,
		windows.DACL_SECURITY_INFORMATION,
	)
	if err != nil {
		t.Fatal(err)
	}
	if descriptor == nil {
		t.Fatal("Windows security descriptor is absent")
	}
	dacl, _, err := descriptor.DACL()
	if err != nil {
		t.Fatal(err)
	}
	return descriptor, dacl
}
