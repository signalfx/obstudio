package main

import (
	"os"
	"path/filepath"
	"strings"
)

// configManagerGateEnv turns on the Config Manager: ~/.obstudio/config.yaml,
// the `obstudio telemetry` command and the webview Config tab. It is off
// unless set to an on-value (1, true, yes, y, on).
const configManagerGateEnv = "OBSTUDIO_CONFIG_MANAGER"

// configManagerEnabled reports whether the Config Manager exists in this
// process. A variable present in the process environment wins, even when
// empty. Otherwise the env file (OBSTUDIO_ENV_FILE, else ~/.obstudio/env)
// decides; a missing or unusable file, or no home directory, is off.
//
// It is called from newRootCmd, before any env file is loaded, and from run,
// after loadConfiguredEnvFile. It is not cached, writes nothing, never exits
// and never logs. It computes the env file path itself because
// defaultEnvFilePath exits the process when there is no home directory.
//
// Shipping the feature: make the body `return true`.
func configManagerEnabled() bool {
	if value, ok := os.LookupEnv(configManagerGateEnv); ok {
		return envMapBool(map[string]string{configManagerGateEnv: value}, configManagerGateEnv)
	}
	path := strings.TrimSpace(os.Getenv("OBSTUDIO_ENV_FILE"))
	if path == "" {
		home, err := os.UserHomeDir()
		if err != nil || home == "" {
			return false
		}
		path = filepath.Join(home, ".obstudio", "env")
	}
	values, err := readEnvFile(path)
	if err != nil {
		return false
	}
	return envMapBool(values, configManagerGateEnv)
}
