# Obstudio user guide

Obstudio gives coding agents an OpenTelemetry workflow and provides a local
Observer for inspecting the resulting traces, metrics, logs, and validation
evidence.

## Quick start

Download and extract the archive for your platform from
[GitHub Releases](https://github.com/signalfx/obstudio/releases/latest), then
change into the extracted directory:

```bash
cd obstudio_<version>_<os>_<arch>
```

Install one agent integration:

```bash
./obstudio install --target=codex
```

Use a comma-separated list to install more than one target.

To configure every target in one run:

```bash
./obstudio install --target=codex,claude-code,cursor,kiro,windsurf,copilot
```

| Target | Skill command |
|---|---|
| `codex` | `$otel-audit` |
| `claude-code`, `cursor`, or `kiro` | `/otel-audit` |
| `windsurf` with Devin Local | `/otel-audit` |
| `windsurf` with legacy Cascade | `@otel-audit` |
| `copilot` | Not available |

The `copilot` target configures MCP but does not install skills. The `windsurf`
skill bundle is also available to Devin Local, which needs the running
Observer added separately as described in the
[extension guide](../extension/README.md#install).

Where supported, installation copies the bundled skills, `obstudio`, and
`weaver` into the selected agent's managed directory. It also updates the MCP
configuration. Restart each agent after installation and begin a new task.

This guide runs the release binary as `./obstudio`. For a source build, use
`./build/obstudio` instead.

## Using the skills

The normal workflow is
**audit → select → instrument → verify → configure → publish**.

- `$otel-audit` finds observability gaps without changing application code.
- `$otel-instrument` implements approved SDK, auto-instrumentation, and
  custom-signal changes.
- `$otel-verify` rechecks instrumentation and refreshes proof.
- `$splunk-dashboard` generates dashboard Terraform and a local preview.
- `$splunk-configure` generates detector and dashboard Terraform from audit
  evidence.
- `$splunk-detector-publish` compares detectors with Splunk and creates
  confirmed gaps.
- `$splunk-dashboard-publish` compares dashboards and charts with Splunk and
  creates confirmed gaps.

The skill names above use Codex syntax. Use the prefix shown for your target
and keep the skill name and arguments unchanged.

### Audit, select, and instrument

1. Run `$otel-audit` from the service root.
2. Open the returned tokenized local report link.
3. Select the findings to fix and copy the generated `$otel-instrument`
   command.
4. Run that command without changing its finding IDs, decisions, or service
   path.
5. Review the verification proof that `$otel-instrument` produces by default.

If you already know the finding IDs, you can select them directly:

```text
$otel-instrument --ids OTEL-001,OTEL-004
```

Run `$otel-verify` later whenever application or runtime evidence has changed.

- `.observe/otel-audit.json` contains the source-derived audit findings.
- `.observe/otel.html` is the interactive audit and finding-selection report.
- `.observe/otel-selection.json` records approved finding IDs and decisions.
- `.observe/otel-instrumentation.md` is the developer-readable implementation
  record; `.observe/otel-instrumentation.json` is its machine-readable form.
- `.observe/otel-instrumentation.html` explains the changes, impact, and proof.
- `.observe/otel-verify.md` is the verification report;
  `.observe/otel-verify.json` is its machine-readable form in the canonical
  audit flow.

Audit and instrumentation are separate reports. Skills return user-clicked,
tokenized local links and never open them automatically. JSON and Markdown
artifacts remain local files. See [OTel Verify](otel-verify.md) for direct
verification guidance.

## Run Observer

Start Observer in the foreground:

```bash
./obstudio
```

Or manage a background process:

```bash
./obstudio start
./obstudio status
./obstudio restart
./obstudio stop
```

Installing a new build does not restart a running Observer. The lifecycle
commands manage only the standalone background process, not foreground or
extension-managed instances.

| Service | Default endpoint |
|---|---|
| Observer UI and REST API | `http://127.0.0.1:3000` |
| MCP | `http://127.0.0.1:3000/mcp` |
| OTLP/HTTP | `http://127.0.0.1:4318` |
| OTLP/gRPC | `127.0.0.1:4317` |

Use `./obstudio --observer-http-port 41234` to move the Observer UI, REST API,
and MCP endpoint. The OTLP receiver ports remain `4318` and `4317` unless you
change their environment variables.

### Send service telemetry

After installing an OpenTelemetry SDK or auto-instrumentation, run these
commands in the shell that starts your service:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=\
"http://127.0.0.1:4318"
export OTEL_EXPORTER_OTLP_PROTOCOL=\
"http/protobuf"
export OTEL_TRACES_EXPORTER=otlp
export OTEL_METRICS_EXPORTER=otlp
export OTEL_LOGS_EXPORTER=otlp
export OTEL_SERVICE_NAME=my-service
```

Start the service and exercise a real request. Observer accepts all three
signals. Open the Observer UI to inspect services, traces, metrics, logs,
semantic-convention findings, and dashboard previews.

Use **Validation** after telemetry arrives. For agent-driven analysis, ask what
is missing or incorrect; `observer_validation_analyze` uses the latest retained
result and reports when it is stale. Ask to refresh validation when you need a
new run. The [Observer guide](../observer/README.md) lists the common REST and
MCP entry points.

## Collect coding-agent token telemetry

Agent installation does not change Codex or Claude Code exporter settings.
Enable token telemetry explicitly:

```bash
./obstudio token-telemetry enable \
  --target=codex,claude-code
./obstudio token-telemetry status \
  --target=codex,claude-code
./obstudio token-telemetry disable \
  --target=codex,claude-code
```

`enable` takes ownership of recognized provider OTLP routes; it has no separate
force flag. Previous destinations are not saved or restored. `disable` removes
only unchanged Obstudio-managed values, while later edits remain untouched.

New targets use repository correlation mode `path`. Use `name` to omit
filesystem paths or `off` to disable normalized correlation. Omitting the flag
for an existing target preserves its recorded mode. Raw provider telemetry is
unchanged and can still include a provider-supplied working directory.

Restart every affected Codex or Claude process after changing routing. Claude
Desktop Setup profiles can override user-level Claude Code settings and are not
edited by `--target=claude-code`. See the
[token-usage demo](../observer/README.md#audit-token-usage-demo) for a complete
test, Desktop setup, retention behavior, and result interpretation.

## Forward to Splunk Observability Cloud

Observer can forward received traces and metrics while keeping the Observer UI
available. Logs remain local.

Create `~/.obstudio/env` with these values:

```dotenv
OBSTUDIO_SPLUNK_METRICS_EXPORT=true
OBSTUDIO_SPLUNK_TRACES_EXPORT=true
SPLUNK_REALM=<your-realm>
SPLUNK_ACCESS_TOKEN=<org-ingest-token>
```

Protect the file, then restart a managed background Observer. If Observer is
running in the foreground, stop it and launch it again instead.

```bash
chmod 600 ~/.obstudio/env
./obstudio restart
```

The default env file is loaded automatically when present. Shell environment
variables take precedence; use `./obstudio --env-file <path>` for another file.
Forwarding requires an organization access token with ingest scope.

Generating Terraform does not change Splunk. Publishing is a separate,
confirmation-gated action:

| Skill or action | Purpose |
|---|---|
| `$splunk-dashboard` | Generate dashboard Terraform and local preview data. |
| `$splunk-configure` | Generate evidence-backed detector and dashboard Terraform. |
| Open **Dashboards** | Compare generated layouts with current local telemetry. |
| `$splunk-detector-publish` | Show a live diff and create confirmed detector gaps. |
| `$splunk-dashboard-publish` | Show a live diff and create confirmed dashboard gaps. |

The local dashboard preview is approximate because SignalFlow runs in Splunk
Observability Cloud. Publisher skills require an API token with permission to
create their resources; an ingest-only token is not sufficient.

## CLI reference

| Command | Purpose |
|---|---|
| `./obstudio install --target=<agent>` | Install skills and configure MCP. |
| `./obstudio` | Run Observer in the foreground. |
| `./obstudio start` | Start the managed background Observer. |
| `./obstudio status` | Inspect the managed process and endpoints. |
| `./obstudio restart` | Restart the managed process with current settings. |
| `./obstudio stop` | Stop the managed process. |
| `./obstudio token-telemetry <action>` | Enable, inspect, or disable provider routing. |
| `./obstudio --version` | Print the installed version. |
| `./obstudio --help` | Show commands and flags. |

## Environment variables

Observer runtime:

- `PORT` sets the Observer UI, REST API, and MCP port. Default: `3000`.
- `OTLP_HTTP_PORT` sets the OTLP/HTTP receiver port. Default: `4318`.
- `OTLP_GRPC_PORT` sets the OTLP/gRPC receiver port. Default: `4317`.
- `OBSTUDIO_ENV_FILE` selects a startup env file. The default
  `~/.obstudio/env` is loaded when present.
- `OBSTUDIO_WORKSPACE_ROOT` sets the root for workspace-relative audit and
  dashboard files. It defaults to the current directory.
- `OBSTUDIO_AUDIT_REPORT` selects the audit shown in Overview. It defaults to
  `.observe/otel-audit.json`.

Splunk export:

- `SPLUNK_REALM` identifies the realm used for default ingest endpoints.
- `SPLUNK_ACCESS_TOKEN` supplies an ingest token for forwarding or an
  API-write token for publisher skills.
- `OBSTUDIO_SPLUNK_METRICS_EXPORT` and `OBSTUDIO_SPLUNK_TRACES_EXPORT` enable
  their respective exporters. Both default to `false`.
- `OBSTUDIO_SPLUNK_METRICS_ENDPOINT` and
  `OBSTUDIO_SPLUNK_TRACES_ENDPOINT` override the full ingest endpoints.
- `OBSTUDIO_SPLUNK_METRICS_TIMEOUT` and `OBSTUDIO_SPLUNK_TRACES_TIMEOUT` set
  request timeouts. Both default to `5s`.

## Troubleshooting

- **Observer will not start:** check the UI port and both OTLP ports.
  Change only the listener that is in use.
- **An agent cannot find skills or MCP:** restart the agent and open a new task.
  Existing processes keep their startup configuration.
- **A configured local Observer does not connect:** confirm that it is
  reachable and its version is compatible with the client.
- **Validation cannot run:** keep the bundled `weaver` executable beside
  `obstudio`, or make it available on `PATH`.
- **The extension shows Restart required:** open **Observer Status** and follow
  its recovery action. The extension will not stop a process it cannot verify.
- **A dashboard preview uses the wrong repository:** open the service as the
  first workspace folder and restart Observer.

## Security and data handling

Observer stores telemetry in bounded local memory. Cloud export, Free Edition
signup, and publisher skills are explicit external actions. The editor
extension stores Cloud access tokens in IDE secret storage.

Review the full [security](../plugins/obstudio/SECURITY.md) and
[privacy](../plugins/obstudio/PRIVACY.md) contracts before enabling external
actions.

## Resources

- [Observer guide](../observer/README.md)
- [Prompt examples](examples.md)
- [Skill sources](../skills/)
- [Contributing](../CONTRIBUTING.md)
