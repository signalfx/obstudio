# Python Audit Reference

Load only for Python repositories. Check only dependencies that the project uses.

| Dependency | Auto-instrumentation Package | Signals |
|---|---|---|
| `flask` | `opentelemetry-instrumentation-flask` | spans |
| `django` | `opentelemetry-instrumentation-django` | spans |
| `fastapi` | `opentelemetry-instrumentation-fastapi` | spans |
| `starlette` | `opentelemetry-instrumentation-starlette` | spans |
| `requests` | `opentelemetry-instrumentation-requests` | spans |
| `httpx` | `opentelemetry-instrumentation-httpx` | spans |
| `urllib3` | `opentelemetry-instrumentation-urllib3` | spans |
| `aiohttp.ClientSession` (client) | `opentelemetry-instrumentation-aiohttp-client` | spans |
| `aiohttp.web` (server) | `opentelemetry-instrumentation-aiohttp-server` | spans |
| `psycopg2` | `opentelemetry-instrumentation-psycopg2` | spans |
| `sqlalchemy` | `opentelemetry-instrumentation-sqlalchemy` | spans |
| `pymongo` | `opentelemetry-instrumentation-pymongo` | spans |
| `redis` | `opentelemetry-instrumentation-redis` | spans |
| `celery` | `opentelemetry-instrumentation-celery` | spans |
| `grpcio` | `opentelemetry-instrumentation-grpc` | spans |
| `kafka-python` / `confluent-kafka` | `opentelemetry-instrumentation-kafka-python` / `opentelemetry-instrumentation-confluent-kafka` | spans |
| `boto3` / `botocore` | `opentelemetry-instrumentation-botocore` | spans |
| `logging` (stdlib) | `opentelemetry-instrumentation-logging` | logs |

Name `pyproject.toml` or `requirements.txt`, the app entry point, and runtime
files such as Dockerfile or compose config when present. For FastAPI/Celery,
identify web and worker entry points, commands, ASGI and Celery coverage, Redis
coverage when Redis exists, and HTTP-client instrumentation only when a client
dependency exists.

Do not substitute the FastAPI instrumentor for a plain Starlette application.
For `aiohttp`, inspect source usage rather than inferring the surface from the
dependency alone: `ClientSession` needs the client package, `aiohttp.web` needs
the server package, and an application using both surfaces needs both packages.
