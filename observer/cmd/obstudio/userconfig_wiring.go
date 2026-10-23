package main

import (
	"log"

	"github.com/signalfx/obstudio/observer/internal/api"
	"github.com/signalfx/obstudio/observer/internal/configstatus"
	"github.com/signalfx/obstudio/observer/internal/userconfig"
	"github.com/signalfx/obstudio/observer/internal/web"
)

// notifyConfigChanged is replaced in tests to count notifications.
var notifyConfigChanged = web.NotifyConfigChanged

// userConfigWiring is the process's one config Manager and the views of it
// handed to the HTTP and MCP layers. Every field is nil when the Manager
// could not be built.
type userConfigWiring struct {
	manager *userconfig.Manager
	api     api.UserConfig
	status  *configstatus.Builder
}

// openUserConfig builds the config Manager for ~/.obstudio/config.yaml and
// connects its events to the UI's live config signal. The caller closes the
// Manager; Close also ends the subscription.
func openUserConfig() userConfigWiring {
	path, err := userConfigYAMLPath()
	if err != nil {
		log.Printf("warning: user settings are unavailable: %v", err)
		return userConfigWiring{}
	}
	m, err := userconfig.NewManager(path)
	if err != nil {
		log.Printf("warning: user settings are unavailable: %v", err)
		return userConfigWiring{}
	}
	m.Subscribe(func(userconfig.Event) { notifyConfigChanged() })
	return userConfigWiring{manager: m, api: api.NewUserConfig(m), status: configstatus.New(m, path)}
}
