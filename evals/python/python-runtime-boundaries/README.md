# Python Runtime Boundary Demo

This fixture intentionally contains three observability failures reported in
long-running Python applications:

- a Click command keeps one `click session` span current while several
  independently scheduled tasks run, so every task becomes part of one trace;
- OpenTelemetry providers and their background processors are created while a
  Gunicorn preload master imports the application, before workers fork; and
- the Conda launch target runs `opentelemetry-instrument` outside the selected
  Conda environment instead of proving that the agent and its instrumentation
  packages are installed in, and launched by, that environment.

`OBSERVABILITY.md` represents organization-specific policy that cannot be
inferred from OpenTelemetry conventions alone. The audit must validate that
policy against the actual launch files and package manifests.

Run `make known-failures` to prove the Click trace collapse and the inherited
pre-fork provider ownership without requiring a collector.
