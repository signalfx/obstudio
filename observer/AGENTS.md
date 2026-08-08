# Observer Instructions

This file adds Go backend guidance to the repository-root `AGENTS.md`. Changes
under `observer/client/` must also follow its nested instructions.

- Keep OTLP ingestion, storage, REST, MCP, validation, and web-serving concerns
  in their existing packages. When an API or protocol contract changes, update
  its focused handler/server test and every affected consumer.
- Preserve concurrency, shutdown, and cross-platform behavior. Exercise the
  relevant race, lifecycle, or platform path when a change touches it.
- Do not hand-edit generated client assets under
  `observer/internal/web/static/assets/`; edit `observer/client/` and rebuild.

For a narrow Go package check, run an exact package command such as
`cd observer && go test ./internal/api`. Run `make test` for the full Go suite
and `make vet` when production Go code changes. Use `make build` when embedding,
staging, or binary assembly changes.
