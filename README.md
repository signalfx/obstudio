# Observability Studio

Observability Studio is a local OpenTelemetry workspace for receiving,
exploring, and validating telemetry while developing services. It includes a
Go collector, REST API, MCP server, React UI, and repo-scoped agent skills for
auditing and adding OpenTelemetry instrumentation.

## Core Skills

| Skill | Purpose |
|---|---|
| `$otel-audit` | Scan a service for observability coverage gaps without modifying code |
| `$otel-instrument` | Add OpenTelemetry auto-instrumentation and optional custom spans or metrics |
| `$splunk-configure` | Generate Splunk O11y detector Terraform from an audit report |
| `$splunk-sync` | Diff local detector Terraform against live Splunk detectors and create only the gaps |

The canonical skill sources live under `skills/`. Codex discovers repo-local
entries through `.agents/skills/`, which points at those source directories.

## Quick Start

### Install From Release

Download the latest zip for your platform from
[Releases](https://github.com/signalfx/obstudio/releases/latest), then install
the skills and MCP config for your agent:

```bash
unzip obstudio_*_darwin_arm64.zip
cd obstudio_*_darwin_arm64
./obstudio install --target=<agent>
```

After unzipping the release, run `obstudio install` from that extracted
directory without moving the files. The installer expects `weaver` to be next
to `obstudio`. It stores the managed bundle under `~/.<agent>/skills/obstudio/`
and creates top-level discoverable skill entries such as `otel-audit` and
`otel-instrument` in the agent skills root.

### Build From Source

```bash
make build
make run
```

The collector starts on:

| Service | URL |
|---|---|
| Telemetry Explorer | http://localhost:3000 |
| OTLP/HTTP | http://localhost:4318 |
| OTLP/gRPC | localhost:4317 |
| MCP endpoint | http://localhost:3000/mcp |

Use `obstudio --observer-http-port <port>` to move the Observer UI, REST API,
and MCP endpoint to a different port. The OTLP receivers stay fixed at `4318`
and `4317`, matching the VS Code extension.

### Optional Splunk Metrics Forwarding

By default, Obstudio stores incoming OTLP telemetry locally for inspection. To
also forward received metrics to Splunk Observability Cloud, put the settings
in Obstudio's default env file:

```bash
mkdir -p ~/.obstudio
chmod 700 ~/.obstudio
cat > ~/.obstudio/env <<'EOF'
OBSTUDIO_SPLUNK_METRICS_EXPORT=true
SPLUNK_REALM=<your-realm>
SPLUNK_ACCESS_TOKEN=<your-org-ingest-token>
EOF
chmod 600 ~/.obstudio/env
obstudio
```

The token must be an org access token with ingest scope. Splunk's documented
OTLP/HTTP authentication header is `X-SF-Token`.
Shell environment variables override values from the env file. Use
`obstudio --env-file <path>` or `OBSTUDIO_ENV_FILE=<path>` to load a different
env file.

Obstudio forwards metrics over OTLP/HTTP protobuf to:

```text
https://ingest.<realm>.observability.splunkcloud.com/v2/datapoint/otlp
```

Use `OBSTUDIO_SPLUNK_METRICS_ENDPOINT` to override the full endpoint. Explicit
endpoint values are used exactly as configured. Use
`OBSTUDIO_SPLUNK_METRICS_TIMEOUT` to override the default `5s` export timeout.
The access token is only read from the environment and is never returned by
`/api/health`.

### Optional Splunk Traces Forwarding

To also forward received traces to Splunk Observability Cloud APM, add the
traces flag to the same env file:

```bash
cat >> ~/.obstudio/env <<'EOF'
OBSTUDIO_SPLUNK_TRACES_EXPORT=true
EOF
```

The same `SPLUNK_REALM` and `SPLUNK_ACCESS_TOKEN` values are used for both
metrics and traces. Obstudio forwards traces over OTLP/HTTP protobuf to:

```text
https://ingest.<realm>.observability.splunkcloud.com/v2/trace/otlp
```

Use `OBSTUDIO_SPLUNK_TRACES_ENDPOINT` to override the full endpoint. Use
`OBSTUDIO_SPLUNK_TRACES_TIMEOUT` to override the default `5s` export timeout.
Once traces are flowing, the service appears as an APM service in Splunk
Observability Cloud and becomes a valid target for `$splunk-sync`.

## Using The Skills

From a service directory, invoke the relevant skill in Codex:

```text
$otel-audit
$otel-instrument
$splunk-configure
$splunk-sync
```

Use `$otel-audit` to understand what is missing before editing. Use
`$otel-instrument` when you are ready to add SDK setup, auto-instrumentation,
and targeted custom signals. Use `$splunk-configure` after auditing to generate
Splunk Observability Cloud detector Terraform — it reads the audit report,
classifies metrics, and outputs ready-to-apply HCL with a `terraform.tfvars.example`
for credentials. Use `$splunk-sync` to diff those specs against live Splunk
detectors and create only the ones that don't exist yet.

## Validation

Validation is available through the Explorer UI, REST API, and MCP.

1. Start `obstudio`.
2. Send traces, metrics, and logs to the OTLP receiver.
3. Open the **Validation** tab and run validation.
4. Use the findings to inspect affected telemetry rows.

| Surface | Entry points |
|---|---|
| REST | `/api/query/validation/summary`, `/api/query/validation/latest`, `/api/validation/run`, `/api/validation/refresh` |
| MCP | `observer_validation_status`, `observer_validation_analyze`, `observer_validation_refresh` |

If you move `obstudio` manually instead of using `obstudio install`, keep
the bundled `weaver` runtime beside it or make `weaver` available on
`PATH`.

## Repository Layout

```text
obstudio/
├── observer/          # Go collector, REST API, MCP server, and embedded web UI
├── extension/         # VS Code extension that packages the collector
├── skills/            # Canonical agent skill sources
│   ├── otel-audit/
│   ├── otel-instrument/
│   ├── splunk-configure/
│   ├── splunk-sync/
│   └── references/    # Shared language guides and signal references
├── .agents/skills/    # Repo-scoped Codex skill entries
├── evals/             # Fixture services and JSON eval cases
├── pytest-codex-evals/# Reusable pytest plugin for Codex eval harnessing
├── eval-reports/      # Latest summarized eval reports
├── docs/              # Design docs and usage examples
├── Makefile
├── AGENTS.md
└── CONTRIBUTING.md
```

## Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| Go | 1.25+ | Collector and CLI |
| Node.js | 20+ | React client and VS Code extension |
| npm | latest | JavaScript package management |
| uv | latest | Python eval harness and Python fixture apps |
| Docker | latest | Optional runtime eval checks |

## Development Commands

| Target | Description |
|---|---|
| `make build` | Build the `obstudio` binary with embedded skills and client assets |
| `make run` | Build and start the collector |
| `make test` | Run Go tests |
| `make test-client` | Run React client tests |
| `make test-extension` | Run extension tests |
| `make test-all` | Run Go, client, and extension tests |
| `make fmt` | Format Go source |
| `make vet` | Vet Go source |
| `make tidy` | Tidy Go modules |
| `make list-skills` | List repo skills |
| `make eval-validation` | Validate eval JSONs without running Codex |
| `make eval-sanity` | Run quick loaded-skill eval checks |
| `make eval-rubric` | Run schema-constrained rubric eval checks |
| `make eval-runtime` | Run Docker/Observer runtime eval checks |
| `make -C evals eval-*-test` / `make -C evals eval-*-report` | Split eval execution from report rendering |
| `make eval-all` | Run validation, sanity, rubric, and runtime evals |
| `make eval-all-ab` | Run validation plus A/B sanity, rubric, and runtime evals |
| `make test-pytest-plugin` | Run reusable pytest plugin tests |
| `make build-pytest-plugin` | Build pytest plugin distribution artifacts |
| `make publish-pytest-plugin` | Publish pytest plugin artifacts with `uv publish` credentials |
| `make release-local` | Build local release archives |
| `make clean` | Remove build artifacts |

## Skill Evals

Skill eval definitions and fixture apps live under `evals/`. See
[evals/README.md](evals/README.md) for eval modes, commands, configs, and
report locations.

## CLI Reference

| Command | Description |
|---|---|
| `obstudio` | Start the collector, web UI, REST API, OTLP receivers, and MCP server |
| `obstudio install --target=<agent>` | Install skills and configure MCP for a supported agent |
| `obstudio --version` | Print version |

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) for the development process and
[AGENTS.md](AGENTS.md) for repo-specific AI agent guidelines.

## Splunk Copyright Notice

Apache License 2.0. See [LICENSE](LICENSE).
