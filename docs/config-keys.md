# config.yaml keys

<!-- Generated from observer/internal/userconfig. Do not edit. Regenerate: cd observer && go test ./internal/userconfig -update -->

Splunk Observability Studio reads these keys from `~/.obstudio/config.yaml`. A key that is absent or has an invalid value uses its fail-safe value. A change applies while Splunk Observability Studio is running unless the key requires a restart.

## Privacy (`telemetry`)

### `telemetry.enabled`

**Send anonymous usage data**

Allow Cisco to collect anonymous usage data about Splunk Observability Studio itself. Turning this off does not change what Splunk Observability Studio collects from your agents or shows you locally.

To turn this off, run: obstudio telemetry disable

| Property | Value |
|---|---|
| Type | `bool` |
| Default | `true` |
| Fail-safe | `false` |
| Applies | Live |
