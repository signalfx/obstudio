package main

import (
	"os"
	"path/filepath"
)

// configManagerGateEnv turns on the Config Manager: ~/.obstudio/config.yaml,
// the `obstudio telemetry` command and the webview Config tab. It is off
// unless set to an on-value (1, true, yes, y, on).
const configManagerGateEnv = "OBSTUDIO_CONFIG_MANAGER"

// configManagerEnabled reports whether the Config Manager exists in this
// process. A variable present in the process environment wins, even when
// empty. Otherwise the env file the loader would use decides: envFile (the
// --env-file value) if set, else OBSTUDIO_ENV_FILE, else ~/.obstudio/env. A
// missing or unusable file, or no home directory, is off.
//
// newRootCmd calls it with "" because cobra has not parsed --env-file yet.
// run calls it with the --env-file value after the env file is loaded. It is
// not cached, writes nothing, never exits and never logs; it does not call
// defaultEnvFilePath, which exits the process when there is no home
// directory.
//
// Shipping the feature: add `return true` at the top of this function, and
// delete the CONTRIBUTING.md paragraph and the off-by-default paragraph in
// docs/config-manager.md.
func configManagerEnabled(envFile string) bool {
	if value, ok := os.LookupEnv(configManagerGateEnv); ok {
		return envMapBool(map[string]string{configManagerGateEnv: value}, configManagerGateEnv)
	}
	path := explicitEnvFilePath(envFile)
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
