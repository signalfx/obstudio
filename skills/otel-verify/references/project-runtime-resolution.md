# Project Runtime Resolution

Use this reference before any `$otel-verify` compile, import, test, harness,
startup, or OTLP command. The goal is to execute verification with the
repository's configured runtime instead of the shell's accidental defaults.

## Required Outcome

Build a runtime candidate inventory before running verification:

```markdown
## Runtime Candidate Inventory

| Surface | Config evidence | Selected runner/env | Probe command | Outcome | Fallback/impact |
|---|---|---|---|---|---|
```

Only mark application code `Fail` after it fails under the selected
project-configured runtime. If a default shell runtime fails but project config
points elsewhere, record the default runtime as rejected and retry with the
project runtime.

When `.observe/otel.md` contains `Verification Plan / Test Environments`, or
`.observe/otel-instrumentation.md` contains `Verification Handoff / Results`,
treat their runtime rows and commands as candidates. Normalize legacy
`Verification Contract / Project Runtime` input when needed. Revalidate all
candidates against current wrappers, toolchain files, manifests, and local
availability before execution; a handoff can become stale.

## Discovery Order

Inspect these sources before choosing commands:

1. Repository wrappers: `mvnw`, `gradlew`, package-manager wrappers, checked-in
   scripts.
2. Toolchain/version files: `.java-version`, `.sdkmanrc`, `.tool-versions`,
   `mise.toml`, `.nvmrc`, `.node-version`, `.python-version`,
   `rust-toolchain.toml`, `global.json`, `go.mod`, `.ruby-version`.
3. Manifests and lockfiles: `pom.xml`, `build.gradle*`, `package.json`,
   lockfiles, `pyproject.toml`, `poetry.lock`, `uv.lock`, `requirements*.txt`,
   `Cargo.toml`, `Gemfile.lock`, `composer.lock`.
4. Repo test commands: `Makefile`, `justfile`, `Taskfile.yml`, `package.json`
   scripts, CI workflow files, devcontainer config, Docker compose test
   services.
5. Existing local environments: activated venvs, `.venv`, tool manager shims,
   local dependency caches.

Prefer the first candidate that is both project-configured and locally
available. Do not install global tools or update dependency manifests.

## Language Rules

### Java and Kotlin

- Prefer `./mvnw` or `./gradlew`; otherwise use installed Maven/Gradle with the
  project-selected JDK.
- Read Java version evidence from `maven.compiler.release`, `jdk.version`,
  `java.version`, Maven Toolchains, `.mvn/jvm.config`, Gradle Java toolchains,
  `.java-version`, `.sdkmanrc`, `.tool-versions`, or `mise.toml`.
- Locate installed JDKs without installing new ones. On macOS, use
  `/usr/libexec/java_home -V`; also consider SDKMAN, asdf, mise, or jenv when
  config references them.
- Run probes with explicit `JAVA_HOME` and `PATH`, for example:
  `JAVA_HOME=<jdk> PATH=<jdk>/bin:$PATH ./mvnw -version`.
- If a Java compile fails with Lombok, annotation processor, or javac-internal
  errors under a newer global JDK, retry with the configured project JDK before
  reporting an app compile failure.
- For Maven reactor test filters, `-Dtest=...` can fail in upstream modules
  that have no matching tests. It is acceptable to add
  `-Dsurefire.failIfNoSpecifiedTests=false` or the project-equivalent guard,
  but then inspect Surefire/Failsafe output or reports to confirm the target
  test class actually ran.
- For temporary Java harnesses, use the same JDK and project classpath. Prefer
  `test-compile` plus `dependency:build-classpath`, Gradle test runtime
  classpath tasks, or an existing test source set over ad hoc global jars.

### Node and TypeScript

- Select the package manager from `packageManager` in `package.json` first,
  then lockfiles: `pnpm-lock.yaml`, `yarn.lock`, `package-lock.json`, or
  `bun.lockb`.
- Respect `.nvmrc`, `.node-version`, `engines.node`, `.tool-versions`, and
  `mise.toml`. Use `corepack` when the repo declares a package manager version.
- Run verification through package scripts or workspace-aware commands such as
  `pnpm exec`, `pnpm --filter`, `yarn workspace`, `npm exec`, or `bun run`.
- If dependencies are missing, use the locked project install only when needed
  and safe; otherwise mark rows `Blocked` with the missing package-manager or
  registry prerequisite.

### Python

- Prefer an existing `.venv` or project runner: `uv run --locked`,
  `poetry run`, `pdm run`, `pipenv run`, `hatch run`, `tox`, or `nox`.
- Respect `.python-version`, `requires-python` in `pyproject.toml`,
  `runtime.txt`, `.tool-versions`, and `mise.toml`.
- Do not `pip install` into the global interpreter. Use locked project restore
  or a temporary project-local environment only when needed for verification.
- If an import fails in the shell interpreter but the dependency is declared in
  the project, retry through the project runner before downgrading the row.

### Go

- Use the module's `go` command with `go.mod` as the source of truth.
- Respect `go` and `toolchain` directives. Record when `GOTOOLCHAIN=auto`
  downloads or requires a newer toolchain.
- Use focused `go test ./path -run ...` commands and project environment
  variables from CI or Make targets when present.

### .NET

- Respect `global.json`, target frameworks, solution files, and existing test
  projects.
- Prefer `dotnet test <solution-or-project> --filter ...` with the configured
  SDK. If the SDK from `global.json` is absent, mark affected rows `Blocked`.

### Rust, Ruby, PHP

- Rust: respect `rust-toolchain.toml` or `rust-toolchain`; use `cargo test`
  with focused package/test filters.
- Ruby: respect `.ruby-version`, `.tool-versions`, `Gemfile.lock`; use
  `bundle exec`.
- PHP: respect `composer.lock` and platform config; use `composer exec` or
  vendor binaries.

## Containers And CI

Use container/devcontainer/CI commands only when they are clearly local-safe and
do not require production credentials. Prefer them when the host is missing the
declared toolchain and the repo already provides a deterministic test service.
Record Docker, network, registry, or credential requirements as `Blocked` when
they prevent verification.

## Reporting Rules

In `.observe/otel-verify.md`, include:

- config evidence that selected each runtime
- the selected runner and environment variables such as `JAVA_HOME`, package
  manager, Python interpreter, SDK version, or container image
- rejected candidates, including global runtime failures that were retried
- restore/import/probe commands and results
- exact missing prerequisites for blocked rows
- confirmation that each targeted filtered test actually ran when no-match
  guards were used
- build/import viability per affected module, failure ownership, and every
  signal/path row blocked by a failed gate

Do not treat a source definition as verified runtime behavior. Runtime rows are
verified only when the configured project runtime executes the import, compile,
test, harness, startup, or exporter path.
