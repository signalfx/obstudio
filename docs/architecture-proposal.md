# Observability Studio — Layered Architecture

## The Layering Principle

Observability Studio is a layered product where each layer is independently useful and the outermost layer
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
│  │  │  │  terraform/      │    │    Storage            │   │  │  │
│  │  │  │  (agent-readable │    │  Query API (REST)     │   │  │  │
│  │  │  │   markdown)      │    │  MCP server           │   │  │  │
│  │  │  │                  │    │  Web UI               │   │  │  │
│  │  │  │                  │    │  Validator            │   │  │  │
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
Instrumenter, Terraformer, and Splunk-sync skills are agent skills. The Telemetry
Explorer and Validator produce data that agents consume via MCP, but the
Telemetry Explorer also stands on its own as a live telemetry viewer — no agent
workflow required.

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
codebase and which semantic conventions to follow.

```
skills/
├── otel-audit/        # Scan a service for observability coverage gaps
├── otel-instrument/   # Add OTel auto-instrumentation and custom signals
├── otel-verify/       # Prove app instrumentation and local OTLP visibility
├── splunk-configure/  # Generate Splunk O11y detector Terraform from an audit
└── splunk-sync/       # Diff local detector specs against live Splunk detectors;
                       # create only the confirmed gaps via the Splunk REST API
```

Skills are plain files. They require no runtime, no server, no binary. Any AI
agent that can read files can use them. This is Layer 1 — it works on its own.

### Observer — Local Telemetry Backend

The Observer is a local server that receives, stores, and exposes OpenTelemetry
data. It provides four surfaces:


| Surface             | Protocol                       | Purpose                                                 |
| ------------------- | ------------------------------ | ------------------------------------------------------- |
| OTLP receiver       | HTTP `:4318`, gRPC `:4317`     | Ingest traces, metrics, logs from instrumented services |
| Splunk forwarding   | OTLP/HTTP to Splunk ingest     | Mirror received metrics and traces to Splunk O11y Cloud |
| Query API           | REST on `:3000`                | Structured access to stored telemetry                   |
| MCP server          | Streamable HTTP on `:3000/mcp` | AI agents query telemetry programmatically              |
| Web UI              | HTTP on `:3000`                | Visual trace/metric/log explorer                        |

Splunk forwarding is optional. Set `SPLUNK_ACCESS_TOKEN` and `SPLUNK_REALM` to
enable it. The same token is used by `$splunk-sync` to read and create detectors
via the Splunk REST API (`GET`/`POST /v2/detector`).


The Observer is also Layer 1. It has no knowledge of skills, no CLI wrapper, and
no editor integration. It is a server that receives OTLP and answers questions
about what it received.

### How They Compose

Skills tell the agent *what to do*. The Observer tells the agent *what happened*.
Together they form a closed loop:

```
┌──────────────────────────────────────────────────────────────┐
│  1. Agent reads $otel-audit → finds coverage gaps            │
│  2. Agent reads $otel-instrument → adds OTel SDK + signals   │
│  3. $otel-verify runs app-code and runtime scenarios         │
│  4. App may send OTLP to Observer for local runtime proof    │
│  5. Observer stores telemetry and may forward it to Splunk   │
│  6. $otel-verify queries evidence and writes its report      │
│  7. Agent reads $splunk-configure → generates detectors.tf   │
│  8. Agent reads $splunk-sync → creates only the gap detectors│
│  9. Agent fixes instrumentation issues → go to step 3        │
└──────────────────────────────────────────────────────────────┘
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


| Capability               | Layer 1 (Core)      | Layer 2 (obstudio)                         |
| ------------------------ | ------------------- | ------------------------------------------ |
| Run Observer             | Manual server start | `obstudio start`                           |
| Install skills           | Manual file copy    | `obstudio install --target=<agent>`        |
| Register with AI tools   | Manual config edit  | Handled by `obstudio install`              |
| Lifecycle management     | None                | Start, stop, restart, health check         |
| Cross-platform binary    | Source code         | Single binary, zero deps                   |
| Forward to Splunk O11y   | None                | `SPLUNK_ACCESS_TOKEN` + `SPLUNK_REALM`     |
| Sync detectors to Splunk | None                | `$splunk-sync` via Splunk REST API         |


### Why Go

Native OTLP/gRPC support. Single binary distribution. The OpenTelemetry
Collector ecosystem is Go. Cross-compilation to all platforms without external
toolchains.

### MCP Tools

The MCP server exposes tools that let agents inspect local telemetry and control
the observer:

| MCP Tool                       | What It Does                                            |
| ------------------------------ | ------------------------------------------------------- |
| `observer_metrics_overview`    | List metrics with filters (name, service, type, scope)  |
| `observer_metric_detail`       | Fetch one metric by name with full datapoint history    |
| `observer_traces_overview`     | List recent traces with span previews and status        |
| `observer_trace_detail`        | Fetch one trace by ID with all spans, events, links     |
| `observer_logs_overview`       | List recent log records with filters                    |
| `observer_validation_status`   | Return validator state and result freshness             |
| `observer_validation_analyze`  | Run or return OTel convention validation analysis       |
| `observer_validation_refresh`  | Force a fresh validation run against current telemetry  |
| `observer_clear`               | Clear all in-memory telemetry                           |
| `observer_status`              | Return collector endpoints and telemetry stats          |

Every AI tool talks to the same endpoint: `http://localhost:3000/mcp`. No
editor-specific protocol, no custom integration. Standard MCP over Streamable
HTTP.

Splunk detector operations (`$splunk-sync`) call the Splunk REST API directly
(`GET`/`POST /v2/detector`) — they do not go through the obstudio MCP server.

---

## Layer 3: Distribution

Layer 3 is how obstudio reaches developers. It changes nothing about the
product. It is packaging, delivery, and convenience.

Two channels are described below. To avoid scope creep we start with these and
expand to additional channels (e.g. Homebrew, `go install`) once the core
product is stable.

### Channel 1: Native Agentic Installation

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


| AI Tool     | MCP Config Location       | Skill Location                     |
| ----------- | ------------------------- | ---------------------------------- |
| Cursor      | `~/.cursor/mcp.json`      | `~/.cursor/skills/obstudio/`       |
| Claude Code | `~/.claude/settings.json` | `.claude/skills/obstudio/`         |
| Codex       | `~/.codex/config.json`    | `~/.codex/skills/obstudio/`        |
| Generic     | Project `.mcp.json`       | Project `.agents/skills/obstudio/` |


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


| Strategy                  | How It Works                                                                                                                                            | Tradeoff                                                   |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| **Bundled per platform**  | Extension includes pre-built binaries for darwin-arm64, darwin-x64, linux-x64, win32-x64. VS Code supports platform-specific extensions via `--target`. | Larger extension size (~20-30MB), but zero setup for user. |
| **Download on first use** | Extension downloads the correct binary from GitHub releases on activation.                                                                              | Smaller extension, but requires network on first run.      |
| **Expect pre-installed**  | Extension checks `PATH` for `obstudio`. If missing, prompts user to install via `brew install obstudio`.                                                | Smallest extension, but requires user action.              |


Recommendation: **Bundled per platform** for the VS Code Marketplace release
(seamless install experience), with a fallback to PATH lookup so developers who
installed via Homebrew or `go install` use their existing binary.

---

## Marketplace Precedent

The "native tool + extension as distribution" pattern is well-established. The
most successful developer tools in the VS Code ecosystem follow exactly this
architecture: the real product is a standalone binary, and the extension is a
thin wrapper that manages its lifecycle and provides editor-specific UI.


| Extension                                  | Native Tool                      | What the Extension Does                                                                                                   |
| ------------------------------------------ | -------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| **Docker** (`ms-azuretools.vscode-docker`) | Docker CLI + Engine              | Drives `docker` commands, provides container/image tree views. The engine runs independently.                             |
| **Go** (`golang.go`)                       | `gopls` + Go toolchain           | Spawns `gopls` as a language server subprocess. All intelligence lives in gopls.                                          |
| **ESLint** (`dbaeumer.vscode-eslint`)      | `eslint` binary                  | Runs ESLint from workspace `node_modules` via LSP bridge. Linting logic is entirely in the eslint package.                |
| **Terraform** (`hashicorp.terraform`)      | `terraform-ls` + `terraform` CLI | Wraps the language server for editing, invokes the CLI for plan/apply.                                                    |
| **Rust Analyzer**                          | `rust-analyzer` binary           | Downloads or locates the binary, spawns it, provides LSP integration. All analysis lives in the standalone tool.          |
| **OTelMe** (`digitarald.vscode-otelme`)    | Local OTLP receiver              | Closest parallel in the observability space. Runs a local collector, stores telemetry, enables Copilot-oriented querying. |


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
OpenTelemetry tooling. obstudio differs in two ways:

- **Reach** — OTelMe is locked to VS Code. obstudio works with every AI coding
tool via MCP, and the extension is optional.
- **Capabilities** — obstudio adds agent-readable skills, validation, and
terraform generation that go beyond live telemetry viewing.

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

After registration the agent can read skills to learn how to instrument code
and call MCP tools to inspect live telemetry. Concrete workflows are defined in
the skills themselves and may evolve independently of this document.

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


| Path                  | Install                         | Start                    | Register                           | UI                          |
| --------------------- | ------------------------------- | ------------------------ | ---------------------------------- | --------------------------- |
| **Native (CLI)**      | `brew install obstudio`         | `obstudio start`         | `obstudio register --agent cursor` | Browser at `localhost:3000` |
| **VS Code Extension** | Marketplace install             | Automatic on editor open | Automatic on activation            | Embedded webview panel      |
| **Manual**            | `go install` or binary download | `obstudio start`         | Edit MCP config by hand            | Browser at `localhost:3000` |


All three paths result in the same running product: same Observer, same MCP
tools, same skills, same web UI. The developer chooses based on preference. The
extension is the most convenient for VS Code/Cursor users. The CLI is the most
universal.

---

## The Rule

**Every capability must work at Layer 2. Layer 3 only adds convenience.**

If a feature only works inside a VS Code extension, it is built wrong. Every
capability — telemetry visualization, validation, MCP queries, skill-driven
instrumentation — must work via `obstudio start` + `obstudio register`. 

The extension should be a thin shell: lifecycle management (start/stop the binary)
and editor-specific UI (webviews, status bar). Keeping extension code minimal
makes it straightforward to add plugins for other IDEs in the future.

---

## Development Components

Work is organized as independent components, not sequential phases. Components
within the same tier can progress in parallel. Dependencies between components
are shown explicitly so engineers can work independently.

### Core components (parallel tracks)


| Component    | Layer | Deliverable                                                                          | Depends On |
| ------------ | ----- | ------------------------------------------------------------------------------------ | ---------- |
| **Observer** | 1     | OTLP ingest, web UI, MCP server, Splunk metrics/traces forwarding                   | —          |
| **Skills**   | 1     | `$otel-audit`, `$otel-instrument`, `$otel-verify`, `$splunk-configure`, `$splunk-sync` (REST-direct) | —          |


Observer and Skills have no dependency on each other. They can be developed,
tested, and shipped by separate engineers or teams from day one.

### Integration components


| Component        | Layer | Deliverable                                    | Depends On       |
| ---------------- | ----- | ---------------------------------------------- | ---------------- |
| **obstudio CLI** | 2     | `obstudio start`, `obstudio register`          | Observer, Skills |
| **Validator**    | 2     | OTel Weaver conformance checks via CLI and MCP | Observer         |


The CLI composes Observer and Skills into a single binary and adds lifecycle
management. The Validator needs Observer's telemetry store but is otherwise
independent. Both can proceed once the Observer and Skills interfaces stabilize,
and can run in parallel with each other.

### Distribution


| Component             | Layer | Deliverable                                 | Depends On   |
| --------------------- | ----- | ------------------------------------------- | ------------ |
| **VS Code extension** | 3     | Marketplace distribution for VS Code/Cursor | obstudio CLI |


The extension is a thin wrapper around the CLI. It can begin development early
using the CLI's interface contract, but packaging and release depend on a stable
CLI.

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
