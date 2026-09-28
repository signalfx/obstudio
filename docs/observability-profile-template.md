# Organization Observability Profile Template

Copy this file to `OBSERVABILITY.md` at the repository or service root when
organization-specific observability rules cannot be inferred from source.
Keep it in version control with the application. Never put credentials in it.

## Runtime ownership

- Package/runtime manager and exact environment name:
- Supported production, worker, CLI, and local launch commands:
- Process model, preload behavior, worker class, and shutdown hooks:
- Approved package channels or artifact registries (names only, no tokens):

## Telemetry identity and routing

- Operator-overridable `service.name` defaults by process:
- Namespace, environment, region, version, and deployment attribute sources:
- Local collector address by runtime shape:
- Signal ownership when an agent, SDK, platform, or vendor bridge already exists:

## Trace and work boundaries

- What constitutes one transaction or trace:
- Which delayed or batch operations must start new root traces:
- Where span links preserve causality without creating a process-lifetime trace:

## Data handling

- Approved bounded attributes and metric dimensions:
- Prohibited identifiers, content, paths, payloads, and log fields:
- Content-capture, redaction, retention, and access owner:

## Verification

- Project-runtime commands for focused tests:
- Safe local full-runtime profile and required dependencies:
- Required host/editor launch configurations:
