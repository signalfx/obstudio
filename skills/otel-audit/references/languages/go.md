# Go Audit Reference

Load only for Go repositories. Check only dependencies that the project uses.

| Dependency | Auto-instrumentation Package | Signals |
|---|---|---|
| `net/http` (stdlib) | `go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp` | spans + metrics |
| `gorilla/mux` | `go.opentelemetry.io/contrib/instrumentation/github.com/gorilla/mux/otelmux` | spans only |
| `go-chi/chi` | `otelhttp` + `otelhttp.WithRouteTag` for bounded `http.route` (no official contrib `otelchi` module; does not rename spans) | spans + metrics |
| `gin-gonic/gin` | `go.opentelemetry.io/contrib/instrumentation/github.com/gin-gonic/gin/otelgin` | spans only |
| `google.golang.org/grpc` | `go.opentelemetry.io/contrib/instrumentation/google.golang.org/grpc/otelgrpc` | spans + metrics |
| `database/sql` | `github.com/XSAM/otelsql` | spans only |
| `github.com/redis/go-redis/v9` | `github.com/redis/go-redis/extra/redisotel/v9` | spans + metrics |
| `runtime` | `go.opentelemetry.io/contrib/instrumentation/runtime` | metrics only |
| `host` | `go.opentelemetry.io/contrib/instrumentation/host` | metrics only |
| `segmentio/kafka-go` | `go.opentelemetry.io/contrib/instrumentation/github.com/segmentio/kafka-go/otelsegmentio` | spans only |
| `aws-sdk-go-v2` | `go.opentelemetry.io/contrib/instrumentation/github.com/aws/aws-sdk-go-v2/otelaws` | spans only |

When a detected `net/http` or chi server lacks HTTP instrumentation, name
`go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp` in the finding
and, for chi, explicitly require `otelhttp.WithRouteTag` (or equivalent
route-attribute setter proven by the source version) for bounded `http.route`
attributes. `WithRouteTag` does not rename the outer `otelhttp` server span. If
route-pattern span names are an explicit requirement, separately require
renaming the current outer server span after route matching and proving that
name in a recorder test; do not start a second server span.
Do not write only "add HTTP instrumentation," and do not recommend a
nonexistent official `otelchi` module.

For multi-package services, name the process entry point such as
`cmd/kvstore-server/main.go` and relevant library files. Call out filesystem
persistence, background indexing, LRU eviction, goroutines, channels, and
shutdown behavior when present.
