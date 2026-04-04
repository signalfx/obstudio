# Observability Studio

Local OpenTelemetry observability workspace -- receive, explore, and
validate telemetry during development. Includes AI agent skills that
audit codebases and add OpenTelemetry instrumentation automatically.

## Repository Layout

```
obstudio/
├── observer/          # Observer app (React UI + Node/Express server)
├── observer-go/       # Go-based Observer built on the OTel Collector framework
├── extension/         # VS Code extension that packages the Observer
├── skills/            # AI agent skills (composable workflows)
│   ├── audit/         #   /audit -- gap analysis, .observe/ generation
│   ├── instrument/    #   /instrument -- OTel implementation
│   ├── verify/        #   /verify -- telemetry validation
│   ├── provision/     #   /provision -- Terraform, detectors, alerts
│   ├── observe/       #   /observe -- composite orchestrator
│   └── references/    #   Shared language guides and reference material
├── docs/              # Design docs, PRD, and example prompts
├── demo/              # Sample apps for skill evaluation (gitignored)
├── Makefile           # Skill packaging
├── AGENTS.md          # Guidelines for AI agents
└── CONTRIBUTING.md    # Dev process, PR workflow, releases
```

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Node.js | 20+ | Observer app and VS Code extension |
| npm | latest | Package management |
| Go | 1.22+ | observer-go collector |
| uv | latest | Running Python demo apps |
| VS Code | 1.110+ | Extension development (optional) |

## Quick Start

### 1. Build and Run the Observer

```bash
make build
make run
```

This starts the collector on:

| Service | URL |
|---------|-----|
| Telemetry Explorer | http://localhost:3000 |
| OTLP/HTTP | http://localhost:4318 |
| OTLP/gRPC | localhost:4317 |
| MCP endpoint | http://localhost:3000/mcp |

### 2. Build the Observer (Node/React frontend)

```bash
cd observer
npm install
npm run dev
```

### 3. Build the VS Code Extension

```bash
cd extension
npm install
npm run build:vsix
```

## Skills

Skills are composable AI agent workflows that follow the
[addyosmani/agent-skills](https://github.com/addyosmani/agent-skills)
anatomy. Each skill is a `SKILL.md` with: Overview, When to Use,
Process, Red Flags, and Verification.

### Available Skills

```bash
make list-skills
```

| Skill | Command | Description |
|-------|---------|-------------|
| Audit | `/audit` | Analyze codebase for observability gaps, produce `.observe/inventory.md` |
| Instrument | `/instrument` | Implement OTel auto + custom instrumentation for identified KPIs |
| Verify | `/verify` | Start Observer, exercise APIs, validate traces and metrics |
| Provision | `/provision` | Generate Terraform dashboards, detectors, and alert rules |
| Observe | `/observe` | Composite: chains audit -> instrument -> verify -> provision |

### Skill Lifecycle

```
  AUDIT           INSTRUMENT      VERIFY          PROVISION
 ┌──────┐        ┌──────┐       ┌──────┐        ┌──────┐
 │ Scan │  ───>  │ Code │ ───>  │ Test │  ───>  │ Ship │
 │ Gaps │        │ OTel │       │  Run │        │  IaC │
 └──────┘        └──────┘       └──────┘        └──────┘
  /audit          /instrument    /verify          /provision

                       /observe (chains all four)
```

All skills operate on the same `.observe/` directory:

```
.observe/
├── inventory.md          # KPI table, components, fault domains
├── terraform/            # Splunk O11y Cloud dashboards and detectors
└── alerts/               # Prometheus, Grafana, PagerDuty alert rules
```

### Shared References

Language guides and reference material live in `skills/references/`.
Skills load them on-demand to minimize token usage:

```
skills/references/
├── languages/            # Go, Node.js, Python OTel guides
├── fault-domain-patterns.md
├── signal-mapping-guide.md
└── observability-template.md
```

### Install Skills

Download a release archive, extract it, and run the installer:

```bash
curl -L https://github.com/signalfx/obstudio/releases/latest/download/obstudio_Darwin_arm64.tar.gz | tar xz
cd obstudio_Darwin_arm64/
./obstudio install --target=cursor
```

This copies skills and references to `~/.cursor/skills/obstudio/` and
configures `~/.cursor/mcp.json` to auto-start the MCP server.

### CLI Reference

| Command | Description |
|---------|-------------|
| `obstudio` | Start the full collector (OTLP receiver, Web UI, MCP over HTTP) |
| `obstudio install --target=<agent>` | Install skills and configure MCP (`cursor`, `claude-code`, `codex`) |
| `obstudio mcp` | Start the MCP server over stdio (auto-started by Cursor) |
| `obstudio --version` | Print version |
| `obstudio --help` | Show help for all commands |
| `obstudio install --help` | Show help for the install command |

### Using the Skills

In your AI coding agent, navigate to a service directory and run:

```
/observe
```

Or use individual skills:

```
/audit          # analyze gaps only
/instrument     # add OTel code (requires .observe/inventory.md)
/verify         # validate telemetry (requires instrumented code)
/provision      # generate Terraform/alerts (requires verified KPIs)
```

Or use natural language:

```
instrument this service with OpenTelemetry
audit this service for observability gaps
verify my instrumentation is working
generate dashboards and alerts for this service
```

See [docs/examples.md](docs/examples.md) for more prompt examples.

## Demo Apps

The `demo/` directory contains sample apps for evaluating skills.
Baselines are committed; generated artifacts (`.observe/`, `otel_*.py`,
`.venv/`) are gitignored.

| App | Stack | Run |
|-----|-------|----|
| `demo/python-flask-basic/` | Flask (in-memory) | `make dev` |
| `demo/python-fastapi-celery/` | FastAPI + Celery + Redis (Docker) | `make up` or `make dev` |

Run locally with `uv`:

```bash
cd demo/python-flask-basic
make dev          # starts on :8000
```

Run with Docker (FastAPI + Celery + Redis):

```bash
cd demo/python-fastapi-celery
make up           # docker compose up --build -d
make down         # tear down
```

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full development process
including PR workflow, review policy, testing requirements, and release
cadence.

See [AGENTS.md](AGENTS.md) for AI agent guidelines.

## Make Targets

| Target | Description |
|--------|-------------|
| `make help` | Show all targets |
| `make package-skills` | Package skills into `build/skills/` |
| `make list-skills` | List available skills |
| `make release-local` | Build release archives locally via GoReleaser |
| `make clean` | Remove build artifacts |
