# kvstore

Example in-memory key/value database with a public JSON REST API.

## Features

- `set`, `get`, `delete`, and `list` operations.
- `list` returns all keys by prefix.
- Key limit: 256 bytes.
- Value limit: 4 MiB.
- Errors are returned when limits are exceeded.

## Requirements

- Go 1.22+
- Network access on first lint run (the pinned `golangci-lint` version is fetched automatically)

## Run

```bash
make run
```

The service listens on `:8080` by default. Set `PORT` to override.

## REST API

All endpoints use JSON request and response bodies.

### `POST /set`

Request:

```json
{"key":"app:1","value":"hello"}
```

Response:

```json
{"message":"ok"}
```

### `POST /get`

Request:

```json
{"key":"app:1"}
```

Response:

```json
{"value":"hello"}
```

### `POST /delete`

Request:

```json
{"key":"app:1"}
```

Response:

```json
{"message":"deleted"}
```

### `POST /list`

Request:

```json
{"prefix":"app:"}
```

Response:

```json
{"keys":["app:1","app:2"]}
```

### `GET /health`

Response:

```json
{"message":"ok"}
```

## Build, test, lint

```bash
make build
```

`build` runs tests and linting first, then compiles all packages.

## Example curl session

```bash
curl -sS -X POST localhost:8080/set -H 'Content-Type: application/json' -d '{"key":"app:1","value":"value1"}'
curl -sS -X POST localhost:8080/get -H 'Content-Type: application/json' -d '{"key":"app:1"}'
curl -sS -X POST localhost:8080/list -H 'Content-Type: application/json' -d '{"prefix":"app:"}'
curl -sS -X POST localhost:8080/delete -H 'Content-Type: application/json' -d '{"key":"app:1"}'
```
