# Observability Studio

Local OpenTelemetry observability workspace -- receive, explore, and
validate telemetry during development. Includes AI agent skills that
audit codebases and add OpenTelemetry instrumentation automatically.

```
  AUDIT           INSTRUMENT      VERIFY
 ┌──────┐        ┌──────┐       ┌──────┐
 │ Scan │  ───>  │ Code │ ───>  │ Test │
 │ Gaps │        │ OTel │       │  Run │
 └──────┘        └──────┘       └──────┘
  /splunk-audit   /splunk-instrument  /splunk-verify

                /splunk-observe (chains all three)
```

---

## Commands

4 slash commands that map to the observability lifecycle. Each one
activates the right skill automatically.

| What you're doing | Command | Key principle |
|---|---|---|
| Find observability gaps | `/splunk-audit` | Measure before you instrument |
| Add OpenTelemetry code | `/splunk-instrument` | Auto + custom instrumentation |
| Validate telemetry flows | `/splunk-verify` | Evidence over assumption |
| Run the full pipeline | `/splunk-observe` | End-to-end in one command |

Skills also activate with natural language -- "instrument this service
with OpenTelemetry" triggers `/splunk-instrument`, and so on.

---

## Quick Start

### Install from Release

Download the latest zip for your platform from
[Releases](https://github.com/signalfx/obstudio/releases/latest), then:

```bash
unzip obstudio_*_darwin_arm64.zip
./obstudio install --target=cursor
```

This copies skills and references to `~/.cursor/skills/obstudio/` and
configures `~/.cursor/mcp.json` to auto-start the MCP server.

### Build from Source

```bash
make build    # compile the Go binary (skills embedded)
make run      # start the collector
```

The collector starts on:

| Service | URL |
|---|---|
| Telemetry Explorer | http://localhost:3000 |
| OTLP/HTTP | http://localhost:4318 |
| OTLP/gRPC | localhost:4317 |
| MCP endpoint | http://localhost:3000/mcp |

When telemetry is flowing, open the Telemetry Explorer and use the
**Validation** tab to run semantic validation against the current
in-memory snapshot. Validation findings are retained, grouped into
issues, and surfaced through the dedicated validation workflow.

### Use the Skills

In your AI coding agent, navigate to a service directory and run:

```
/splunk-observe
```

Or use individual skills:

```
/splunk-audit          # analyze gaps only
/splunk-instrument     # add OTel code (requires .observe/inventory.md)
/splunk-verify         # validate telemetry (requires instrumented code)
```

See [docs/examples.md](docs/examples.md) for more prompt examples.

### Run Validation

Validation is available through the Explorer UI, the REST API, and MCP.

1. Start `obstudio`
2. Send traces, metrics, and logs to the OTLP receiver
3. Open the **Validation** tab and run validation
4. Use the findings to jump back to the affected telemetry rows

Programmatic entry points:

| Surface | Entry points |
|---|---|
| REST | `/api/query/validation/summary`, `/api/query/validation/latest`, `/api/validation/run`, `/api/validation/refresh` |
| MCP | `observer_validation_status`, `observer_validation_analyze`, `observer_validation_refresh` |

---

## All 4 Skills

The commands above are the entry points. Each skill is a structured
workflow with steps, verification gates, and red flags. They follow the
[addyosmani/agent-skills](https://github.com/addyosmani/agent-skills)
anatomy.

### Analyze -- Understand what's missing

| Skill | What It Does | Use When |
|---|---|---|
| [splunk-audit](skills/splunk-audit/SKILL.md) | Scan a codebase for observability gaps, produce `.observe/inventory.md` with SLI definitions, signal tables (Spans/Metrics/Logs), fault domains, and component mapping | Starting observability work on any service |

### Build -- Add instrumentation

| Skill | What It Does | Use When |
|---|---|---|
| [splunk-instrument](skills/splunk-instrument/SKILL.md) | Implement OTel auto-instrumentation libraries and custom spans/metrics for every signal gap in the inventory | You have an inventory and need to write the code |

### Verify -- Prove it works

| Skill | What It Does | Use When |
|---|---|---|
| [splunk-verify](skills/splunk-verify/SKILL.md) | Start the Observer collector, exercise service APIs, and check traces and metrics against the inventory | Instrumentation is done and you need evidence it works |

### Orchestrate -- End-to-end

| Skill | What It Does | Use When |
|---|---|---|
| [splunk-observe](skills/splunk-observe/SKILL.md) | Chain audit → instrument → verify in sequence | You want full observability in one command |

---

## Shared References

Language guides and reference material live in `skills/references/`.
Skills load them on-demand to minimize token usage -- only the file
matching the detected language is loaded.

| Reference | Covers |
|---|---|
| [languages/go.md](skills/references/languages/go.md) | Go OTel SDK, auto-instrumentation, custom spans/metrics |
| [languages/node.md](skills/references/languages/node.md) | Node.js OTel SDK, Express/Fastify instrumentation |
| [languages/python.md](skills/references/languages/python.md) | Python OTel SDK, Flask/FastAPI/Django instrumentation |
| [fault-domain-patterns.md](skills/references/fault-domain-patterns.md) | Fault domain taxonomy and boundary detection |
| [signal-mapping-guide.md](skills/references/signal-mapping-guide.md) | SLI → OTel signal mapping (spans, metrics, logs) |
| [observability-template.md](skills/references/observability-template.md) | `.observe/inventory.md` template and format spec |

---

## Skill Contract

All skills operate on the same `.observe/` directory:

```
.observe/
└── inventory.md          # SLI definitions, signal tables (Spans/Metrics/Logs), components, fault domains
```

- `/splunk-audit` creates it (SLI definitions, signal tables)
- `/splunk-instrument` updates the Status column in Spans, Metrics, and Logs tables
- `/splunk-verify` updates the Verified column in Spans, Metrics, and Logs tables

---

## Repository Layout

```
obstudio/
├── observer/       # Primary collector, REST API, MCP server, and embedded web UI
├── extension/         # VS Code extension that packages the collector
├── skills/            # AI agent skills (composable workflows)
│   ├── splunk-audit/         #   /splunk-audit
│   ├── splunk-instrument/    #   /splunk-instrument
│   ├── splunk-verify/        #   /splunk-verify
│   ├── splunk-observe/       #   /splunk-observe
│   └── references/    #   Shared language guides and reference material
├── tests/             # Skill tests and LLM-based eval runner
├── examples/          # Sample apps for skill evaluation, organized by language
├── docs/              # Design docs, PRD, and example prompts
├── .github/workflows/ # CI (GitHub Actions)
├── Makefile           # Go build, test, release
├── AGENTS.md          # Guidelines for AI agents
└── CONTRIBUTING.md    # Dev process, PR workflow, releases
```

---

## CLI Reference

| Command | Description |
|---|---|
| `obstudio` | Start the collector + stdio MCP server (OTLP receiver, Web UI, REST API, MCP) |
| `obstudio install --target=<agent>` | Install skills and configure MCP (`cursor`, `claude-code`, `codex`) |
| `obstudio --version` | Print version |

---

## Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| Go | 1.25+ | observer collector |
| Node.js | 20+ | observer client dev/test and VS Code extension |
| npm | latest | Package management |
| uv | latest | Running Python example apps and tests |
| claude | latest | Skill evals (`make skill-eval`) -- optional |

---

## Development

### Make Targets

| Target | Description |
|---|---|
| `make build` | Build the `obstudio` binary (skills embedded) |
| `make run` | Build and start the collector |
| `make test` | Run all Go tests |
| `make vet` | Vet Go source |
| `make fmt` | Format Go source |
| `make tidy` | Tidy Go modules |
| `make list-skills` | List available skills |
| `make test-deterministic` | Run deterministic skill tests (no LLM calls) |
| `make skill-eval SKILL=<name>` | Run LLM-based skill evals and show report |
| `make skill-eval-all` | Run evals for all skills |
| `make release-local` | Build release archives locally via GoReleaser |
| `make clean` | Remove build artifacts |

### Skill Evals

Each skill has an `evals/` directory with LLM-based benchmarks that test
skill effectiveness against example apps. Evals run the skill via
`claude -p`, grade outputs against assertions, and compare with a
baseline (same task without the skill).

```bash
make skill-eval SKILL=splunk-audit      # run evals for one skill
make skill-eval SKILL=splunk-audit --id 1  # single eval case
make skill-eval-all                     # all skills
```

Results are written to `skill-eval-workspace/` (gitignored) with timing,
token usage, and pass rates. The `evals/` directories are dev-only and
are excluded from the release binary.

### CI

GitHub Actions runs on every push to `main` and `feature/**` branches:

- **observer** -- `go vet`, `make build`, `make test`
- **skill-tests** -- structural, semconv, and golden tests via `make test-deterministic`

See [.github/workflows/ci.yml](.github/workflows/ci.yml).

### Example Apps

The `examples/` directory contains sample apps organized by language.

| App | Stack | Run |
|---|---|---|
| `examples/python/flask-basic/` | Flask (in-memory) | `make dev` |
| `examples/python/fastapi-celery/` | FastAPI + Celery | `make dev` |
| `examples/node/express-basic/` | Express (in-memory) | `npm run dev` |
| `examples/go/chi-basic/` | Chi (in-memory) | `go run .` |

```bash
cd examples/python/flask-basic
make dev          # starts on :8000
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full development process
including PR workflow, review policy, testing requirements, and release
cadence.

See [AGENTS.md](AGENTS.md) for AI agent guidelines.

## License

Apache License 2.0 -- see [LICENSE](LICENSE).
