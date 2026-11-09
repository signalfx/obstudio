# Config Manager

How `~/.obstudio/config.yaml` is read, edited, watched and shown. This page
is for people changing the code. It does not cover what any setting means to
a user.

The Config Manager is off by default. See
[CONTRIBUTING.md](../CONTRIBUTING.md#config-manager-off-by-default) for how to
turn it on while developing. With it off, none of the pieces below run: no
file is read or created, the routes are not registered, the `telemetry`
command does not exist, and the webview hides the Config tab.

## The idea

Every setting is declared once, in one Go table. The file, the CLI, the HTTP
API, the Config tab and the generated goldens all read that table. Adding a
setting means adding a declaration and a struct field, not touching each
surface.

```text
definitions.go (the table)
        |
        +-- userconfig.Manager --- watches config.yaml, keeps the last good Settings
        |        |
        |        +-- Update(m, c) -- atomic, comment-preserving write
        |        +-- Subscribe / SubscribeFile -- change events
        |
        +-- DefinitionsDocument() -- GET /api/config/definitions
        +-- Scaffold()            -- the file written on first start
        +-- configstatus.Builder  -- GET /api/config/status, observer_status `config`
```

## Where things live

| Piece | Path | Role |
|---|---|---|
| Table and types | `observer/internal/userconfig/definitions.go` | `section`, `define`, `Settings`, `Key[T]`, checks |
| File layer | `userconfig/file.go`, `codec.go` | `Load` with line-numbered diagnostics, comment-preserving writes, JSON body decoding |
| Live layer | `userconfig/manager.go`, `watch.go` | `Manager`: fsnotify watch, 100 ms debounce, last-good snapshot |
| Generated output | `userconfig/render.go`, `scaffold.go`, `testdata/` | scaffold text, definitions document |
| Status | `observer/internal/configstatus/` | state (`ok`, `invalid`, `unparseable`, `missing`), `problem` flag, message |
| HTTP | `observer/internal/api/user_config.go` | `GET`/`POST /api/config`, `GET /api/config/definitions`, `GET /api/config/status` |
| Websocket | `observer/internal/web/websocket.go` | `config-changed` message |
| MCP | `observer/internal/mcp/handler.go` | `observer_status` gains `config` only when `problem` is true |
| CLI | `observer/cmd/obstudio/telemetry.go` | `obstudio telemetry enable \| disable \| status` |
| Wiring and gate | `observer/cmd/obstudio/userconfig_wiring.go`, `config_manager_gate.go` | builds the Manager, reads the gate |
| Webview | `observer/client/src/config/` | Config tab, edit coalescing, status pill, capability probe |
| Extension | `extension/src/observer-webview-host.ts`, `observer-webview-telemetry.ts` | host allowlist for the config routes, `config-changed` relay |

## Reading and writing the file

- **Types.** A setting is a `bool`, `int` or `string`. A bool must be a plain
  `true` or `false` in the file; `yes`, `on` and `True` are invalid.
- **Bad values.** A bad or missing value falls back to the setting's
  `FailSafe` value. `Default` is what a fresh file has. Both must pass the
  setting's own check, and a test enforces that.
- **Diagnostics.** `Load` returns the settings plus a list of diagnostics with
  line numbers. Unknown keys are reported and kept, not dropped.
- **Writes.** `Update` edits the file in place with the YAML node API, so
  comments and unknown keys survive. It writes a temp file, fsyncs, renames
  over the original, then fsyncs the directory (not on Windows). A write
  never leaves a torn file. A symlinked `config.yaml` (chezmoi, stow) is
  resolved first and the real file is written, so the link stays a link and
  the temp file sits next to the real file. `Update` calls are serialized
  within one `Manager`. The CLI writes the file directly, without that lock,
  so the CLI and a running observer writing at the same moment resolve
  last-write-wins.
- **Unparseable YAML.** Writes are refused until the file is fixed or deleted.
  The Manager keeps serving the last good snapshot while running, and the
  fail-safe settings if the file was already broken at start.
- **First start.** If the file is absent, `Scaffold()` is written without
  overwriting anything. If it cannot be created or read, the Manager still
  starts, with fail-safe settings, and logs why.

## Live changes

`Manager` watches the file's directory with fsnotify, so a file that an
editor replaces is still seen, and waits for 100 ms of quiet before
re-reading. A symlinked `config.yaml` is also watched at its resolved
location, so edits of the real file are seen live. A retargeted symlink is
picked up live on Linux and on the next restart on macOS. Two kinds of
subscription exist:

- `Subscribe` gets an `Event` with the old and new `Snapshot` only when the
  effective settings changed. `Event.Affects(key or section)` asks whether a
  particular setting changed. Changes that arrive while the callback runs are
  merged into one `Event`.
- `SubscribeFile` fires when the file's state changed, including a break or a
  fix that leaves the settings the same. A comment-only edit also fires it.
  The observer uses this one to send `config-changed` over the websocket, so
  open webviews re-fetch settings and status.

Callbacks run on their own goroutines, so a callback may call `Get`, `Update`
or subscribe again. If the watcher cannot start, or the directory (or the
real file's directory, for a link) is removed, the Manager gives up the watch
for good and logs it. `Get` then re-reads a changed file itself, so settings
stay correct when they are read. Subscribers and webviews hear about a change
only when something calls `Get`.

## HTTP, websocket and MCP

| Route | Notes |
|---|---|
| `GET /api/config` | The effective settings, in the file's shape |
| `POST /api/config` | A JSON merge body such as `{"<section>":{"<name>":<value>}}`. Loopback only, and a browser request must be same-origin and send `X-Obstudio-Browser-Request: 1`; anything else gets 403. Bodies over 4 KiB, unknown keys and wrong types get 400 before anything is written. An unparseable file gets 409. Returns the effective settings |
| `GET /api/config/definitions` | The declared sections and settings (title, description, type, default, fail-safe, apply mode). The Config tab renders from this |
| `GET /api/config/status` | State, `problem`, a message, the line-numbered diagnostics, and every effective setting. `problem` is true when the state is `invalid` or `unparseable` |
| `GET /api/health` | `configManager: true` only when the gate is on. The webview treats anything else as "off" |

The routes are only registered when a Manager exists.

## Adding a setting

1. In `definitions.go`, add a field to `Settings` (inside a section struct) and
   a `define(section, name, defSpec[T]{...})` with `Title`, `Description`,
   `Default`, `FailSafe`, `Apply` and a `Field` accessor. Declare a new
   `section` first if needed. Names must line up: section `abc` is the field
   `Settings.Abc` of type `AbcSettings`, and setting `xyz` is its field `Xyz`
   (`TestTableSelfTest` checks this). Declarations run at package
   initialization, and a duplicate name or an unregistered section panics at
   startup.
2. Regenerate the goldens from `observer/`:
   `go test ./internal/userconfig -update`, then read the diff in
   `testdata/`.
3. Update the tests that pin the exact settings list. In
   `internal/userconfig`: `v1DefinitionsDoc` in `render_test.go`, `v1Scaffold`
   and the parse and write fixtures in `file_test.go`, `assertV1Definitions`
   and `TestTableV1` in `definitions_test.go`, and `TestEncodeSettings` in
   `codec_test.go`.
   Outside it: `TestStateTable` in `internal/configstatus` and the settings and
   status shape tests in `internal/api/user_config_test.go`.
4. Check the scaffold wrap. The `Description` is wrapped at 80 columns into the
   file comments. Tests pin `telemetry.enabled` to line 11 of the scaffold, so
   a longer description there, or a setting declared before it, fails them.
5. The Config tab, the definitions route, the scaffold and the status
   `Effective` block pick the new setting up without further code. The
   `telemetry` CLI is the exception: it is written for one setting, so a new
   setting needs its own command or a generic one.

Titles and descriptions come from the table everywhere. A client test
(`noHardcodedWording.test.ts`) fails if the webview source contains a copy of
the `telemetry` section title or of the `telemetry.enabled` title or
description.

## Sections and keys

A section name is also the YAML top-level key and the prefix of every key path
under it. `define` builds a path as `section.name`. The section's `Title` and
`Description` are the only parts that are pure presentation. This means a
setting is always shown under its YAML parent. Grouping settings differently
from the file structure would need a presentation group on top of the
section; nothing needs that yet.

## Webview and extension

The Config tab (`observer/client/src/config/`) loads the definitions and the
settings and renders a control per setting. A bool or a choice is sent at
once; a typed value is sent 500 ms after the last keystroke. Only the changed
fields are sent. A config problem shows as a pill in the tab bar on every tab
but Config, and as a list inside it. The client fails closed: the tab,
shortcut and pill appear only when `/api/health` reports `configManager: true`.
If the definitions or the settings fail to load, the tab shows an error with a
retry.

In the extension, the host transport forwards only allow-listed paths, so the
config routes and the `config-changed` message are listed in
`observer-webview-host.ts` and `observer-webview-telemetry.ts`. A new route
needs an entry there, plus a test in `extension/src/test/extension.test.ts`.

## Testing

```sh
cd observer
go test -race -count=1 ./internal/userconfig ./internal/configstatus \
  ./internal/api ./internal/web ./internal/mcp ./cmd/obstudio
cd client && npx vitest run src/config
```

- Wait on a side effect, not only on a state flag. For example, the Manager
  stores `watched=false` before it logs the reason, so a test that polls the
  flag and then reads the log can race.
- The `Manager` takes injected clocks, a fake watcher and a log function, so
  watcher and debounce behavior can be tested without sleeping.
- Two goldens are checked in: `testdata/scaffold.golden.yaml` and
  `testdata/definitions.golden.json`. A stale one fails with the command to
  regenerate it.
