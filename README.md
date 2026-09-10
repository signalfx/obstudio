# Observability Studio

Observability Studio is a local OpenTelemetry workspace for developers. It
receives traces, metrics, and logs; provides a browser UI, REST API, and MCP
server; and ships agent skills for auditing, instrumenting, verifying, and
operationalizing telemetry.

## Quick start

### Install a release

Download the archive for your platform from
[Releases](https://github.com/signalfx/obstudio/releases/latest), extract it,
and run the installer from that directory:

```bash
./obstudio install --target=codex
```

Use a single target or a comma-separated list. The installer supports `codex`,
`claude-code`, `cursor`, `kiro`, `windsurf`, and `copilot`. GitHub Copilot gets
the local MCP connection only because it does not support this skill layout.

Keep the bundled `weaver` executable beside `obstudio`. Restart each selected
agent after installation, then start a new task so it reloads its skills and
MCP configuration.

Run Observer in the foreground with `./obstudio`, or manage a background
process from the extracted directory:

```bash
./obstudio start
./obstudio status
./obstudio restart
./obstudio stop
```

Installing a newer build does not restart a running Observer. Run
`./obstudio restart` when you are ready to use the new binary.

### Build from source

Requirements: Go 1.25+, Node.js 22+, npm, and `uv`. Docker is optional and is
used only by runtime evals.

```bash
make run
```

`make run` builds the binary and starts Observer with these endpoints:

| Service | Default endpoint |
|---|---|
| Observer UI and REST API | `http://127.0.0.1:3000` |
| MCP | `http://127.0.0.1:3000/mcp` |
| OTLP/HTTP | `http://127.0.0.1:4318` |
| OTLP/gRPC | `127.0.0.1:4317` |

Use `./build/obstudio --observer-http-port <port>` to move the UI, REST API,
and MCP endpoint. The OTLP ports remain `4318` and `4317`.

For UI development, run the collector and client watcher in separate terminals:

```bash
make build-client
cd observer
go run -tags dev ./cmd/obstudio
```

```bash
make dev
```

The development build serves client assets from disk and reloads open Observer
tabs after a client rebuild. See [CONTRIBUTING.md](CONTRIBUTING.md) for the full
development workflow.

## Using the skills

The skills form one reviewable path from source code to production resources:
**audit → select → instrument → verify → configure → publish**.

- `$otel-audit` finds observability gaps without modifying application code.
- `$otel-instrument` implements approved SDK, auto-instrumentation, and
  custom-signal changes.
- `$otel-verify` proves existing instrumentation with project, code, and
  optional local OTLP checks.
- `$splunk-dashboard` generates dashboard Terraform and previews it against
  local telemetry.
- `$splunk-configure` generates evidence-backed detector and dashboard
  Terraform.
- `$splunk-detector-publish` compares detector specs with Splunk and creates
  confirmed gaps.
- `$splunk-dashboard-publish` compares dashboards and charts with Splunk and
  creates confirmed gaps.
- `$connect-splunk-observability-cloud` opens the local Cloud view for secure
  connection setup.
- `$create-splunk-free-account` submits a consent-gated Splunk Observability
  Cloud Free Edition signup.

The skill names above use Codex syntax. Use `/skill-name` in Claude Code,
Cursor, Kiro, or Devin Local, and `@skill-name` in legacy Cascade. The
deprecated `$splunk-sync` and `$splunk-dashboard-sync` aliases remain for
compatibility; use the publisher names above for new work.

### 1. Audit and select

Run `$otel-audit` from the service root. It writes canonical audit data to
`.observe/otel-audit.json` and a self-contained review UI to
`.observe/otel.html`.

Open the tokenized local link returned by the skill, choose the findings
to address, and run the generated `$otel-instrument` command. Keep its finding
IDs, decisions, and validated service root unchanged. You can also select known
findings directly:

```text
$otel-instrument --ids OTEL-001,OTEL-004
```

### 2. Instrument and verify

`$otel-instrument` records the validated selection before editing and runs
`$otel-verify` by default after its implementation gate. It writes a separate
`.observe/otel-instrumentation.html` report that connects each selected gap to
the change, emitted telemetry, product impact, and proof.

Run `$otel-verify` again whenever you need fresh evidence. Verification writes
`.observe/otel-verify.json` and `.observe/otel-verify.md`. See
[OTel Verify](docs/otel-verify.md) for the verification contract.

HTML reports are served only through user-clicked, tokenized local links and
are never opened automatically. JSON and Markdown reports remain local files.

### 3. Configure and publish

Use `$splunk-dashboard` for a dashboard-only workflow, or
`$splunk-configure` to generate detector and dashboard Terraform from the audit
and verification evidence. The publisher skills compare those specs with live
Splunk state, show the diff, and require confirmation before creating missing
resources.

## Observer

Send OTLP data to `127.0.0.1:4317` or `http://127.0.0.1:4318`, then open
`http://127.0.0.1:3000`. Observer provides focused views for services, traces,
metrics, logs, semantic-convention validation, dashboard previews, and optional
Splunk Observability Cloud export.

REST and MCP validation APIs are documented in
[observer/README.md](observer/README.md), along with retention and routing.

### Collect coding-agent token telemetry

Token telemetry is an explicit opt-in for Codex and Claude Code:

These commands assume the extracted release directory. Source builds use
`./build/obstudio` instead.

```bash
./obstudio token-telemetry enable \
  --target=codex,claude-code
./obstudio token-telemetry status \
  --target=codex,claude-code
./obstudio token-telemetry disable \
  --target=codex,claude-code
```

`enable` takes ownership of recognized provider OTLP routes; there is no
separate force flag. Replaced destinations are not saved or restored. `disable`
removes only unchanged Obstudio-managed values, while values edited after
enablement are preserved.

New targets default to `--repository-correlation=path`, which supports exact
path queries. Use `name` to omit filesystem paths or `off` to disable normalized
repository correlation. Omitting the option for an existing target preserves
its recorded mode. Raw provider telemetry can still contain provider-supplied
working-directory data.

Restart every affected provider process after changing its exporter. Claude
Desktop Setup profiles can override user-level Claude Code routing, and the
`claude-code` target does not edit those profiles. See
[the token-usage guide](observer/README.md#audit-token-usage-demo) for provider
precedence, supported exporter shapes, retention, and Desktop troubleshooting.

### Forward metrics and traces to Splunk

Remote export is optional. Observer always accepts traces, metrics, and logs
locally, but forwards only traces and metrics to Splunk Observability Cloud.
Logs remain in the local Logs view.

Create `~/.obstudio/env` with permissions `0600`:

```dotenv
OBSTUDIO_SPLUNK_METRICS_EXPORT=true
OBSTUDIO_SPLUNK_TRACES_EXPORT=true
SPLUNK_REALM=<your-realm>
SPLUNK_ACCESS_TOKEN=<org-ingest-token>
```

The token must have ingest scope. Shell variables override the env file; pass
`--env-file <path>` when starting Observer to select another file. Tokens are
accepted only on writes and are not returned by status APIs. Endpoint and
timeout overrides are documented in the
[user guide](docs/USER.md#environment-variables).

## Repository map

| Path | Contents |
|---|---|
| `observer/` | Go collector, OTLP receivers, REST and MCP APIs, and React UI. |
| `extension/` | VS Code-compatible extension and marketplace documentation. |
| `skills/` | Canonical agent skill sources. |
| `.agents/skills/` | Repo-local Codex discovery links. |
| `evals/` | Fixture services and skill eval cases. |
| `pytest-codex-evals/` | Reusable pytest plugin for the eval harness. |
| `eval-reports/` | Latest summarized eval results. |
| `docs/` | User, design, and workflow documentation. |

Common commands:

| Command | Purpose |
|---|---|
| `make build` | Build `obstudio` with embedded skills and client assets. |
| `make run` | Build and start Observer. |
| `make test` | Run Go tests. |
| `make test-client` | Run React client tests. |
| `make test-extension` | Run extension tests. |
| `make test-all` | Run the main Go, client, extension, and skill-script suites. |
| `make agent-policy-check` | Validate agent-policy and skill-discovery rules. |
| `make help` | List the remaining build, eval, and release targets. |

See [evals/README.md](evals/README.md) for skill evals and
[CONTRIBUTING.md](CONTRIBUTING.md) for testing, pull requests, and releases.

## Security and privacy

Review [Security](plugins/obstudio/SECURITY.md) and
[Privacy](plugins/obstudio/PRIVACY.md) before enabling Cloud export, account
creation, or publisher skills.

## License

Apache License 2.0. See [LICENSE](LICENSE).
