package main

import (
	"errors"
	"os"
	"path/filepath"
)

// userConfigYAMLPath is the one place the path of ~/.obstudio/config.yaml is
// built. It has no override, so a stray environment variable cannot redirect
// the usage-data opt-out.
func userConfigYAMLPath() (string, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}
	if home == "" || !filepath.IsAbs(home) {
		return "", errors.New("home directory is not an absolute path")
	}
	return filepath.Join(home, sharedObserverStateDirName, "config.yaml"), nil
}
