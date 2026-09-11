package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
)

const tokenTelemetryPendingTransactionVersion = 1

type tokenTelemetryConfigSnapshot struct {
	Data   []byte `json:"data,omitempty"`
	Exists bool   `json:"exists"`
}

type tokenTelemetryPendingTransaction struct {
	AfterConfig                 tokenTelemetryConfigSnapshot         `json:"afterConfig"`
	AfterRepositoryCorrelation  *tokenTelemetryRepositoryCorrelation `json:"afterRepositoryCorrelation,omitempty"`
	AfterTarget                 *tokenTelemetryTargetOwnership       `json:"afterTarget,omitempty"`
	BeforeConfig                tokenTelemetryConfigSnapshot         `json:"beforeConfig"`
	BeforeRepositoryCorrelation *tokenTelemetryRepositoryCorrelation `json:"beforeRepositoryCorrelation,omitempty"`
	BeforeTarget                *tokenTelemetryTargetOwnership       `json:"beforeTarget,omitempty"`
	ConfigPath                  string                               `json:"configPath"`
	Target                      string                               `json:"target"`
	Version                     int                                  `json:"version"`
}

type tokenTelemetryConfigSnapshotReader func(string) (tokenTelemetryConfigSnapshot, error)

func publishTokenTelemetryConfigTransaction(
	statePath, target, configPath string,
	beforeConfig, afterConfig tokenTelemetryConfigSnapshot,
	beforeOwnership, afterOwnership tokenTelemetryOwnership,
	writeOwnership tokenTelemetryOwnershipWriter,
) error {
	return publishTokenTelemetryConfigTransactionWithSnapshotReader(
		statePath,
		target,
		configPath,
		beforeConfig,
		afterConfig,
		beforeOwnership,
		afterOwnership,
		writeOwnership,
		readTokenTelemetryConfigSnapshot,
	)
}

func publishTokenTelemetryConfigTransactionWithSnapshotReader(
	statePath, target, configPath string,
	beforeConfig, afterConfig tokenTelemetryConfigSnapshot,
	beforeOwnership, afterOwnership tokenTelemetryOwnership,
	writeOwnership tokenTelemetryOwnershipWriter,
	readConfig tokenTelemetryConfigSnapshotReader,
) error {
	if tokenTelemetryConfigSnapshotsEqual(beforeConfig, afterConfig) {
		if err := requireUnchangedTokenTelemetryConfig(configPath, beforeConfig, readConfig); err != nil {
			return err
		}
		return writeOwnership(statePath, afterOwnership)
	}
	pendingPath := tokenTelemetryPendingTransactionPath(statePath, target)
	if _, err := os.Stat(pendingPath); err == nil {
		return fmt.Errorf("pending token telemetry transaction %q must be recovered before changing %s", pendingPath, target)
	} else if !errors.Is(err, os.ErrNotExist) {
		return fmt.Errorf("inspect pending token telemetry transaction %q: %w", pendingPath, err)
	}
	pending := tokenTelemetryPendingTransaction{
		AfterConfig:                 afterConfig,
		AfterRepositoryCorrelation:  tokenTelemetryRepositoryCorrelationSnapshot(afterOwnership, target),
		AfterTarget:                 tokenTelemetryTargetOwnershipSnapshot(afterOwnership, target),
		BeforeConfig:                beforeConfig,
		BeforeRepositoryCorrelation: tokenTelemetryRepositoryCorrelationSnapshot(beforeOwnership, target),
		BeforeTarget:                tokenTelemetryTargetOwnershipSnapshot(beforeOwnership, target),
		ConfigPath:                  configPath,
		Target:                      target,
		Version:                     tokenTelemetryPendingTransactionVersion,
	}
	if err := writeTokenTelemetryPendingTransaction(pendingPath, pending); err != nil {
		return err
	}
	if err := requireUnchangedTokenTelemetryConfig(configPath, beforeConfig, readConfig); err != nil {
		return errors.Join(err, removeTokenTelemetryPendingTransaction(pendingPath))
	}
	if err := applyTokenTelemetryConfigSnapshot(configPath, afterConfig); err != nil {
		return errors.Join(err, removeTokenTelemetryPendingTransaction(pendingPath))
	}
	if err := writeOwnership(statePath, afterOwnership); err != nil {
		configErr := restoreTokenTelemetryConfigIfUnchanged(
			configPath,
			beforeConfig,
			afterConfig,
			readConfig,
		)
		stateErr := applyTokenTelemetryOwnershipDelta(
			statePath,
			target,
			pending.BeforeTarget,
			pending.BeforeRepositoryCorrelation,
		)
		var pendingErr error
		if configErr == nil && stateErr == nil {
			pendingErr = removeTokenTelemetryPendingTransaction(pendingPath)
		}
		return errors.Join(err, configErr, stateErr, pendingErr)
	}
	return removeTokenTelemetryPendingTransaction(pendingPath)
}

func requireUnchangedTokenTelemetryConfig(
	path string,
	expected tokenTelemetryConfigSnapshot,
	readConfig tokenTelemetryConfigSnapshotReader,
) error {
	current, err := readConfig(path)
	if err != nil {
		return err
	}
	if tokenTelemetryConfigSnapshotsEqual(current, expected) {
		return nil
	}
	return fmt.Errorf(
		"provider config %q changed before token telemetry publish; current content was preserved",
		path,
	)
}

func restoreTokenTelemetryConfigIfUnchanged(
	path string,
	beforeConfig, afterConfig tokenTelemetryConfigSnapshot,
	readConfig tokenTelemetryConfigSnapshotReader,
) error {
	current, err := readConfig(path)
	if err != nil {
		return err
	}
	switch {
	case tokenTelemetryConfigSnapshotsEqual(current, beforeConfig):
		return nil
	case tokenTelemetryConfigSnapshotsEqual(current, afterConfig):
		return applyTokenTelemetryConfigSnapshot(path, beforeConfig)
	default:
		return fmt.Errorf(
			"provider config %q changed after token telemetry publish; rollback preserved current content and retained the pending transaction",
			path,
		)
	}
}

func recoverPendingTokenTelemetryTransaction(statePath, target string) error {
	pendingPath := tokenTelemetryPendingTransactionPath(statePath, target)
	pending, exists, err := readTokenTelemetryPendingTransaction(pendingPath)
	if err != nil || !exists {
		return err
	}
	if pending.Target != target {
		return fmt.Errorf(
			"pending token telemetry transaction %q belongs to %s, not %s",
			pendingPath,
			pending.Target,
			target,
		)
	}
	current, err := readTokenTelemetryConfigSnapshot(pending.ConfigPath)
	if err != nil {
		return err
	}
	var owned *tokenTelemetryTargetOwnership
	var correlation *tokenTelemetryRepositoryCorrelation
	switch {
	case tokenTelemetryConfigSnapshotsEqual(current, pending.AfterConfig):
		owned = pending.AfterTarget
		correlation = pending.AfterRepositoryCorrelation
	case tokenTelemetryConfigSnapshotsEqual(current, pending.BeforeConfig):
		owned = pending.BeforeTarget
		correlation = pending.BeforeRepositoryCorrelation
	default:
		return fmt.Errorf(
			"%s config %q changed while token telemetry transaction %q was pending; no files were changed",
			pending.Target,
			pending.ConfigPath,
			pendingPath,
		)
	}
	if err := applyTokenTelemetryOwnershipDelta(statePath, target, owned, correlation); err != nil {
		return fmt.Errorf("recover token telemetry ownership state: %w", err)
	}
	return removeTokenTelemetryPendingTransaction(pendingPath)
}

func readTokenTelemetryConfigSnapshot(path string) (tokenTelemetryConfigSnapshot, error) {
	data, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return tokenTelemetryConfigSnapshot{}, nil
	}
	if err != nil {
		return tokenTelemetryConfigSnapshot{}, fmt.Errorf("read provider config %q: %w", path, err)
	}
	return tokenTelemetryConfigSnapshot{Data: data, Exists: true}, nil
}

func applyTokenTelemetryConfigSnapshot(path string, snapshot tokenTelemetryConfigSnapshot) error {
	if !snapshot.Exists {
		if err := os.Remove(path); err != nil && !errors.Is(err, os.ErrNotExist) {
			return fmt.Errorf("remove provider config %q: %w", path, err)
		}
		return nil
	}
	return writeAgentConfig(path, snapshot.Data)
}

func tokenTelemetryConfigSnapshotsEqual(left, right tokenTelemetryConfigSnapshot) bool {
	return left.Exists == right.Exists && bytes.Equal(left.Data, right.Data)
}

func tokenTelemetryPendingTransactionPath(statePath, target string) string {
	return statePath + "." + target + ".pending"
}

func tokenTelemetryTargetOwnershipSnapshot(state tokenTelemetryOwnership, target string) *tokenTelemetryTargetOwnership {
	owned, ok := state.Targets[target]
	if !ok {
		return nil
	}
	owned.Env = cloneStringMap(owned.Env)
	owned.Settings = cloneStringMap(owned.Settings)
	owned.TableSettings = cloneStringMap(owned.TableSettings)
	return &owned
}

func tokenTelemetryRepositoryCorrelationSnapshot(state tokenTelemetryOwnership, target string) *tokenTelemetryRepositoryCorrelation {
	correlation, ok := state.RepositoryCorrelation[target]
	if !ok {
		return nil
	}
	return &correlation
}

func applyTokenTelemetryOwnershipDelta(
	statePath, target string,
	owned *tokenTelemetryTargetOwnership,
	correlation *tokenTelemetryRepositoryCorrelation,
) error {
	state, err := readTokenTelemetryOwnership(statePath)
	if err != nil {
		return err
	}
	if owned == nil {
		delete(state.Targets, target)
	} else {
		cloned := *owned
		cloned.Env = cloneStringMap(owned.Env)
		cloned.Settings = cloneStringMap(owned.Settings)
		cloned.TableSettings = cloneStringMap(owned.TableSettings)
		state.Targets[target] = cloned
	}
	if correlation == nil {
		delete(state.RepositoryCorrelation, target)
	} else {
		state.RepositoryCorrelation[target] = *correlation
	}
	return writeTokenTelemetryOwnership(statePath, state)
}

func writeTokenTelemetryPendingTransaction(path string, pending tokenTelemetryPendingTransaction) error {
	data, err := json.MarshalIndent(pending, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal pending token telemetry transaction %q: %w", path, err)
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return fmt.Errorf("create pending token telemetry transaction directory: %w", err)
	}
	if err := writeConfigFile(path, append(data, '\n'), 0o600, false); err != nil {
		return fmt.Errorf("write pending token telemetry transaction %q: %w", path, err)
	}
	return nil
}

func readTokenTelemetryPendingTransaction(path string) (tokenTelemetryPendingTransaction, bool, error) {
	data, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return tokenTelemetryPendingTransaction{}, false, nil
	}
	if err != nil {
		return tokenTelemetryPendingTransaction{}, false, fmt.Errorf("read pending token telemetry transaction %q: %w", path, err)
	}
	if err := validateJSONUniqueObjectKeys(data); err != nil {
		return tokenTelemetryPendingTransaction{}, false, fmt.Errorf("parse pending token telemetry transaction %q: %w", path, err)
	}
	var pending tokenTelemetryPendingTransaction
	if err := json.Unmarshal(data, &pending); err != nil {
		return tokenTelemetryPendingTransaction{}, false, fmt.Errorf("parse pending token telemetry transaction %q: %w", path, err)
	}
	if pending.Version != tokenTelemetryPendingTransactionVersion {
		return tokenTelemetryPendingTransaction{}, false, fmt.Errorf(
			"pending token telemetry transaction %q uses unsupported version %d",
			path,
			pending.Version,
		)
	}
	if pending.ConfigPath == "" || pending.Target == "" {
		return tokenTelemetryPendingTransaction{}, false, fmt.Errorf("pending token telemetry transaction %q is incomplete", path)
	}
	return pending, true, nil
}

func removeTokenTelemetryPendingTransaction(path string) error {
	if err := os.Remove(path); err != nil && !errors.Is(err, os.ErrNotExist) {
		return fmt.Errorf("remove pending token telemetry transaction %q: %w", path, err)
	}
	return nil
}

func cloneTokenTelemetryOwnership(state tokenTelemetryOwnership) tokenTelemetryOwnership {
	cloned := tokenTelemetryOwnership{
		RepositoryCorrelation: make(map[string]tokenTelemetryRepositoryCorrelation, len(state.RepositoryCorrelation)),
		Targets:               make(map[string]tokenTelemetryTargetOwnership, len(state.Targets)),
		Version:               state.Version,
	}
	for target, correlation := range state.RepositoryCorrelation {
		cloned.RepositoryCorrelation[target] = correlation
	}
	for target, owned := range state.Targets {
		owned.Env = cloneStringMap(owned.Env)
		owned.Settings = cloneStringMap(owned.Settings)
		owned.TableSettings = cloneStringMap(owned.TableSettings)
		cloned.Targets[target] = owned
	}
	return cloned
}

func cloneStringMap(values map[string]string) map[string]string {
	if values == nil {
		return nil
	}
	cloned := make(map[string]string, len(values))
	for key, value := range values {
		cloned[key] = value
	}
	return cloned
}
