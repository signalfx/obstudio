# kvstore

`kvstore` is an example in-memory key/value database in Go with asynchronous file persistence and a REST API.

## Features

- In-memory key/value store with `set`, `get`, `delete`, and `search`
- Asynchronous persistence to filesystem (`key` as filename, `value` as file content)
- Configurable in-memory capacity with LRU eviction
- Background word index updater for fast search
- Startup reload from filesystem

## Limits

- Keys: up to 64 bytes, must match `^[A-Za-z0-9_-]+$`
- Values: up to 4 MiB

## API

- `PUT /kv/{key}`: set value (request body is raw value bytes), returns `202 Accepted`
- `GET /kv/{key}`: returns raw value body, or `404` if missing
- `DELETE /kv/{key}`: deletes key, returns `204 No Content`
- `GET /search?word={word}`: returns JSON object with matching keys

Example search response:

```json
{"keys":["alpha","beta"]}
```

## Run

```bash
make build
go run ./cmd/kvstore-server -addr :8080 -data-dir ./data -capacity 1024
```

## Test

```bash
make test
```
