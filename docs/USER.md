# Observability Studio -- User Guide

## Installation

Download the binary for your platform and run the installer:

```bash
# macOS (Apple Silicon)
curl -LO https://github.com/signalfx/obstudio/releases/latest/download/obstudio_darwin_arm64.zip
unzip obstudio_darwin_arm64.zip

# macOS (Intel)
curl -LO https://github.com/signalfx/obstudio/releases/latest/download/obstudio_darwin_amd64.zip
unzip obstudio_darwin_amd64.zip

# Linux (x86_64)
curl -LO https://github.com/signalfx/obstudio/releases/latest/download/obstudio_linux_amd64.zip
unzip obstudio_linux_amd64.zip
```

After unzipping the release, change into the directory created by `unzip` and
run the installer:

```bash
cd obstudio_<version>_<os>_<arch>
./obstudio install --target=<agent>
```

This installs the included skills and configures the MCP server.

### Supported Targets

| Target | Skills directory | MCP config |
|--------|-----------------|------------|
| `cursor` | `~/.cursor/skills/obstudio/` | `~/.cursor/mcp.json` |
| `claude-code` | `~/.claude/skills/obstudio/` | `~/.claude.json` |
| `codex` | `~/.codex/skills/obstudio/` | `~/.codex/config.toml` |

The installer:
1. Extracts skills and references from the binary to the agent's skill directory
2. Copies `obstudio` and the bundled `weaver` runtime alongside the skills (stable path for MCP)
3. Creates top-level discoverable skill entries in the agent skills root
4. Configures the agent's MCP config to auto-start `obstudio` or reuse a shared Observer

Restart your agent to activate.

### What Gets Installed

```
~/.cursor/skills/obstudio/
  obstudio              # binary (MCP server, auto-started by Cursor)
  weaver                # validator runtime used by the Validation tab and APIs
  otel-audit/SKILL.md   # bundled /otel-audit skill file
  otel-instrument/SKILL.md # bundled /otel-instrument skill file
  references/           # language guides and reference material

~/.cursor/skills/
  otel-audit -> obstudio/otel-audit
  otel-instrument -> obstudio/otel-instrument
```

## CLI Reference

| Command | Description |
|---------|-------------|
| `obstudio` | Start the collector + stdio MCP server (OTLP receiver, Web UI, REST API, MCP) |
| `obstudio install --target=<agent>` | Install skills and configure MCP (`cursor`, `claude-code`, `codex`) |
| `obstudio --observer-http-port <port>` | Override the Observer UI, REST API, and MCP HTTP port |
| `obstudio --env-file <path>` | Load startup environment values from a `KEY=VALUE` env file |
| `obstudio --version` | Print version |
| `obstudio --help` | Show all available commands |

## Using Skills

Once installed, open any project in your agent and use:

| Command | What it does |
|---------|-------------|
| `/otel-audit` | Analyze codebase for observability gaps |
| `/otel-instrument` | Add OpenTelemetry instrumentation |

Or use natural language:

```
instrument this service with OpenTelemetry
audit this service for observability gaps
```

## Running the Full Observer

For the complete experience (Web UI, OTLP receiver, HTTP MCP endpoint):

```bash
obstudio
```

To override the Observer UI, REST API, and MCP HTTP port explicitly:

```bash
obstudio --observer-http-port 41234
```

The OTLP receiver ports stay fixed at `4318` and `4317`, matching the VS Code
extension.

When a standalone Observer is already running, `obstudio install --target=<agent>`
auto-detects its current HTTP MCP endpoint from local runtime state, including
nondefault `--observer-http-port` values. Use `--shared-url` only when you want
to point an agent at a different already-running Observer explicitly.

| Service | URL |
|---------|-----|
| Telemetry Explorer | http://localhost:3000 |
| OTLP/HTTP receiver | http://localhost:4318 |
| OTLP/gRPC receiver | localhost:4317 |
| MCP endpoint | http://localhost:3000/mcp |

Configure your app to send telemetry:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
export OTEL_SERVICE_NAME=my-service
```

To forward incoming telemetry to Splunk Observability Cloud while still keeping
the local Explorer experience, put the settings in Obstudio's default env file:

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

### Metrics export

Metrics are forwarded via OTLP/HTTP protobuf to
`https://ingest.<realm>.observability.splunkcloud.com/v2/datapoint/otlp`.
Set `OBSTUDIO_SPLUNK_METRICS_ENDPOINT` to override the full endpoint. Explicit
endpoint values are used exactly as configured.
The token must be an org access token with ingest scope. Splunk's documented
OTLP/HTTP authentication header is `X-SF-Token`.

Shell environment variables override values from the env file. Use
`obstudio --env-file <path>` or `OBSTUDIO_ENV_FILE=<path>` to load a different
env file.

### Trace / span export

Obstudio also forwards spans to Splunk Observability Cloud via OTLP/HTTP,
making your service visible as a real **Splunk APM service** with
`service.request.*` metrics, trace latency distributions, and dependency maps.

Add the following to the env file (same token as metrics):

```bash
cat >> ~/.obstudio/env <<'EOF'
OBSTUDIO_SPLUNK_TRACES_EXPORT=true
SPLUNK_REALM=<your-realm>
SPLUNK_ACCESS_TOKEN=<your-org-ingest-token>
EOF
```

With these set, Obstudio exports all received spans to
`https://ingest.<realm>.observability.splunkcloud.com/v2/trace/otlp` (OTLP/HTTP)
alongside the local Explorer.

After spans flow in, Splunk APM materialises:
- `service.request.count`, `service.request.duration`, and related metrics per
  operation on the instrumented service
- Dependency maps showing calls between services
- Trace search and exemplar traces in the Splunk O11y UI

### Detector sync

Once your service is live in Splunk APM and you have local detector Terraform
from `$splunk-configure`, use `$splunk-sync` to close the loop:

```
$splunk-sync
```

This diffs `.observe/terraform/detectors.tf` against live Splunk Observability
Cloud detectors for the same service, classifies each local spec as COVERED /
GAP / UNCERTAIN, shows a confirmation diff, and creates only the genuine gaps
via the Splunk Observability Cloud REST API (`POST /v2/detector`). A resume
ledger is written to `.observe/detector-sync.md` so re-runs are idempotent.

`$splunk-sync` calls the Splunk REST API directly using `SPLUNK_ACCESS_TOKEN`
and `SPLUNK_REALM` — the same variables already required for metrics and traces
forwarding. No additional configuration is needed.

See the `$splunk-sync` skill for the full process and coverage model.

### Dashboard generation

Alongside detectors, you can turn the same audit report into Splunk
Observability Cloud **dashboards**:

```
$splunk-dashboard
```

This reads `.observe/otel.md`, groups the service's metrics into RED-style
panels (latency/duration, error rate, throughput, plus saturation and KPI
single-value tiles), and writes dashboard Terraform to
`.observe/terraform/dashboards.tf` — a `signalfx_dashboard_group`, one or more
`signalfx_dashboard`, and one `signalfx_*_chart` resource per panel placed on
the real 12-column grid — plus `variables.tf`, `terraform.tfvars.example`, a
`.observe/dashboards.md` report, and a `.observe/dashboards.preview.json`
sidecar consumed by the Observer's Dashboards tab. No network call is made; the
output is ready for `terraform apply` or `$splunk-dashboard-sync`.

### Dashboard preview (Dashboards tab)

Open the **Dashboards** tab in the Telemetry Explorer (or `?tab=dashboards`, or
press `6`) to preview each generated dashboard's grid layout against the OTLP
telemetry currently in the local store. The preview is honest about its limits:
SignalFlow `program_text` runs on Splunk's backend, so the tab parses each
panel's `{ metric, filters, aggregation }`, plots the matching *local* series in
the dashboard's real grid, and carries an explicit **"Approximate · local-data
preview"** badge. Panels whose metric is not currently being emitted show an
empty card naming the metric and filters rather than a fabricated chart. The tab
reads `.observe/dashboards.preview.json` on each refresh, so regenerating the
dashboard and pressing Refresh updates the preview.

### Dashboard sync

Once you have local dashboard Terraform from `$splunk-dashboard`, use
`$splunk-dashboard-sync` to push only the gaps:

```
$splunk-dashboard-sync
```

This diffs `.observe/terraform/dashboards.tf` against live Splunk Observability
Cloud dashboards for the same service and classifies the dashboard group, each
dashboard, and each chart as COVERED / GAP / UNCERTAIN with a concrete reason on
every row. After you confirm, it creates the gaps **chart-first** — `POST
/v2/chart` for each missing chart to collect chart IDs, then `POST /v2/dashboard`
referencing those IDs with grid placement (creating the group via `POST
/v2/dashboardgroup` first when it is missing) — and recovers orphaned charts if
the dashboard create fails. A resume ledger is written to
`.observe/dashboard-sync.md` (with the per-verdict reason and app links) so
re-runs are idempotent. Like `$splunk-sync`, it uses `SPLUNK_ACCESS_TOKEN` and
`SPLUNK_REALM` directly and needs no extra configuration.

See the `$splunk-dashboard` and `$splunk-dashboard-sync` skills for the full
classification and coverage model.

## Validation

When telemetry is flowing, open the **Validation** tab in the Telemetry
Explorer to run semantic validation against the current in-memory
snapshot. The latest retained result is summarized in the tab and
surfaced through the dedicated validation workflow.

Validation is also available programmatically:

| Surface | Entry points |
|---------|--------------|
| REST | `GET /api/query/validation/summary`, `GET /api/query/validation/latest`, `POST /api/validation/run`, `POST /api/validation/refresh` |
| MCP | `observer_validation_status`, `observer_validation_analyze`, `observer_validation_refresh` |

Use `observer_validation_analyze` for most questions about missing
telemetry or semantic convention issues. Use
`observer_validation_refresh` only when you explicitly want to rerun
validation against the current snapshot.

If you move `obstudio` manually instead of using `obstudio install`, keep
the bundled `weaver` runtime beside it or ensure `weaver` is available on
`PATH`.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST` | `127.0.0.1` | Bind address for all servers |
| `PORT` | `3000` | Observer UI, REST API, and MCP HTTP port |
| `OBSTUDIO_ENV_FILE` | `~/.obstudio/env` if present | Env file to load before startup; ignored when missing unless explicitly set |
| `SPLUNK_REALM` / `OBSTUDIO_SPLUNK_REALM` | unset | Splunk Observability Cloud realm — used for both metrics and trace export endpoints |
| `SPLUNK_ACCESS_TOKEN` | unset | Splunk org ingest token (metrics and traces `X-SF-Token` header) |
| `OBSTUDIO_SPLUNK_METRICS_EXPORT` / `SPLUNK_METRICS_EXPORT` | `false` | Forward received OTLP metrics to Splunk Observability Cloud |
| `OBSTUDIO_SPLUNK_METRICS_ENDPOINT` | unset | Full OTLP/HTTP metrics endpoint override |
| `OBSTUDIO_SPLUNK_METRICS_TIMEOUT` | `5s` | Splunk metrics export request timeout |
| `OBSTUDIO_SPLUNK_TRACES_EXPORT` / `SPLUNK_TRACES_EXPORT` | `false` | Forward received OTLP spans to Splunk Observability Cloud (activates APM service visibility) |
| `OBSTUDIO_SPLUNK_TRACES_ENDPOINT` | auto from realm | Full OTLP/HTTP traces endpoint override |
| `OBSTUDIO_SPLUNK_TRACES_TIMEOUT` | `5s` | Splunk traces export request timeout |

## Example Prompts

See [examples.md](examples.md) (installed alongside skills) for a full
table of use cases, prompts, and which skill handles each one.
