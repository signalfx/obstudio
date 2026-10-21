package main

import (
	"errors"

	"github.com/signalfx/obstudio/observer/internal/configmanager"
	"github.com/signalfx/obstudio/observer/internal/configmanager/configmanagertest"
)

// newConfigManager returns the ConfigManager behind the /api/config routes.
// TODO: replace the in-memory mock with the real config.yaml-backed
// ConfigManager once it lands. This is the only place that needs to change.
func newConfigManager() configmanager.ConfigManager {
	return configmanagertest.New(map[string]any{
		"ui.port":                    float64(17900),
		"logging.level":              "info",
		"telemetry.retentionMinutes": float64(60),
		"splunk.realm":               "us1",
		"splunk.metricsExport":       false,
		"splunk.tracesExport":        false,
	}).
		WithSpec(configmanager.KeySpec{Key: "ui.port", Type: configmanager.TypeInteger, Minimum: int64Ptr(1024), Maximum: int64Ptr(65535)}).
		WithSpec(configmanager.KeySpec{Key: "logging.level", Type: configmanager.TypeString, AllowedValues: []any{"debug", "info", "warn", "error"}}).
		WithSpec(configmanager.KeySpec{Key: "telemetry.retentionMinutes", Type: configmanager.TypeInteger, Minimum: int64Ptr(1), Maximum: int64Ptr(1440)}).
		WithSpec(configmanager.KeySpec{Key: "splunk.realm", Type: configmanager.TypeString}).
		WithSpec(configmanager.KeySpec{Key: "splunk.metricsExport", Type: configmanager.TypeBoolean}).
		WithSpec(configmanager.KeySpec{Key: "splunk.tracesExport", Type: configmanager.TypeBoolean}).
		WithValidator("splunk.realm", func(value any) error {
			if realm, _ := value.(string); realm == "" {
				return errors.New("must be a non-empty string")
			}
			return nil
		})
}

func int64Ptr(value int64) *int64 { return &value }
