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

The canonical skill sources live under `skills/`. Codex discovers repo-local
entries through `.agents/skills/`, which points at those source directories.

## Quick Start

### Install From Release

Download the latest zip for your platform from
[Releases](https://github.com/signalfx/obstudio/releases/latest), then install
the skills and MCP config for your agent:

```bash
unzip obstudio_*_darwin_arm64.zip
./obstudio install --target=codex
```

After unzipping the release, run `obstudio install` from that extracted
directory without moving the files. The installer expects `weaver` to be next
to `obstudio`.

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

## Using The Skills

From a service directory, invoke the relevant skill in Codex:

```text
$otel-audit
$otel-instrument
```

Use `$otel-audit` to understand what is missing before editing. Use
`$otel-instrument` when you are ready to add SDK setup, auto-instrumentation,
and targeted custom signals.

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
