# Fresh native Go GenAI fixture

This application starts with no telemetry provider, exporter, or active observer.
`main.go` owns a support agent, local policy retrieval, an order tool, and a real
HTTP model client. `telemetry.go` initially does nothing. The provisioned native
Go OTel dependencies are unused until instrumentation is implemented; their
presence does not establish coverage. There is no application logging stack.
The JSON written to stdout is business output, not an OTel LogRecord.

The four requests exercise success, tool failure, HTTP provider failure, and
cancellation after retrieval but before the tool returns. The applicable graph
has four agent roots, four retrieval children, four tool children, and two
HTTP model children: fourteen spans, with request sizes 4/3/4/3. There is no
separate workflow, database call, streaming, model-issued tool call, or source
conversation/tool-call ID. Only the model client is a remote operation.

## Local commands

Use Go 1.25 or newer compatible with `go.mod`. Provision modules once with
`go mod download`; subsequent commands can use
`GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off` with the provisioned module cache.
Versions in `go.mod` are this fixture's reproducible dependency selection, not
version instructions for skills. `eval/inputs/native-module-evidence.json`
records the official release metadata and toolchain compatibility decision.

```sh
go test -race ./...
mkdir -p .observe
go build -o .observe/agent .
go run ./eval/inputs/nativeprobe --app "$PWD/.observe/agent" --output .observe/baseline.json --expect baseline
```

`nativeprobe` is an external Go test controller. It starts isolated numeric
loopback HTTP model, resource API, and OTLP servers, then launches the compiled
application with `--model-origin`, `--scenario all`, and `--output`. Ambient
OTLP/AO configuration and proxy variables are removed from the child
configuration without changing the caller's environment. It supplies synthetic
selectors `fixture-project`/`fixture-agent`, public resource marker
`X-SF-Token: local-gateway`, and harmless configured exporter headers plus stale
AO IDs to test replacement/removal. No cloud token, Python process, or sidecar
is involved. The model returns one observed response with 11 input and 7 output
tokens; these are fixture usage, not a billing claim.

After native instrumentation, use:

```sh
go run ./eval/inputs/nativeprobe --app "$PWD/.observe/agent" --output .observe/native.json --expect native --runs 2 --resources missing
go run ./eval/inputs/nativeprobe --app "$PWD/.observe/agent" --output .observe/auth.json --expect capture --resources auth
go run ./eval/inputs/nativeprobe --app "$PWD/.observe/agent" --output .observe/rejected.json --expect capture --resources existing --reject-traces
```

Resource modes are `missing`, `existing`, and `auth`. `missing` serves actual
201 project/stream creates on the first process and reuses their returned UUIDs
on the second. `auth` serves 403 and must not trigger POST or retain stale AO
bindings; business execution and independent metrics continue. Trace rejection
serves actual OTLP 400 while metrics remain accepted. Capture mode proves
recorded business/failure behavior; it is not a successful-delivery or complete
profile Pass. The controller's native profile checks are source-specific;
semantic review and complete-schema validation remain separate requirements.

## Read-only verification inputs

`eval/inputs/nativecandidate/telemetry.go` is a verification-only reference with
a `//go:build ignore` tag. It is excluded from the fresh app and instrument eval
inputs. Its actual execution copies the pristine app into a separate temporary
module and removes only that tag from the replacement `telemetry.go`.
`candidate-provenance.json` records source/capture hashes and this transformation.
The negative capture comes from a separately compiled variant removing the tool
input message mapping; it retains the fourteen spans, arguments/results, and
metrics. Its tool spans select the GenAI mapping rather than the alternative
OpenInference TOOL mapping, so the missing message is a real profile failure.

```sh
go run ./eval/inputs/nativeprobe --validate-receipt eval/inputs/native-candidate-capture.json --expect native
go run ./eval/inputs/nativeprobe --validate-receipt eval/inputs/native-missing-tool-message-capture.json --expect native # must fail
go run ./eval/inputs/schemacheck --profile eval/inputs/genai-profile-evidence.json --receipt eval/inputs/native-candidate-capture.json
```

Receipts retain raw protobuf bytes (base64 and SHA-256), decoded attributes,
resource/scope, IDs/parents, kind/status/events/links/flags and full nanosecond
intervals, model requests/actual response identity, resource journals, and
business outcomes. Read-only validation re-decodes the raw bodies and checks
their equality with the decoded records. Source-bound profile checks require
all fourteen expected operations and complete connected, closed, correctly
parented traces. The current profile uses inference duration and input/output
usage instruments; successful text usage and missing failed usage have distinct
modality/error evidence. Schemas validate present values and do not establish
missing-field coverage. Local acceptance does not establish real Studio/cloud
routing, backend recognition, explorer visibility, or production readiness.
