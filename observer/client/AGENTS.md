# Observer Client Instructions

This file adds React client guidance to the applicable parent instructions.

- Keep API types in `src/api/` aligned with the Go response contract.
- Add a colocated Vitest regression test for changed UI behavior, including
  loading, empty, and error states when the change can affect them.
- Exercise controls through their accessible role and name. Text fields must
  accept, edit, validate, and persist representative valid values; selects and
  drop-downs must expose the supported option set and apply the chosen value.
  Cover keyboard and focus behavior for the affected workflow.
- For material visual changes, inspect the rendered state at normal and narrow
  widths and in each relevant theme. Follow existing design tokens and visual
  hierarchy; avoid clipping, overflow, unreadably small text or controls, and
  oversized layouts that crowd out the user's task. CSS/source-string tests do
  not replace rendered visual evidence.
- Edit source under `src/` or `public/`, not generated Go static assets.

For a narrow check, run the changed test file, for example
`cd observer/client && npx vitest run src/AppView.test.tsx`. Run
`cd observer/client && npm run typecheck` for TypeScript changes and
`make test-client` for the complete client test suite. Run `make build-client`
when the embedded web output could change.
