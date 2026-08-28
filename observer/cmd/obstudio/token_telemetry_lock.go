package main

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
)

func withTokenTelemetryStateTransaction(
	statePath, target string,
	operation func() (tokenTelemetryResult, error),
) (result tokenTelemetryResult, err error) {
	err = withTokenTelemetryStateLock(statePath, func() error {
		if recoverErr := recoverPendingTokenTelemetryTransaction(statePath, target); recoverErr != nil {
			return recoverErr
		}
		result, err = operation()
		return err
	})
	return result, err
}

func withTokenTelemetryStateLock(statePath string, operation func() error) (err error) {
	if err := os.MkdirAll(filepath.Dir(statePath), 0o700); err != nil {
		return fmt.Errorf("create token telemetry state directory: %w", err)
	}
	lockPath := statePath + ".lock"
	lockFile, err := os.OpenFile(lockPath, os.O_CREATE|os.O_RDWR, 0o600)
	if err != nil {
		return fmt.Errorf("open token telemetry state lock %q: %w", lockPath, err)
	}
	unlock, err := lockTokenTelemetryFile(lockFile)
	if err != nil {
		return errors.Join(
			fmt.Errorf("lock token telemetry state %q: %w", statePath, err),
			lockFile.Close(),
		)
	}
	defer func() {
		err = errors.Join(err, unlock(), lockFile.Close())
	}()
	return operation()
}
