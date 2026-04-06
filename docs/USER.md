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

Install skills and configure the MCP server:

```bash
./obstudio install --target=cursor
```

Skills are embedded in the binary -- a single file is all you need.

### Supported Targets

| Target | Skills directory | MCP config |
|--------|-----------------|------------|
| `cursor` | `~/.cursor/skills/obstudio/` | `~/.cursor/mcp.json` |
| `claude-code` | `~/.claude/skills/obstudio/` | `~/.claude/settings.json` |
| `codex` | `~/.codex/skills/obstudio/` | `~/.codex/mcp.json` |

The installer:
1. Extracts skills and references from the binary to the agent's skill directory
2. Copies the binary alongside the skills (stable path for MCP)
3. Configures the agent's MCP config to auto-start `obstudio`

Restart your editor/agent to activate.

### What Gets Installed

```
~/.cursor/skills/obstudio/
  obstudio              # binary (MCP server, auto-started by Cursor)
  audit/SKILL.md        # /audit skill
  instrument/SKILL.md   # /instrument skill
  verify/SKILL.md       # /verify skill
  provision/SKILL.md    # /provision skill
  observe/SKILL.md      # /observe composite orchestrator
  references/           # language guides and reference material
```

## CLI Reference

| Command | Description |
|---------|-------------|
| `obstudio` | Start the collector + stdio MCP server (OTLP receiver, Web UI, REST API, MCP) |
| `obstudio install --target=<agent>` | Install skills and configure MCP (`cursor`, `claude-code`, `codex`) |
| `obstudio --version` | Print version |
| `obstudio --help` | Show all available commands |

## Using Skills

Once installed, open any project in your agent and use:

| Command | What it does |
|---------|-------------|
| `/observe` | Full pipeline: audit -> instrument -> verify -> provision |
| `/audit` | Analyze codebase for observability gaps |
| `/instrument` | Add OpenTelemetry instrumentation |
| `/verify` | Validate telemetry flows end-to-end |
| `/provision` | Generate Terraform dashboards, detectors, and alerts |

Or use natural language:

```
instrument this service with OpenTelemetry
audit this service for observability gaps
verify my instrumentation is working
generate dashboards and alerts for this service
```

## Running the Full Observer

For the complete experience (Web UI, OTLP receiver, HTTP MCP endpoint):

```bash
obstudio
```

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

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST` | `127.0.0.1` | Bind address for all servers |
| `PORT` | `3000` | Web UI and MCP HTTP port |
| `OTLP_HTTP_PORT` | `4318` | OTLP/HTTP receiver port |
| `OTLP_GRPC_PORT` | `4317` | OTLP/gRPC receiver port |

## Example Prompts

See [examples.md](examples.md) (installed alongside skills) for a full
table of use cases, prompts, and which skill handles each one.
