# Organization Observability Profile

## Supported runtimes

- Production uses the Conda environment `customer-python` from
  `environment.yml`.
- Every production command must enter that environment before invoking
  `opentelemetry-instrument` or importing the application.
- Gunicorn is the production web server. Uvicorn's multi-worker target is kept
  for developer compatibility and must remain usable.

## Telemetry identity and boundaries

- Web workers use `customer-python-api`; CLI work uses
  `customer-python-cli`. Operators may override both names.
- Each scheduled Click task is an independent transaction and must start a new
  trace. An upstream scheduling context may be represented by a span link, but
  it must not parent delayed tasks under one process-lifetime trace.
- Each web worker initializes and shuts down its own trace, metric, and log
  providers. The Gunicorn master must not create provider background threads
  before fork.

## Data handling

- Task type is approved as a bounded span attribute.
- Task arguments, customer identifiers, environment prefixes, and Conda paths
  must not be recorded as span attributes, metric dimensions, or log bodies.
- Credentials belong in the deployment secret store and never in this file.
