# Observability Studio

Observability Studio is a local OpenTelemetry workspace for developers. It
receives traces, metrics, and logs; provides a browser UI, REST API, and MCP
server; and ships agent skills for auditing, instrumenting, verifying, and
operationalizing telemetry.

## Quick start

For an editor-integrated Observer, install the extension and follow the
[extension guide](extension/README.md). To use the CLI instead, download and
extract the archive for your platform from
[Releases](https://github.com/signalfx/obstudio/releases/latest), then run:

```bash
cd obstudio_<version>_<os>_<arch>
./obstudio install --target=codex
```

Restart Codex after installation. If no Observer was already running, its MCP
configuration starts one; otherwise setup reuses the detected Observer. See the
[user guide](docs/USER.md) for other agents, shared setup, and configuration
options. To build from source instead, run `make run`; see
[CONTRIBUTING.md](CONTRIBUTING.md) for prerequisites, UI development, testing,
and release workflows.

## Using the skills

Choose the skill that matches your task. Each skill links to its documentation:

| Goal | Start with |
|---|---|
| Review a service and improve its telemetry | [`$otel-audit`](skills/otel-audit/SKILL.md) |
| Recheck existing instrumentation | [`$otel-verify`](skills/otel-verify/SKILL.md) |
| Generate detectors and dashboards | [`$splunk-configure`](skills/splunk-configure/SKILL.md) |
| Generate dashboards only | [`$splunk-dashboard`](skills/splunk-dashboard/SKILL.md) |
| Publish confirmed detector or dashboard gaps | [`$splunk-detector-publish`](skills/splunk-detector-publish/SKILL.md) or [`$splunk-dashboard-publish`](skills/splunk-dashboard-publish/SKILL.md) |
| Connect an existing Splunk organization | [`$connect-splunk-observability-cloud`](skills/connect-splunk-observability-cloud/SKILL.md) |
| Request a Free Edition organization | [`$create-splunk-free-account`](skills/create-splunk-free-account/SKILL.md) |

See the [user guide](docs/USER.md#using-the-skills) for the complete workflow
and [example prompts](docs/examples.md) for common tasks.

## Observer

Send OTLP data to `127.0.0.1:4317` or `http://127.0.0.1:4318`, then open
`http://127.0.0.1:3000`. Observer provides focused views for services, traces,
metrics, logs, semantic-convention validation, dashboard previews, and optional
Splunk Observability Cloud export. See the [Observer guide](observer/README.md)
for runtime configuration, APIs, routing, retention, and troubleshooting.

Token telemetry supports **Codex and Claude Code only** and is configured
through the standalone `obstudio` CLI. See the
[token-usage guide](observer/README.md#coding-agent-token-telemetry) for setup,
routing, repository correlation, and troubleshooting.

## Repository map

| Path | Contents |
|---|---|
| `observer/` | Go collector, OTLP receivers, REST and MCP APIs, and React UI. |
| `extension/` | VS Code-compatible extension and marketplace documentation. |
| `skills/` | Canonical agent skill sources. |
| `.agents/skills/` | Repo-local Codex discovery links. |
| `evals/` | Fixture services and skill eval cases. |
| `pytest-codex-evals/` | Reusable pytest plugin for the eval harness. |
| `eval-reports/` | Latest summarized eval results. |
| `docs/` | User, design, and workflow documentation. |

See [evals/README.md](evals/README.md) for skill evaluation.

## Security and privacy

See the plugin [security](plugins/obstudio/SECURITY.md) and
[privacy](plugins/obstudio/PRIVACY.md) documentation for details about data
handling and external connections.

## License

Apache License 2.0. See [LICENSE](LICENSE).
