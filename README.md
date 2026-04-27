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
| `make test-pytest-plugin` | Run reusable pytest plugin tests |
| `make build-pytest-plugin` | Build pytest plugin distribution artifacts |
| `make publish-pytest-plugin` | Publish pytest plugin artifacts with `uv publish` credentials |
| `make release-local` | Build local release archives |
| `make clean` | Remove build artifacts |

## Skill Evals

Skill evals are pytest-collected JSON files. Each fixture keeps its eval
definitions next to the service code:

```text
evals/<language>/<service>/audit_eval.json
evals/<language>/<service>/instrument_eval.json
```

Each eval defines `prompts[]` task variants. `skill-eval` validates those JSON
files and fixtures quickly; `skill-eval-ab` runs live A/B comparisons for the
selected tasks.

Each eval JSON keeps the human-facing tasks at the top, then deterministic and
qualitative checks:

```json
{
  "skill": "otel-audit",
  "prompts": [
    {
      "id": "direct",
      "task": "Scan the service in ./service for observability gaps."
    }
  ],
  "deterministic_checks": [],
  "qualitative_checks": []
}
```

The live A/B harness runs each case twice:

| Side | Skill visibility |
|---|---|
| `with_skill` | Copied fixture plus temporary `.agents/skills` entries |
| `baseline` | Same copied fixture with no repo skills visible |

Baseline checks stay intentionally simple: run health plus `skills-not-loaded`.
Detailed deterministic artifact checks default to the `with_skill` side, which
also gets a `skills-loaded` guard.

Common commands:

| Target | Purpose |
|---|---|
| `make test-eval-harness` | Validate every eval JSON and fixture |
| `make skill-eval-list SKILL=skills/otel-audit` | List collected eval items for a skill path |
| `make skill-eval SKILL=skills/otel-instrument CASE=go/kvstore` | Validate one fixture |
| `make skill-eval SKILL=skills/otel-instrument CASE=go/kvstore PROMPT=direct` | Validate one prompt variant |
| `make skill-eval-ab SKILL=skills/otel-audit CASE=go/chi-basic PROMPT=direct` | Run live Codex A/B for one prompt |
| `make skill-eval-all` | Validate all eval JSONs |

Live A/B settings are configured in TOML:

| File | Purpose |
|---|---|
| `evals/codex-evals.toml` | Default validation config |
| `evals/codex-evals.ab.toml` | Live A/B config, including qualitative judge model |

Set the judge model with:

```toml
[models]
agent = "gpt-5.2"
judge = "gpt-5.2"
```

Full run artifacts are written under `.workspace/codex-evals/<skill>/<run-id>/`.
Latest summaries are copied to `eval-reports/<skill>/REPORT.md` and
`eval-reports/<skill>/benchmark.json`.

## Eval Fixture Apps

| App | Stack | Run |
|---|---|---|
| `evals/python/flask-basic/` | Flask | `make dev` |
| `evals/python/fastapi-celery/` | FastAPI + Celery | `make dev` |
| `evals/node/express-basic/` | Express | `npm run dev` |
| `evals/go/chi-basic/` | Chi | `go run .` |
| `evals/go/kvstore/` | Chi + package tests | `make test` |

## CLI Reference

| Command | Description |
|---|---|
| `obstudio` | Start the collector, web UI, REST API, OTLP receivers, and MCP server |
| `obstudio install --target=<agent>` | Install skills and configure MCP for a supported agent |
| `obstudio --version` | Print version |

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) for the development process and
[AGENTS.md](AGENTS.md) for repo-specific AI agent guidelines.

## License

Apache License 2.0. See [LICENSE](LICENSE).
