# Configuration API

The `obstudio` binary serves a small REST API for reading and changing its configuration. It is served on the same port as the Telemetry Explorer (default `17900`), and the startup banner prints the URL:

```
Config API:          http://127.0.0.1:17900/api/config
```

> **Status:** until the `config.yaml`-backed ConfigManager lands, the API is backed by an in-memory mock with sample values. Changes are not persisted and reset when the binary restarts. The wiring lives in `observer/cmd/obstudio/config_manager.go`.

## Concepts

- **Keys** are dotted paths into the configuration tree, such as `splunk.realm`. Segments may contain letters, digits, `_` and `-`.
- **Values** are JSON: string, boolean or integer.
- Every request goes through the ConfigManager, which owns validation. A rejected value changes nothing.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/config` | Read the whole configuration (nested) |
| `GET` | `/api/config/{key}` | Read one value, or a whole section such as `splunk` |
| `PUT` | `/api/config/{key}` | Set one value |
| `PATCH` | `/api/config` | Set several values atomically |
| `GET` | `/api/config/schema` | List every key with its type and allowed values |

`schema` is a reserved path, so a top-level key named `schema` cannot be read on its own.

### Read

```bash
B=http://127.0.0.1:17900/api/config

curl -s $B                    # {"values": {"splunk": {"realm": "us1", ...}, ...}}
curl -s $B/splunk.realm       # {"key": "splunk.realm", "value": "us1"}
curl -s $B/splunk             # {"key": "splunk", "value": {"realm": "us1", ...}}
```

### Set one value

`PUT` takes `{"value": ...}` and returns the stored value.

```bash
curl -s -X PUT $B/ui.port -H 'Content-Type: application/json' -d '{"value": 18000}'
# {"key": "ui.port", "value": 18000}
```

### Set several values

`PATCH` takes an object shaped like the `GET /api/config` response. Every leaf is applied, or none are. It returns the full resulting configuration.

```bash
curl -s -X PATCH $B -H 'Content-Type: application/json' \
  -d '{"ui": {"port": 18000}, "logging": {"level": "debug"}}'
```

Unlike RFC 7396 merge patch, `null` is passed to the ConfigManager as a value rather than deleting the key, and `{}` is a value too. Segment names may not contain dots, so `{"ui.port": 1}` is rejected. A request may change at most 256 values.

### Discover keys, types and allowed values

```bash
curl -s $B/schema
```

```json
{"keys": [
  {"key": "logging.level", "type": "string", "allowedValues": ["debug", "info", "warn", "error"]},
  {"key": "splunk.metricsExport", "type": "boolean"},
  {"key": "ui.port", "type": "integer", "minimum": 1024, "maximum": 65535}
]}
```

`type` is `string`, `boolean` or `integer`. `allowedValues`, `minimum` and `maximum` appear only when they apply. Keys are sorted.

## Errors

Errors are JSON: `{"code": "...", "error": "...", "key": "..."}`.

| Status | `code` | Meaning |
|---|---|---|
| 400 | `invalid_request` | Body is not valid JSON, has unknown fields, or `PUT` is missing `value` |
| 400 | `invalid_key` | Key or `PATCH` segment name has an invalid form, or the request has too many values |
| 403 | `forbidden` | Request did not come from a local origin (see below) |
| 404 | `unknown_key` | No such key |
| 422 | `invalid_value` | The value was rejected, for example out of range or not in `allowedValues` |
| 500 | `internal_error` | The ConfigManager failed; details are in the server log, not the response |

When a `PATCH` is rejected, the response adds an `errors` array with one entry per bad key, and nothing is applied:

```json
{"code": "invalid_value", "error": "2 values were rejected; nothing was changed",
 "errors": [{"key": "logging.level", "error": "must be one of: debug, info, warn, error"},
            {"key": "ui.port", "error": "must be a whole number between 1024 and 65535"}]}
```

## Security

Configuration can hold credentials, so reads are protected like writes. Requests must come from a loopback address, and browser requests must be same-origin (the same check as the other mutating endpoints). Responses carry `Cache-Control: no-store` and no CORS headers, so other websites cannot read them.
