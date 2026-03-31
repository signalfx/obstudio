# Observability Studio — Layered Architecture

## The Layering Principle

Observability Studio is not a VS Code extension. It is not a CLI tool. It is a
layered product where each layer is independently useful and the outermost layer
is just a distribution mechanism.

```
┌─────────────────────────────────────────────────────────────────┐
│  Layer 3: Distribution                                          │
│                                                                 │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌──────────┐  │
│  │ VS Code    │  │ brew /     │  │ npx /      │  │ go       │  │
│  │ Extension  │  │ Homebrew   │  │ npm        │  │ install  │  │
│  └────────────┘  └────────────┘  └────────────┘  └──────────┘  │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Layer 2: obstudio                                        │  │
│  │                                                           │  │
│  │  Single binary / runnable package                         │  │
│  │  CLI interface, lifecycle management, skill installer     │  │
│  │                                                           │  │
│  │  ┌─────────────────────────────────────────────────────┐  │  │
│  │  │  Layer 1: Core                                      │  │  │
│  │  │                                                     │  │  │
│  │  │  ┌──────────────────┐    ┌──────────────────────┐   │  │  │
│  │  │  │  Skills          │    │  Observer             │   │  │  │
│  │  │  │                  │    │                       │   │  │  │
│  │  │  │  instrument/     │    │  OTLP receiver        │   │  │  │
│  │  │  │  terraform/      │    │  DuckDB storage       │   │  │  │
│  │  │  │  (agent-readable │    │  Query API (REST)     │   │  │  │
│  │  │  │   markdown)      │    │  MCP server           │   │  │  │
│  │  │  │                  │    │  Web UI               │   │  │  │
│  │  │  │                  │    │  Validator             │   │  │  │
│  │  │  └──────────────────┘    └──────────────────────┘   │  │  │
│  │  └─────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

This layering exists so that each ring can be used, tested, and distributed
independently:

- **Layer 1 (Core)** works without Layer 2 or 3. A developer can run the
  Observer server directly and read skill files from disk.
- **Layer 2 (obstudio)** works without Layer 3. A developer can `obstudio start`
  from any terminal, in any editor, with any AI agent.
- **Layer 3 (Distribution)** is how obstudio reaches developers. The VS Code
  extension is one channel. Homebrew is another. `go install` is another. None
  of them change what the product does.

## Who Is the Customer?

Developers who use **AI agents** to write, instrument, and debug code. The
Instrumenter and Terraformer are agent skills. The Telemetry Explorer and
Validator produce data that agents consume via MCP. The entire workflow is
agent-driven.

The product must reach these developers wherever they work: Cursor, Claude Code,
Windsurf, Cline, Continue, GitHub Copilot, JetBrains AI, OpenAI Codex, and
whatever comes next. A layered architecture achieves this because the core
product has zero dependency on any host environment.

---

## Layer 1: Core (Skills + Observer)

The core is two independent primitives that compose together but have no
dependency on each other or on any host environment.

### Skills — Agent-Readable Expertise

Skills are markdown files that codify instrumentation and infrastructure
expertise. An AI agent reads them to understand how to add OpenTelemetry to a
codebase, which semantic conventions to follow, and how to generate Splunk O11y
Cloud terraform.

```
skills/
├── instrument/
│   └── opentelemetry/
│       ├── SKILL.md          # Workflow, rules, checklist
│       ├── go.md             # Go-specific guidance
│       ├── python.md         # Python-specific guidance
│       ├── java.md           # Java-specific guidance
│       └── ...
└── terraform/
    └── SKILL.md              # Splunk O11y Cloud terraform
```

Skills are plain files. They require no runtime, no server, no binary. Any AI
agent that can read files can use them. This is Layer 1 — it works on its own.

### Observer — Local Telemetry Backend

The Observer is a local server that receives, stores, and exposes OpenTelemetry
data. It provides four surfaces:

| Surface           | Protocol          | Purpose                              |
|--------------------|-------------------|--------------------------------------|
| OTLP receiver     | HTTP `:4318`, gRPC `:4317` | Ingest traces, metrics, logs  |
| Query API         | REST on `:3000`   | Structured access to stored telemetry |
| MCP server        | Streamable HTTP on `:3000/mcp` | AI agents query telemetry programmatically |
| Web UI            | HTTP on `:3000`   | Visual trace/metric/log explorer     |

The Observer is also Layer 1. It has no knowledge of skills, no CLI wrapper, and
no editor integration. It is a server that receives OTLP and answers questions
about what it received.

### How They Compose

Skills tell the agent *what to do*. The Observer tells the agent *what happened*.
Together they form a closed loop:

```
┌─────────────────────────────────────────────────┐
│  1. Agent reads skill → instruments the code    │
│  2. Developer runs the app                      │
│  3. App sends OTLP to Observer (localhost:4318)  │
│  4. Agent calls MCP tools → inspects telemetry  │
│  5. Agent fixes issues → go to step 2           │
└─────────────────────────────────────────────────┘
```

Neither component knows about the other. The agent is the orchestrator that
connects them.

---

## Layer 2: obstudio (The Product)

Layer 2 composes the core primitives into a single, runnable product. It is a
cross-platform Go binary with no runtime dependencies.

```
$ obstudio start

  Telemetry Explorer:  http://localhost:3000
  OTLP/HTTP receiver:  http://localhost:4318
  OTLP/gRPC receiver:  localhost:4317
  MCP endpoint:        http://localhost:3000/mcp
```

The developer opens the web UI in a browser to visually inspect traces, metrics,
and logs. The AI agent connects to the MCP endpoint to programmatically query
telemetry and validate instrumentation results.

### What Layer 2 Adds Over Layer 1

| Capability               | Layer 1 (Core)     | Layer 2 (obstudio)     |
|---------------------------|--------------------|------------------------|
| Run Observer              | Manual server start | `obstudio start`       |
| Install skills            | Manual file copy    | `obstudio skills install --agent cursor` |
| Register with AI tools    | Manual config edit  | `obstudio register --agent cursor` |
| Lifecycle management      | None               | Start, stop, restart, health check |
| Cross-platform binary     | Source code         | Single binary, zero deps |

### Why Go

Native OTLP/gRPC support. Single binary distribution. The OpenTelemetry
Collector ecosystem is Go. Cross-compilation to all platforms without external
toolchains.

### MCP Tools

The MCP server exposes four tools that let agents inspect telemetry produced by
the instrumented application:

| MCP Tool                     | What It Does                                           |
|------------------------------|--------------------------------------------------------|
| `observer_metrics_overview`  | List metrics with filters (name, service, type, scope) |
| `observer_metric_detail`     | Fetch one metric by name with full datapoint history   |
| `observer_traces_overview`   | List recent traces with span previews and status       |
| `observer_trace_detail`      | Fetch one trace by ID with all spans, events, links    |

Every AI tool talks to the same endpoint: `http://localhost:3000/mcp`. No
editor-specific protocol, no custom integration. Standard MCP over Streamable
HTTP.

---

## Layer 3: Distribution

Layer 3 is how obstudio reaches developers. It changes nothing about the
product. It is packaging, delivery, and convenience.

### Channel 1: Native Agentic Installation (Primary)

obstudio can install itself directly into any AI coding environment. No
extension, no marketplace, no intermediary. The developer runs a single command
and the AI tool gains full access to skills and MCP tools.

```bash
$ obstudio register --agent cursor
  ✓ MCP server added to ~/.cursor/mcp.json
  ✓ Skills installed to ~/.cursor/skills/obstudio/

$ obstudio register --agent claude-code
  ✓ MCP server added to ~/.claude/settings.json
  ✓ Skills installed to .claude/skills/obstudio/

$ obstudio register --agent codex
  ✓ MCP server added to ~/.codex/config.json
  ✓ Skills installed to ~/.codex/skills/obstudio/
```

This is the primary distribution path because it matches how the product is
used: AI agents consume skills and MCP tools. The registration puts those
resources exactly where the agent expects them.

| AI Tool      | MCP Config Location               | Skill Location                    |
|--------------|-----------------------------------|-----------------------------------|
| Cursor       | `~/.cursor/mcp.json`              | `~/.cursor/skills/obstudio/`      |
| Claude Code  | `~/.claude/settings.json`         | `.claude/skills/obstudio/`        |
| Codex        | `~/.codex/config.json`            | `~/.codex/skills/obstudio/`       |
| Generic      | Project `.mcp.json`               | Project `.agents/skills/obstudio/`|

After registration, the developer starts obstudio and the AI agent discovers it
automatically via MCP `tools/list`. No extension needed.

### Channel 2: VS Code Extension

The extension is a thin wrapper (~400 lines of TypeScript) that automates what
`obstudio start` and `obstudio register` do manually. It adds three conveniences
specific to the VS Code environment:

1. **Auto-start**: spawns the obstudio binary when the editor opens
2. **Embedded UI**: opens the web explorer in an editor panel instead of a browser tab
3. **One-click config**: adds OTLP env vars to `.vscode/launch.json` for debug sessions

The extension does **not** contain:

- OTLP ingest logic (Layer 1: Observer)
- DuckDB or storage (Layer 1: Observer)
- MCP protocol handling (Layer 1: Observer)
- Telemetry query logic (Layer 1: Observer)
- Web UI rendering (Layer 1: Observer)
- Skill content (Layer 1: Skills)

Everything the extension does, the CLI does too. The extension is a convenience
wrapper for developers who prefer a marketplace install and embedded panels.

```
┌───────────────────────────────────────────────────────┐
│  VS Code / Cursor                                     │
│                                                       │
│  ┌─────────────────────────────────────────────────┐  │
│  │  Extension (~400 LoC)                           │  │
│  │                                                 │  │
│  │  activate()                                     │  │
│  │    ├─ findOrDownloadBinary("obstudio")           │  │
│  │    ├─ spawn("obstudio", ["start"])               │  │
│  │    ├─ waitForPort(3000)                          │  │
│  │    ├─ registerMcpServer("http://localhost:3000") │  │
│  │    └─ showStatusBarItem()                        │  │
│  │                                                 │  │
│  │  commands:                                      │  │
│  │    openExplorer()                               │  │
│  │      └─ webviewPanel(iframe → localhost:3000)   │  │
│  │    installSkills()                              │  │
│  │      └─ spawn("obstudio", ["skills", "install"])│  │
│  │    configureDebugLaunch()                       │  │
│  │      └─ update .vscode/launch.json              │  │
│  │                                                 │  │
│  │  deactivate()                                   │  │
│  │    └─ kill obstudio process                     │  │
│  └──────────┬──────────────────────────────────────┘  │
│             │ child process                           │
│             ▼                                         │
│  ┌──────────────────────────────────┐                 │
│  │  obstudio binary (Go)            │                 │
│  │                                  │                 │
│  │  localhost:3000  Web UI + MCP    │◄── webview      │
│  │  localhost:4318  OTLP/HTTP       │◄── instrumented │
│  │  localhost:4317  OTLP/gRPC       │    app          │
│  └──────────────────────────────────┘                 │
└───────────────────────────────────────────────────────┘
```

#### Binary Distribution Strategy

The extension needs the obstudio binary. Three options, in order of preference:

| Strategy | How It Works | Tradeoff |
|---|---|---|
| **Bundled per platform** | Extension includes pre-built binaries for darwin-arm64, darwin-x64, linux-x64, win32-x64. VS Code supports platform-specific extensions via `--target`. | Larger extension size (~20-30MB), but zero setup for user. |
| **Download on first use** | Extension downloads the correct binary from GitHub releases on activation. | Smaller extension, but requires network on first run. |
| **Expect pre-installed** | Extension checks `PATH` for `obstudio`. If missing, prompts user to install via `brew install obstudio`. | Smallest extension, but requires user action. |

Recommendation: **Bundled per platform** for the VS Code Marketplace release
(seamless install experience), with a fallback to PATH lookup so developers who
installed via Homebrew or `go install` use their existing binary.

### Channel 3: CLI Install

For developers who prefer terminal-first workflows or use AI tools that don't
have a marketplace (Claude Code, Codex, terminal agents):

```bash
# macOS / Linux
brew install obstudio

# Any platform with Go
go install github.com/signalfx/obstudio/go/cmd/obstudio@latest

# Direct binary download
curl -fsSL https://github.com/signalfx/obstudio/releases/latest/download/obstudio-$(uname -s)-$(uname -m) -o obstudio
chmod +x obstudio
```

After install, `obstudio register --agent <name>` configures the AI tool.

---

## Marketplace Precedent

The "native tool + extension as distribution" pattern is well-established. The
most successful developer tools in the VS Code ecosystem follow exactly this
architecture: the real product is a standalone binary, and the extension is a
thin wrapper that manages its lifecycle and provides editor-specific UI.

| Extension | Native Tool | What the Extension Does |
|---|---|---|
| **Docker** (`ms-azuretools.vscode-docker`) | Docker CLI + Engine | Drives `docker` commands, provides container/image tree views. The engine runs independently. |
| **Go** (`golang.go`) | `gopls` + Go toolchain | Spawns `gopls` as a language server subprocess. All intelligence lives in gopls. |
| **ESLint** (`dbaeumer.vscode-eslint`) | `eslint` binary | Runs ESLint from workspace `node_modules` via LSP bridge. Linting logic is entirely in the eslint package. |
| **Terraform** (`hashicorp.terraform`) | `terraform-ls` + `terraform` CLI | Wraps the language server for editing, invokes the CLI for plan/apply. |
| **Rust Analyzer** | `rust-analyzer` binary | Downloads or locates the binary, spawns it, provides LSP integration. All analysis lives in the standalone tool. |
| **OTelMe** (`digitarald.vscode-otelme`) | Local OTLP receiver | Closest parallel in the observability space. Runs a local collector, stores telemetry, enables Copilot-oriented querying. |

The architectural pattern across all of these:

```
┌─────────────────────────────────────────────────────────────┐
│  Extension (thin)                                           │
│    ├─ Lifecycle: find/download/spawn the native tool        │
│    ├─ Transport: LSP, HTTP, or CLI invocation               │
│    └─ UI: tree views, webviews, problems, status bar        │
│                                                             │
│  Native Tool (all the logic)                                │
│    ├─ Works without VS Code                                 │
│    ├─ Installable via system package manager                │
│    └─ Used by other editors and CI systems                  │
└─────────────────────────────────────────────────────────────┘
```

obstudio follows this pattern. The Go binary is the product. The extension is
one of several distribution channels.

### Why This Matters for Observability Studio

OTelMe demonstrates that the VS Code marketplace already has demand for local
OpenTelemetry tooling. The difference with obstudio is reach: OTelMe is locked
to VS Code. obstudio works with every AI coding tool via MCP, and the extension
is optional.

---

## Native Installation Mechanism

`obstudio register` is the mechanism that makes native agentic installation
work. It writes the minimum configuration needed for an AI tool to discover
obstudio's MCP server and skills.

### What `obstudio register` Does

For each supported AI tool, `register` performs two writes:

1. **MCP config**: adds an entry to the tool's MCP configuration file so the
   agent can discover obstudio's tools at `http://localhost:3000/mcp`.
2. **Skills**: copies skill files to the location the tool expects so the agent
   can read instrumentation expertise.

### Per-Tool Details

#### Cursor

```bash
$ obstudio register --agent cursor
```

Writes to `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "obstudio": {
      "url": "http://localhost:3000/mcp"
    }
  }
}
```

Copies skills to `~/.cursor/skills/obstudio/`.

**Workflow after registration:**

```
User:     "Instrument my Go service with OpenTelemetry"

Cursor:   1. Reads ~/.cursor/skills/obstudio/instrument/SKILL.md
             Reads ~/.cursor/skills/obstudio/instrument/go.md
          2. Adds OTel SDK, tracer/meter init, spans, metrics to the code
          3. Creates/updates .vscode/launch.json with OTLP env vars

User:     Runs the app (F5 or terminal)

User:     "Check if my instrumentation is producing correct telemetry"

Cursor:   4. Calls MCP tool: observer_traces_overview {}
             → Sees 12 traces, 3 have status "error"
          5. Calls MCP tool: observer_trace_detail { traceId: "abc123..." }
             → Sees span "db.query" missing error status on exception
          6. Calls MCP tool: observer_metrics_overview { serviceName: "my-svc" }
             → Sees http.server.duration metric, but no db.client.duration
          7. Fixes the code: adds error status to db span, adds db metric
          8. "Restart your app — I've fixed 2 issues:
              - db.query spans now record error status on exceptions
              - Added db.client.duration histogram"
```

#### Claude Code (terminal)

```bash
$ obstudio register --agent claude-code
```

Writes to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "obstudio": {
      "url": "http://localhost:3000/mcp"
    }
  }
}
```

Copies skills to `.claude/skills/obstudio/` in the project root.

**Workflow after registration:**

```
$ claude

User:     "Instrument this Python Flask app with OpenTelemetry and
           verify the telemetry looks correct"

Claude:   1. Reads .claude/skills/obstudio/instrument/SKILL.md
             Reads .claude/skills/obstudio/instrument/python.md
          2. Adds opentelemetry-sdk, opentelemetry-instrumentation-flask
             to requirements.txt
          3. Creates otel_setup.py with TracerProvider, MeterProvider
          4. Wraps app entrypoint with OTel initialization
          5. Runs: OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
                   python app.py
          6. Sends a few test requests: curl http://localhost:8080/api/users

          7. Calls MCP tool: observer_traces_overview { serviceName: "flask-app" }
             → "I see 3 traces. Let me check the details."
          8. Calls MCP tool: observer_trace_detail { traceId: "def456..." }
             → "The /api/users endpoint produces a root span with 2 child
                spans (db.query, redis.get). Attributes look correct.
                service.name=flask-app. Spans have proper status codes."
          9. Calls MCP tool: observer_metrics_overview {}
             → "I see http.server.request.duration and
                http.server.active_requests. Both use correct semantic
                conventions."
         10. "Instrumentation looks good. 3 traces verified, 2 metrics
              confirmed. No issues found."
```

#### OpenAI Codex (CLI)

```bash
$ obstudio register --agent codex
```

Writes to `~/.codex/config.json`:

```json
{
  "mcpServers": {
    "obstudio": {
      "url": "http://localhost:3000/mcp"
    }
  }
}
```

Copies skills to `~/.codex/skills/obstudio/`.

**Workflow after registration:**

```
$ codex

User:     "Add OpenTelemetry instrumentation to this Java Spring Boot
           service, then check the telemetry is valid"

Codex:    1. Reads skills from ~/.codex/skills/obstudio/instrument/
          2. Adds OTel SDK dependencies to pom.xml
          3. Creates OtelConfig.java with SDK initialization
          4. Adds @WithSpan annotations, custom metrics
          5. Runs the app with OTLP endpoint set to localhost:4318

          6. Calls MCP tool: observer_traces_overview {}
             → Lists 8 traces from "spring-boot-app"
          7. Calls MCP tool: observer_metric_detail
                { metricName: "http.server.request.duration" }
             → Shows histogram buckets, p50/p99 values
          8. Calls MCP tool: observer_traces_overview { status: "error" }
             → "1 trace has errors. Let me investigate."
          9. Calls MCP tool: observer_trace_detail { traceId: "789abc..." }
             → "Span 'UserRepository.findById' threw NPE but span status
                is UNSET instead of ERROR. Fixing."
         10. Fixes UserRepository, sets span status on exception
         11. "Fixed. Re-run the app to verify."
```

#### Any MCP-Compatible Tool (generic)

For tools that support MCP but don't have a skill convention, the developer
points their tool at the MCP endpoint and the agent discovers available tools
automatically via the standard MCP `tools/list` handshake:

```
Agent → POST http://localhost:3000/mcp
        { "method": "tools/list" }

Server → {
  "tools": [
    { "name": "observer_metrics_overview", ... },
    { "name": "observer_metric_detail", ... },
    { "name": "observer_traces_overview", ... },
    { "name": "observer_trace_detail", ... }
  ]
}
```

No skills needed for basic telemetry inspection. Skills add instrumentation
expertise, but the MCP tools work independently for any agent that wants to
query telemetry.

---

## The Distribution Comparison

Three ways to get the same product:

| Path | Install | Start | Register | UI |
|---|---|---|---|---|
| **Native (CLI)** | `brew install obstudio` | `obstudio start` | `obstudio register --agent cursor` | Browser at `localhost:3000` |
| **VS Code Extension** | Marketplace install | Automatic on editor open | Automatic on activation | Embedded webview panel |
| **Manual** | `go install` or binary download | `obstudio start` | Edit MCP config by hand | Browser at `localhost:3000` |

All three paths result in the same running product: same Observer, same MCP
tools, same skills, same web UI. The developer chooses based on preference. The
extension is the most convenient for VS Code/Cursor users. The CLI is the most
universal.

---

## The Rule

**Every capability must work at Layer 2. Layer 3 only adds convenience.**

If a feature only works inside a VS Code extension, it is built wrong. Every
capability — telemetry visualization, validation, MCP queries, skill-driven
instrumentation — must work via `obstudio start` + `obstudio register`. Editor
extensions, marketplace listings, and package manager formulae are delivery
mechanisms.

---

## Development Phases

| Phase | Layer | Deliverable                        | Outcome                                      |
|-------|-------|------------------------------------|-----------------------------------------------|
| 1     | 1     | Observer: OTLP ingest + web UI    | Run Observer, view telemetry in browser       |
| 2     | 1     | Observer: MCP server               | AI agents can query telemetry                 |
| 3     | 1     | Skills: Instrumenter (multi-lang)  | AI agents can instrument code                 |
| 4     | 2     | obstudio binary: CLI + lifecycle   | `obstudio start`, `obstudio register`         |
| 5     | 2     | Validator (OTel Weaver integration)| Conformance checks via CLI and MCP            |
| 6     | 3     | VS Code extension (thin wrapper)   | Marketplace distribution for VS Code/Cursor   |
| 7     | 3     | Homebrew formula + binary releases | CLI distribution for all platforms             |
| 8     | 1     | Skills: Terraformer                | Splunk O11y Cloud terraform generation        |

Each phase delivers a complete, testable unit at its layer. Layer 1 phases are
usable immediately without waiting for Layer 2 or 3. Layer 2 composes Layer 1
into a product. Layer 3 distributes it.

---

## What We Keep From the Prototype

The existing Node.js prototype validated the concept: OTLP ingest, DuckDB
storage, real-time web UI, MCP tools, and the Instrumenter skill. The Go rewrite
carries forward the same design — same SQL schemas, same MCP tool definitions,
same skill content — in a language the team ships in.

The prototype also validated the extension model: the current VS Code extension
already spawns the Observer as a child process and delegates all logic to it.
The layered architecture makes this pattern explicit and extends it to every
distribution channel.
