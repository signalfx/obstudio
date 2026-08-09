# Pytest Plugin Instructions

This file adds reusable-plugin guidance to the repository-root `AGENTS.md`.

- Preserve public pytest entrypoints, CLI flags, config aliases and defaults,
  eval/report schemas, and supported imports. Breaking changes require explicit
  versioning and migration guidance.
- Keep each consumer run isolated to its temporary or configured workspace.
  Tracked latest reports under `eval-reports/` and run output under the
  configured `.workspace/codex-evals/` root are intentional; do not write
  outside documented output roots or leak environment changes, caches, worker
  results, or state across consumers or runs.
- Add pytester or temporary-workspace coverage for new plugin support. Exercise
  the new path beside an existing path. Isolate selectable backend, worker, and
  report failures so they do not corrupt or suppress unrelated paths. Treat a
  process-wide pytest plugin initialization failure as fatal and explicit; do
  not claim that pytest can continue after its plugin host aborts.

Run the narrowest affected test first. Run `make test-pytest-plugin` from the
repository root for the complete reusable-plugin suite.
