# Project Runtime Validation

Use this reference during `$otel-instrument` preflight and after every code or
runtime-config change. The goal is to validate instrumentation with the
repository's configured runtime, repair regressions introduced by the change,
and leave a deterministic handoff for `$otel-verify`.

## Runtime Candidate Inventory

Build this inventory before editing:

```markdown
| Surface | Config evidence | Candidate runner/env | Probe command | Outcome | Selected? |
|---|---|---|---|---|---|
```

Inspect candidates in this order:

1. Repository wrappers and checked-in task scripts.
2. Toolchain/version files.
3. Manifests and lockfiles.
4. Make, package, CI, devcontainer, and local-safe container test commands.
5. Existing local environments and tool-manager installations.
6. Global runtimes only when no project-specific choice exists.

Select the first candidate that matches project configuration and is locally
available. Probe the exact runtime before using it. A shell default rejected by
project config is not an application failure.

## Runtime Evidence By Ecosystem

### Java And Kotlin

- Prefer `./mvnw` or `./gradlew`; otherwise use installed Maven or Gradle with
  the project-selected JDK.
- Read Java versions from Maven compiler properties, toolchains,
  `.mvn/jvm.config`, Gradle toolchains, `.java-version`, `.sdkmanrc`,
  `.tool-versions`, or `mise.toml`.
- On macOS, inspect installed JDKs with `/usr/libexec/java_home -V`. Also
  consider SDKMAN, asdf, mise, and jenv when the repo references them.
- Probe with explicit `JAVA_HOME` and `PATH`.
- For Maven reactors, a focused `-Dtest=...` filter may fail in upstream
  modules with no matching tests. A no-match guard is allowed only for reactor
  traversal; inspect Surefire/Failsafe reports to prove the target test ran.

### Node And TypeScript

- Select the package manager from `packageManager`, then the lockfile.
- Respect `.nvmrc`, `.node-version`, `engines.node`, `.tool-versions`, and
  `mise.toml`; use Corepack when the project declares a manager version.
- Run package scripts or workspace-aware commands. Do not silently switch
  between npm, pnpm, Yarn, and Bun.

### Python

- Prefer an existing `.venv` or the declared runner: `uv run --locked`,
  `poetry run`, `pdm run`, `pipenv run`, `hatch run`, `tox`, or `nox`.
- Respect `.python-version`, `requires-python`, `runtime.txt`,
  `.tool-versions`, and `mise.toml`.
- Never install into the global interpreter. Use a locked project restore or a
  temporary project-local environment only when needed and safe.

### Go

- Use the module containing the changed package.
- Respect `go` and `toolchain` directives and record any toolchain download or
  network prerequisite.
- Prefer focused package tests and project environment from Make/CI commands.

### .NET, Rust, Ruby, And PHP

- .NET: respect `global.json`, target frameworks, solutions, and existing test
  projects; use the configured SDK.
- Rust: respect `rust-toolchain.toml` or `rust-toolchain`; use focused Cargo
  package/test filters.
- Ruby: respect `.ruby-version`, `.tool-versions`, and `Gemfile.lock`; use
  `bundle exec`.
- PHP: respect `composer.lock` and platform config; use Composer or vendor
  binaries.

## Change Impact Inventory

Map each changed file to the narrowest validation surface:

```markdown
| Changed file | Runtime/module | Risk | Minimum gate | Focused scenario/test |
|---|---|---|---|---|
```

Examples of minimum gates:

- source file: compile, typecheck, or import its owning module
- dependency manifest: locked resolution plus compile/import
- startup script: shell/parser syntax plus the owning process's config check
- Docker/Compose/Kubernetes config: parser/config validation when locally
  available; do not require image pulls for a basic source gate
- custom telemetry path: focused app-code test or temporary harness when the
  existing test framework exposes a practical OTel seam

## Mandatory Validation Gate

Run these in order:

1. Static integrity: `git diff --check` when available, plus parser/syntax
   checks for changed scripts and configuration.
2. Source viability: compile, typecheck, or import all affected modules with
   the selected project runtime.
3. Focused regression tests: run the smallest existing tests for changed code.
4. Signal assertions: for custom spans, metrics, or logs, add or update a
   focused test when the repo already has a practical OTel test seam.
5. Broader build/test only when shared wiring, dependency manifests, or public
   contracts make the blast radius larger.

Do not require full application startup or live infrastructure merely to prove
source viability. Do not use a generated SDK-only harness as proof that
application code compiles or emits telemetry.

## Failure And Repair Loop

- Treat an error on a changed line or in a changed API contract as introduced
  by the instrumentation unless evidence proves it was pre-existing.
- Repair introduced syntax, compile, type, import, test, and startup-config
  failures before finalizing, then rerun the failed gate and any dependent
  checks.
- Preserve unrelated user changes. Do not reset, checkout, stash, or rewrite
  them to establish a baseline.
- When attribution is ambiguous, use compiler locations, focused tests, source
  history, and unchanged-module probes. Report `unknown/pre-existing` only with
  evidence.
- If the configured runtime, private registry, declared dependency, platform,
  or credential is unavailable, mark the gate `Blocked` and name the exact
  prerequisite. Do not claim completion and do not substitute an incompatible
  runtime.

## Verification Handoff / Results

Maintain this top-level section in `.observe/otel-instrumentation.md`:

```markdown
## Verification Handoff / Results

### Runtime Selection

| Surface | Config evidence | Selected runner/env | Probe | Result |
|---|---|---|---|---|

### Build And Test Evidence

| Gate | Command | Scope | Result | Evidence or prerequisite |
|---|---|---|---|---|

### Changed Signal Scenarios

| Scenario ID | Trigger/path | Source entrypoint | Added/modified signals | Expected proof | Current evidence |
|---|---|---|---|---|---|
```

Use stable scenario IDs and one row per telemetry-distinct outcome. Include
success and failure rows when status, exception recording, metrics, events,
logs, parentage, or runtime wiring differ. Map every added/modified signal in
`Signals Changed` to at least one scenario.

When a claim requires the real agent, preload, framework route resolver,
automatic metric, duplicate suppression, startup wiring, or runtime-installed
log bridge, classify it as a conditional full-runtime row and apply
`../../references/full-runtime-acceptance.md` during `$otel-verify`.

Build/test evidence proves implementation viability only. Mark emitted
telemetry as verified only when an app-code test or harness observed the span,
metric datapoint, log record, resource, or exporter behavior.
