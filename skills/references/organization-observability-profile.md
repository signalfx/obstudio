# Organization Observability Profile

Use this reference when the audited or instrumented service contains an exact
`OBSERVABILITY.md` file at its service root or a repository ancestor. This is a
checked-in, organization-owned companion to code and deployment configuration,
similar to an IDE style guide. It carries local facts that generic
OpenTelemetry conventions cannot infer.

## Discovery And Scope

Starting at the selected service root, read the nearest `OBSERVABILITY.md`,
then a repository-root `OBSERVABILITY.md` when it is a different file. The
nearest file owns service-specific values; the root file supplies organization
defaults. Do not search home directories, global config, unrelated sibling
repositories, generated `.observe/` output, or untracked editor state.

The profile may define:

- approved package/runtime managers, environment names, package channels, and
  exact production, worker, CLI, test, and local launch commands;
- process models, preload behavior, worker classes, lifecycle hooks, and which
  process owns each provider, exporter, instrumentation, and shutdown;
- operator-overridable service names and resource-attribute sources;
- transaction, trace, job, batch, stream, and delayed-work boundaries,
  including where a span link is preferred to parentage;
- approved bounded attributes and dimensions, prohibited data, content
  capture, redaction, retention, and access ownership; and
- safe project-runtime and full-runtime verification commands.

Never place credentials, access tokens, private keys, or secret values in the
profile. It may name a secret store or environment variable, but not its value.

## Evidence And Precedence

Treat the profile as an organization constraint and an evidence lead, not as
runtime proof. Reconcile every applicable statement with manifests, lockfiles,
entrypoints, launch configuration, process hooks, and tests. A named Conda
environment does not prove which Python or `opentelemetry-instrument` executes;
a named post-fork hook does not prove providers are worker-local; and an
approved service name does not prove the effective resource.

Use this precedence:

1. the current explicit user request;
2. a nearer service `OBSERVABILITY.md`;
3. repository-root `OBSERVABILITY.md` defaults;
4. generic skill defaults.

Observed source and runtime facts do not silently lose to stale profile prose.
When policy and implementation conflict, preserve the explicit user scope,
report the conflict with both evidence paths, and create or retain the concrete
OTel closure gap. No profile may override credential safety, local-only log
routing, privacy/cardinality limits, semantic conventions, or required proof.

## Audit Contract

Record the profile path in audit evidence and carry applicable service names,
runtime surfaces, process boundaries, privacy limits, and verification commands
into findings and scenarios. Create separate scenarios for materially distinct
launch paths. Do not turn organization preferences with no OTel consequence
into findings.

## Instrumentation Contract

Use validated profile values for service defaults, launch integration, and
privacy controls. Preserve every supported launch surface unless the user
narrows scope. Test the effective values and process ownership; do not claim a
profile requirement is working merely because the file says so. If the
configured runtime is unavailable, keep the implementation source-owned and
mark its runtime proof `Not proven` with the exact prerequisite.
