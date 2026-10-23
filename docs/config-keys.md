# config.yaml keys

<!-- Generated from observer/internal/userconfig. Do not edit. Regenerate: cd observer && go test ./internal/userconfig -update -->

Splunk Observability Studio reads these keys from `~/.obstudio/config.yaml`. A key that is absent or has an invalid value uses its fail-safe value. A change applies while Splunk Observability Studio is running unless the key requires a restart.

## `telemetry`

### `telemetry.enabled`

**Send anonymous usage data**

Sends anonymous usage counts about Splunk Observability Studio itself to Splunk. Turning this off does not change what Splunk Observability Studio collects from your agents or shows you locally.

| Property | Value |
|---|---|
| Type | `bool` |
| Default | `true` |
| Fail-safe | `false` |
| Applies | Live |
