//go:build windows

package main

import (
	"fmt"

	"golang.org/x/sys/windows"
)

func prepareConfigTempFileSecurity(tempPath, targetPath string, targetExists, preserveExistingSecurity bool) error {
	securityInformation := windows.SECURITY_INFORMATION(windows.DACL_SECURITY_INFORMATION)
	var dacl *windows.ACL
	if targetExists && preserveExistingSecurity {
		descriptor, err := windows.GetNamedSecurityInfo(
			targetPath,
			windows.SE_FILE_OBJECT,
			windows.DACL_SECURITY_INFORMATION,
		)
		if err != nil {
			return fmt.Errorf("read existing DACL: %w", err)
		}
		if descriptor == nil {
			return fmt.Errorf("read existing DACL: security descriptor is absent")
		}
		dacl, _, err = descriptor.DACL()
		if err != nil {
			return fmt.Errorf("read existing DACL: %w", err)
		}
		control, _, err := descriptor.Control()
		if err != nil {
			return fmt.Errorf("read existing DACL protection: %w", err)
		}
		if control&windows.SE_DACL_PROTECTED != 0 {
			securityInformation |= windows.PROTECTED_DACL_SECURITY_INFORMATION
		} else {
			securityInformation |= windows.UNPROTECTED_DACL_SECURITY_INFORMATION
		}
	} else {
		user, err := windows.GetCurrentProcessToken().GetTokenUser()
		if err != nil {
			return fmt.Errorf("read current user SID: %w", err)
		}
		dacl, err = windows.ACLFromEntries([]windows.EXPLICIT_ACCESS{{
			AccessPermissions: windows.GENERIC_ALL,
			AccessMode:        windows.SET_ACCESS,
			Inheritance:       windows.NO_INHERITANCE,
			Trustee: windows.TRUSTEE{
				TrusteeForm:  windows.TRUSTEE_IS_SID,
				TrusteeType:  windows.TRUSTEE_IS_USER,
				TrusteeValue: windows.TrusteeValueFromSID(user.User.Sid),
			},
		}}, nil)
		if err != nil {
			return fmt.Errorf("build current-user-only DACL: %w", err)
		}
		securityInformation |= windows.PROTECTED_DACL_SECURITY_INFORMATION
	}
	if err := windows.SetNamedSecurityInfo(
		tempPath,
		windows.SE_FILE_OBJECT,
		securityInformation,
		nil,
		nil,
		dacl,
		nil,
	); err != nil {
		return fmt.Errorf("apply DACL: %w", err)
	}
	return nil
}
