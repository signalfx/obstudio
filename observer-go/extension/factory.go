package extension

import (
	"context"

	"github.com/signalfx/obstudio/observer-go/internal/store"
	"go.opentelemetry.io/collector/component"
	"go.opentelemetry.io/collector/extension"
)

const componentType = "obstudio"

func NewFactory(s *store.Store) extension.Factory {
	return extension.NewFactory(
		component.MustNewType(componentType),
		createDefaultConfig,
		func(_ context.Context, _ extension.Settings, cfg component.Config) (extension.Extension, error) {
			return newExtension(cfg.(*Config), s), nil
		},
		component.StabilityLevelDevelopment,
	)
}

func createDefaultConfig() component.Config {
	return &Config{
		Endpoint: "127.0.0.1:3000",
	}
}
