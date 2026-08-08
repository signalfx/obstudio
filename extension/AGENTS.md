# Extension Instructions

This file adds editor-extension guidance to the repository-root `AGENTS.md`.

- Preserve support for Visual Studio Code, Kiro, and Cursor. Do not assume a
  VS Code-only installation or lifecycle path when changing shared behavior.
- Keep observer lifecycle, webview, and packaging concerns in their existing
  modules and update the matching tests under `src/test/`.
- Edit `src/`, build scripts, or package metadata rather than generated `out/`,
  `dist/`, or `.vsix` output. Respect `package-lock.json` and use `npm`.

Run `cd extension && npm run test:unit` as the narrow local suite. Run
`make test-extension` for unit, integration, and editor-host coverage. For
packaging or bundled-observer changes, also run
`cd extension && npm run build:vsix`.
