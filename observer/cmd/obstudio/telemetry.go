package main

import (
	"errors"
	"fmt"
	"io/fs"

	"github.com/spf13/cobra"

	"github.com/signalfx/obstudio/observer/internal/userconfig"
)

// telemetryLongL2 and telemetryLongL3 follow the setting's Description in
// the group's Long.
const (
	telemetryLongL2 = "This setting can also be managed in ~/.obstudio/config.yaml (telemetry.enabled). A running Splunk Observability Studio picks up a change without a restart."
	telemetryLongL3 = `To manage whether or not Splunk Observability Studio receives token telemetry from your Codex or Claude Code instances, use "obstudio token-telemetry".`
)

// telemetryLong is the setting's Description, read from the definitions,
// then the two fixed lines.
func telemetryLong() string {
	var d string
	for _, def := range userconfig.Definitions() {
		if def.Path == userconfig.TelemetryEnabled.Path() {
			d = def.Description
		}
	}
	return d + "\n\n" + telemetryLongL2 + "\n\n" + telemetryLongL3
}

// telemetryWrite is replaced in tests to simulate a write that does not land.
var telemetryWrite = userconfig.Write[bool]

func newTelemetryCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "telemetry",
		Short: "Manage the anonymous usage data Splunk Observability Studio sends about itself",
		Long:  telemetryLong(),
	}
	cmd.AddCommand(
		newTelemetrySetCommand("enable", "Allow Cisco to collect anonymous usage data", true),
		newTelemetrySetCommand("disable", "Stop Cisco collecting anonymous usage data", false),
		newTelemetryStatusCommand(),
	)
	return cmd
}

func isTelemetryDiagnostic(d userconfig.Diagnostic) bool {
	return (d.Key == userconfig.TelemetryEnabled.Path() || d.Key == userconfig.SectionTelemetry.Path()) &&
		(d.Kind == userconfig.DiagAbsent || d.Kind == userconfig.DiagInvalid)
}

func telemetryDiagnostics(diags []userconfig.Diagnostic) []userconfig.Diagnostic {
	var out []userconfig.Diagnostic
	for _, d := range diags {
		if isTelemetryDiagnostic(d) {
			out = append(out, d)
		}
	}
	return out
}

func holdsLiteral(s userconfig.Snapshot, diags []userconfig.Diagnostic, err error, v bool) bool {
	return err == nil && s.Telemetry.Enabled == v && len(telemetryDiagnostics(diags)) == 0
}

func enabledWord(enabled bool) string {
	if enabled {
		return "enabled"
	}
	return "disabled"
}

func brokenFileError(verb, path string, err error) error {
	msg := fmt.Sprintf("cannot %s anonymous usage data: %s: %v\nFix the file, or delete it and run this command again.", verb, path, err)
	if errors.Is(err, userconfig.ErrSyntax) {
		msg += "\nUntil it is fixed, a running Splunk Observability Studio may keep using its last valid settings."
	}
	return errors.New(msg)
}

func isBrokenFile(err error) bool {
	return errors.Is(err, userconfig.ErrSyntax) || errors.Is(err, userconfig.ErrNotMapping)
}

func newTelemetrySetCommand(verb, short string, want bool) *cobra.Command {
	return &cobra.Command{
		Use:   verb,
		Short: short,
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			path, err := userConfigYAMLPath()
			if err != nil {
				return fmt.Errorf("cannot %s anonymous usage data: %w", verb, err)
			}
			failed := func(err error) error {
				if isBrokenFile(err) {
					return brokenFileError(verb, path, err)
				}
				return fmt.Errorf("cannot %s anonymous usage data: %s: %w", verb, path, err)
			}
			r, err := userconfig.Open(path)
			if err != nil {
				return failed(err)
			}
			if holdsLiteral(r.Snapshot, r.Diagnostics, nil, want) {
				fmt.Fprintf(cmd.OutOrStdout(), "Anonymous usage data is already %s.\nConfig: %s\n", enabledWord(r.Snapshot.Telemetry.Enabled), path)
				return nil
			}
			if err := telemetryWrite(path, userconfig.TelemetryEnabled, want); err != nil {
				return failed(err)
			}
			s, diags, err := userconfig.Load(path)
			if !holdsLiteral(s, diags, err, want) {
				msg := fmt.Sprintf("cannot confirm anonymous usage data is %sd: %s", verb, path)
				if err != nil {
					msg += ": " + err.Error()
				}
				return errors.New(msg)
			}
			fmt.Fprintf(cmd.OutOrStdout(), "Anonymous usage data is now %s.\nConfig: %s\n", enabledWord(s.Telemetry.Enabled), path)
			return nil
		},
	}
}

const runningObserverNote = "Note: A running Splunk Observability Studio may still be using its last valid settings."

func newTelemetryStatusCommand() *cobra.Command {
	return &cobra.Command{
		Use:   "status",
		Short: "Show whether anonymous usage data will be collected",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			path, err := userConfigYAMLPath()
			if err != nil {
				return fmt.Errorf("cannot read anonymous usage data setting: %w", err)
			}
			s, diags, err := userconfig.Load(path)
			lines := []string{"", "Config: " + path}
			switch {
			case err == nil:
				lines[0] = "Anonymous usage data: " + enabledWord(s.Telemetry.Enabled)
				for _, d := range telemetryDiagnostics(diags) {
					lines = append(lines, "Reason: "+telemetryReason(d))
				}
			case errors.Is(err, fs.ErrNotExist):
				lines[0] = "Anonymous usage data: enabled"
				lines = append(lines,
					"Reason: the file does not exist yet; it is created with telemetry.enabled: true the next time Splunk Observability Studio starts.",
					runningObserverNote)
			case errors.Is(err, userconfig.ErrSyntax):
				lines[0] = "Anonymous usage data: disabled"
				lines = append(lines, "Reason: the file is not valid YAML: "+err.Error(), runningObserverNote)
			default:
				lines[0] = "Anonymous usage data: disabled"
				lines = append(lines, "Reason: the file cannot be read: "+err.Error(), runningObserverNote)
			}
			out := cmd.OutOrStdout()
			for _, l := range lines {
				fmt.Fprintln(out, l)
			}
			return nil
		},
	}
}

func telemetryReason(d userconfig.Diagnostic) string {
	tail := fmt.Sprintf(", so %s is treated as %t.", userconfig.TelemetryEnabled.Path(), userconfig.FailSafeSettings().Telemetry.Enabled)
	if d.Kind == userconfig.DiagAbsent {
		return d.Key + " is not set" + tail
	}
	if d.Line > 0 {
		return fmt.Sprintf("%s has an invalid value at line %d%s", d.Key, d.Line, tail)
	}
	return d.Key + " has an invalid value" + tail
}
