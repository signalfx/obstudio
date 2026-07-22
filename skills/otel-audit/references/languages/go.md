# Go Audit Reference

Load only for Go repositories. Check only dependencies that the project uses.

| Dependency | Auto-instrumentation Package | Signals |
|---|---|---|
| `net/http` (stdlib) | `go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp` | spans + metrics |
| `gorilla/mux` | `go.opentelemetry.io/contrib/instrumentation/github.com/gorilla/mux/otelmux` | spans only |
| `go-chi/chi` | `otelhttp` + `otelhttp.WithRouteTag` (no official contrib `otelchi` module) | spans + metrics |
| `gin-gonic/gin` | `go.opentelemetry.io/contrib/instrumentation/github.com/gin-gonic/gin/otelgin` | spans only |
| `google.golang.org/grpc` | `go.opentelemetry.io/contrib/instrumentation/google.golang.org/grpc/otelgrpc` | spans + metrics |
| `database/sql` | `github.com/XSAM/otelsql` | spans only |
| `go-redis/redis` | `github.com/redis/go-redis/extra/redisotel` | spans only |
| `runtime` | `go.opentelemetry.io/contrib/instrumentation/runtime` | metrics only |
| `host` | `go.opentelemetry.io/contrib/instrumentation/host` | metrics only |
| `segmentio/kafka-go` | `go.opentelemetry.io/contrib/instrumentation/github.com/segmentio/kafka-go/otelsegmentio` | spans only |
| `aws-sdk-go-v2` | `go.opentelemetry.io/contrib/instrumentation/github.com/aws/aws-sdk-go-v2/otelaws` | spans only |

When a detected `net/http` or chi server lacks HTTP instrumentation, name
`go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp` in the finding
and, for chi, explicitly require `otelhttp.WithRouteTag` (or equivalent
route-template naming proven by the source version) for bounded route names.
Do not write only "add HTTP instrumentation," and do not recommend a
nonexistent official `otelchi` module.

For multi-package services, name the process entry point such as
`cmd/kvstore-server/main.go` and relevant library files. Call out filesystem
persistence, background indexing, LRU eviction, goroutines, channels, and
shutdown behavior when present.
