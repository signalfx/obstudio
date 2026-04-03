# Observability Studio

Local OpenTelemetry observability workspace -- receive, explore, and
validate telemetry during development. Includes AI agent skills that
audit codebases and add OpenTelemetry instrumentation automatically.

## Repository Layout

```
obstudio/
├── observer/          # Observer app (React UI + Node/Express server)
├── observer-go/       # Go-based OTel Collector with REST API, MCP, and Web UI
├── extension/         # VS Code extension that packages the Observer
├── skills/            # AI agent skills (SKILL.md entry points)
│   └── observe/       #   /observe -- audit + instrument + verify
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

### 1. Build the Observer (Go backend)

```bash
cd observer-go
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

Skills are AI agent plug-ins that follow a structured workflow defined
in `SKILL.md` files. They are consumed by coding agents (Cursor, Claude
Code, Codex, etc.) and provide domain-specific capabilities.

### Available Skills

```bash
make list-skills
```

| Skill | Description |
|-------|-------------|
| `/observe` | Audit a codebase for observability, generate `.observe/` inventory, implement OTel instrumentation, and verify telemetry against the Observer |

### Package Skills for Distribution

```bash
make package-skills
```

This copies skill directories into `build/skills/` ready for
installation:

```bash
obstudio register --agent <cursor|claude-code|codex>
```

### Skill Structure

Each skill follows this layout:

```
skills/<name>/
├── SKILL.md                    # Entry point with workflow steps
├── languages/                  # Language-specific guides (loaded on-demand)
│   ├── go.md
│   ├── node.md
│   └── python.md
└── references/                 # Reference material (loaded per-step)
    ├── fault-domain-patterns.md
    ├── observability-template.md
    └── signal-mapping-guide.md
```

Skills are token-conscious: language guides and references are loaded
lazily based on what the workflow step requires, not all at once.

### Using the /observe Skill

In your AI coding agent, navigate to a service directory and run:

```
/observe
```

Or use natural language:

```
instrument this service with OpenTelemetry
```

The skill will:
1. Discover the language, framework, and existing instrumentation
2. Map components and fault domains
3. Identify KPIs using the four golden signals
4. Generate a `.observe/` directory with an inventory
5. Implement OTel instrumentation (auto + custom)
6. Optionally verify against the Observer -- start the collector, fire
   APIs, validate traces and metrics, and mark KPIs as verified

See [docs/examples.md](docs/examples.md) for more prompt examples.

## Demo Apps

The `demo/` directory contains sample applications for evaluating
skills. These are gitignored -- the baselines are in git history and
can be restored with:

```bash
git checkout c11c968 -- demo/
```

| App | Stack | Purpose |
|-----|-------|---------|
| `demo/python-fastapi/` | FastAPI + SQLite | Minimal single-file API |
| `demo/python-flask/` | Flask + PostgreSQL + Redis + Celery | Multi-component microservice |

Run a demo app:

```bash
cd demo/python-fastapi
make dev
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
| `make clean` | Remove build artifacts |
