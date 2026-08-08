# Observer Client Instructions

This file adds React client guidance to the applicable parent instructions.

- Keep API types in `src/api/` aligned with the Go response contract.
- Add a colocated Vitest regression test for changed UI behavior, including
  loading, empty, and error states when the change can affect them.
- Edit source under `src/` or `public/`, not generated Go static assets.

For a narrow check, run the changed test file, for example
`cd observer/client && npx vitest run src/AppView.test.tsx`. Run
`cd observer/client && npm run typecheck` for TypeScript changes and
`make test-client` for the complete client test suite. Run `make build-client`
when the embedded web output could change.
