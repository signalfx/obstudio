//go:build !windows

package main

func prepareConfigTempFileSecurity(_, _ string, _, _ bool) error {
	return nil
}
