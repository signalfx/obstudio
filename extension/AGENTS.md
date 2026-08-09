# Extension Instructions

This file adds editor-extension guidance to the repository-root `AGENTS.md`.

- Preserve support for Visual Studio Code, Claude Code, Codex, Cursor, Kiro,
  and Copilot where their integration paths apply. Do not project one target's
  config schema, transport, policy fields, or install layout onto another.
- Automatic multi-target detection and configuration must isolate each target:
  report a failed target, preserve successful work and user-owned config, then
  continue with later targets without stopping the Observer. Add a mixed-target
  regression with a failure in the middle whenever this orchestration changes.
- For webview, status, notification, or other extension UI changes, prove the
  affected actions, editable fields/options, accessible keyboard/focus path,
  and visible normal, error, and recovery states. Treat constrained IDE
  sidebars, panels, and webviews as first-class layouts: exercise the documented
  smallest supported viewport or record the narrowest tested width and height,
  a normal size, live resizing, relevant themes, and supported zoom or text
  scaling. Keep essential controls and feedback reachable without clipping,
  overlap, hidden actions, or avoidable horizontal scrolling.
- Keep UI shared by Visual Studio Code, Cursor, and Kiro host-neutral, with
  host-specific APIs behind explicit capability adapters. Prove the shared
  workflow in every materially distinct supported host; for a host-specific
  change, prove the changed host and at least one unchanged existing host. A
  missing or failing host capability must disable or fail only the dependent
  feature with clear host-scoped feedback, without breaking other extension
  UI, integration targets, or the core Observer.
- Keep observer lifecycle, webview, and packaging concerns in their existing
  modules and update the matching tests under `src/test/`.
- Edit `src/`, build scripts, or package metadata rather than generated `out/`,
  `dist/`, or `.vsix` output. Respect `package-lock.json` and use `npm`.

Run `cd extension && npm run test:unit` as the narrow local suite. Run
`make test-extension` for unit, integration, and editor-host coverage. For
packaging or bundled-observer changes, also run
`cd extension && npm run build:vsix`.
