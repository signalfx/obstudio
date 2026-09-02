# Observability Studio

Observability Studio is a local OpenTelemetry workspace for receiving,
exploring, and validating telemetry while developing services. It includes a
Go collector, REST API, MCP server, React UI, and repo-scoped agent skills for
auditing, adding, and verifying OpenTelemetry instrumentation.

## Core Skills

| Skill | Purpose |
|---|---|
| `$otel-audit` | Scan a service for observability coverage gaps without modifying code |
| `$otel-instrument` | Add OpenTelemetry auto-instrumentation, default local application logs, and optional custom spans or metrics |
| `$otel-verify` | Prove existing instrumentation with app-code tests and optional local OTLP evidence |
| `$splunk-configure` | Generate Splunk O11y detector Terraform from an audit report |
| `$splunk-detector-publish` | Diff local detector Terraform against live Splunk detectors and create only the gaps |
| `$splunk-dashboard-publish` | Diff local dashboard Terraform against live Splunk dashboards and create only the gaps |
| `$splunk-sync` | (deprecated, use `$splunk-detector-publish`) Diff local detector Terraform against live Splunk detectors and create only the gaps |
| `$splunk-dashboard-sync` | (deprecated, use `$splunk-dashboard-publish`) Diff local dashboard Terraform against live Splunk dashboards and create only the gaps |

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

# Install for all supported agents (or pass just one target)
./obstudio install --target=codex,claude-code,cursor,kiro,windsurf,copilot
```

After unzipping the release, run `obstudio install` from that extracted
directory without moving the files. The installer expects `weaver` to be next
to `obstudio`. `--target` accepts `codex`, `claude-code`, `cursor`, `kiro`,
`windsurf`, `copilot`, or a comma-separated list of those values. For each
selected agent with a skills directory, the installer stores the managed bundle
under that directory and creates top-level discoverable skill entries such as
`otel-audit`, `otel-instrument`, and `otel-verify` in the agent skills root.
`copilot` has no agent-skills mechanism, so its install configures only the MCP
server (VS Code user `mcp.json`) and installs no skill entries.
After installation, restart the agent if it does not discover the new skills.

For an Observer that should keep running independently of a terminal, use the
explicit managed background lifecycle:

```bash
obstudio start
obstudio status
obstudio restart
obstudio stop
```

Installation never restarts a running Observer. After installing a higher
version, run `obstudio restart` when convenient to activate it. These commands
control only an Observer launched by `obstudio start`; a foreground Observer is
still stopped with `Ctrl+C`, and the editor extension manages its own process.

Kiro installs the bundle under `~/.kiro/skills/obstudio`, creates its
discoverable skill entries in `~/.kiro/skills`, and configures MCP in
`~/.kiro/settings/mcp.json`. Invoke a skill in Kiro with its slash command,
such as `/otel-audit`.

Release archives are verified against `checksums.txt` published by the release
pipeline before the Codex plugin bootstrapper extracts them.

For the Codex plugin trust contract, including local Observer bootstrap,
localhost endpoints and Splunk publish behavior,
see [plugins/obstudio/SECURITY.md](plugins/obstudio/SECURITY.md) and
[plugins/obstudio/PRIVACY.md](plugins/obstudio/PRIVACY.md). The same plugin
bundle serves Claude Code through the repository's `.claude-plugin/marketplace.json`.

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
and `4317`; these are also used by the editor extension.

### Local Development

Use this workflow when editing the Telemetry Explorer UI (`observer/client`)
and you want changes to show up without a full `make build` each time.

1. Start the collector with the `dev` build tag so it serves client assets
   straight from disk instead of the snapshot embedded by `make build`:

   ```bash
   make build-client
   cd observer && go run -tags dev ./cmd/obstudio
   ```

2. In a second terminal, watch and rebuild the client on every save:

   ```bash
   make dev
   ```

3. Open http://localhost:3000. From here it hot-reloads on its own: each
   client rebuild pushes a reload signal over the existing telemetry
   WebSocket to every open tab, so there's no need to manually refresh the
   browser after a save.

The `dev` build tag only affects the binary you run locally with `go run
-tags dev`; release and embedded builds (`make build`/`make run`) never
include it, and the reload-trigger endpoint it adds does not exist otherwise.

### Optional Splunk Metrics Forwarding

Obstudio accepts OTLP traces, metrics, and logs and displays all three in the
local Telemetry Explorer. Splunk Observability Cloud forwarding is opt-in and
applies only to traces and metrics. Logs sent to `/v1/logs` remain in the local
Explorer's Logs view, even when trace and metric forwarding are enabled.

To forward received metrics to Splunk Observability Cloud, put the settings in
Obstudio's default env file:

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
$otel-verify
$splunk-configure
$splunk-sync
```

Use `$otel-audit` to understand what is missing before editing. Use
`$otel-instrument` when you are ready to add SDK setup, auto-instrumentation,
and targeted custom signals. It runs the `$otel-verify` workflow by default
after its implementation gate. The audit writes canonical
`.observe/otel-audit.json` plus a self-contained `.observe/otel.html`; review
and select findings through the returned localhost link, then copy and run the
generated `$otel-instrument` command. The command carries the explicit finding
IDs, decision answers, and validated service root. You can alternatively invoke
`$otel-instrument --ids OTEL-001,OTEL-004` directly; the skill writes the same
validated selection handoff before editing. Instrumentation writes a separate
`.observe/otel-instrumentation.html` that maps selected gaps to code changes,
exact telemetry, product impact, proof, and next actions; it does not turn the
audit HTML into a change log. Both HTML reports are returned as user-clicked,
tokenized `127.0.0.1` links and are never opened automatically. Markdown and
JSON reports remain local-file links. The bundled renderer uses only the Python
standard library, and both HTML reports have no Bun, Node, YAML parser, package,
font, or external network dependency. Run `$otel-verify` after the canonical
audit/selection and instrumentation handoff to recheck existing instrumentation
and refresh proof in the instrumentation HTML. It produces
`.observe/otel-verify.json` plus the readable `.observe/otel-verify.md`. See
[OTel Verify](docs/otel-verify.md) for invocation and report-reading guidance.
Use `$splunk-configure` after auditing to generate Splunk Observability Cloud
detector Terraform — it reads the audit report, classifies metrics, and outputs
ready-to-apply HCL with a `terraform.tfvars.example` for credentials. Use
`$splunk-sync` to diff those specs against live Splunk detectors and create only
the ones that don't exist yet.

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
├── extension/         # VS Code-compatible extension for Visual Studio Code, Kiro, and Cursor
├── skills/            # Canonical agent skill sources
│   ├── otel-audit/
│   ├── otel-instrument/
│   ├── otel-verify/
│   ├── splunk-configure/
│   ├── splunk-detector-publish/
│   ├── splunk-sync/   # deprecated alias → splunk-detector-publish
│   ├── splunk-dashboard-publish/
│   ├── splunk-dashboard-sync/ # deprecated alias → splunk-dashboard-publish
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
| Node.js | 20+ | React client and VS Code-compatible editor extension |
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
| `make test-all` | Run Go, client, extension, and skill-script tests |
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
| `obstudio install --target=<agent>[,<agent>...]` | Install skills and configure MCP for one or more supported agents |
| `obstudio token-telemetry enable --target=codex[,claude-code] [--repository-correlation=off\|name\|path]` | Explicitly opt supported providers into local token logs and traces, plus Claude token metrics, without replacing user-owned OTLP settings; new targets default repository correlation to `path` |
| `obstudio token-telemetry status --target=codex[,claude-code]` | Show whether matching telemetry is Obstudio-managed, user-owned, partial, disabled, or conflicting |
| `obstudio token-telemetry disable --target=codex[,claude-code]` | Remove only unchanged settings added by Obstudio |
| `obstudio --version` | Print version |

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) for the development process and
[AGENTS.md](AGENTS.md) for repo-specific AI agent guidelines.

## Splunk Copyright Notice

Apache License 2.0. See [LICENSE](LICENSE).
