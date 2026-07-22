# OTel Audit Report: go-chi-basic

**Status:** Partial
**GenAI ownership detected:** No
**Canonical source:** `.observe/otel-audit.json`
**Review report:** `.observe/otel.html`

## Executive Summary

- Partial — 1 required, 3 recommended, and 0 deferred findings.
- Repository evidence identifies 6 routes, 0 span entries, 0 metric entries, and 0 log integrations.
- This audit proves only source and configuration state; run the mapped scenarios before treating telemetry as emitted or visible in a product.
- Next: add 1 safe required fix(es) to the plan; resolve prerequisites for 2 blocked item(s); resolve 1 later decision(s).

### Review Queue

| Finding | Priority / effort | Action path | Why it matters | Product result |
|---|---|---|---|---|
| OTEL-001 | required · medium | ready to implement | Operators cannot attribute latency or errors to stable route patterns. | Splunk APM route-level latency and errors |
| OTEL-002 | recommended · small | optional | Product activity cannot be charted independently of HTTP throughput. | Splunk dashboard business KPI |
| OTEL-003 | recommended · decision | decision needed | Implementing both alternatives would duplicate the same task-creation outcome in two app-owned signals. | Task creation has one explicitly chosen app-owned telemetry signal. |
| OTEL-004 | recommended · small | optional | When the span alternative is chosen, operators cannot isolate persistence latency in the trace waterfall. | The trace waterfall shows one bounded task.create span for each successful creation. |

### Technical Audit Highlights

- HTTP request telemetry is missing; a business event metric is optional and not approved.

## Flow

audit -> select -> instrument -> verify

## Audit Evidence

| Check | Finding | Source |
|---|---|---|
| Manifest | Go chi service without OpenTelemetry dependencies | go.mod |
| Entry point | HTTP router and handlers | main.go |
| Route source | Six chi routes | main.go |
| Runtime/startup | Go 1.23 module | go.mod |
| GenAI ownership | No | go.mod and main.go |

## Routes

| Method | Path |
|---|---|
| GET | /health |
| GET | /tasks |
| GET | /tasks/{id} |
| POST | /tasks |
| PATCH | /tasks/{id} |
| DELETE | /tasks/{id} |

## Signal Flow

### Component Flow Map

```text
Request handling
main.go [SOURCE-COVERED] -> chi router [GAP: HTTP request telemetry] -> POST /tasks handler [SOURCE-COVERED] [GAP: Task creation KPI] [GAP: Task telemetry ownership] [GAP: Task creation trace]
```

## Current Instrumentation

### Spans

| Name | Source | Type |
|---|---|---|

### Metrics

| Name | Source | Type |
|---|---|---|

### Logs

| Integration | Source | Detail |
|---|---|---|

## Gaps

| Priority | Area | Gap | Why it matters | Required fix | Instrument mode | Verification scenarios |
|---|---|---|---|---|---|---|
| required | HTTP request telemetry | The chi router has no OpenTelemetry server instrumentation. | Operators cannot attribute latency or errors to stable route patterns. | Add one OpenTelemetry SDK lifecycle and one route-aware otelhttp server wrapper. | default | http.health.success |
| recommended | Task creation KPI | Successful task creation is not counted as a business event. | Product activity cannot be charted independently of HTTP throughput. | Add a task.created counter after a task is persisted. | fix all | business.task-created |
| recommended | Task telemetry ownership | The service does not define whether task creation should emit the task.created metric or the task.create span. | Implementing both alternatives would duplicate the same task-creation outcome in two app-owned signals. | Choose either the task.created metric or the task.create span as the app-owned task-creation signal. | manual decision | business.task-created<br>business.task-create-span |
| recommended | Task creation trace | Successful task creation has no app-owned task.create span. | When the span alternative is chosen, operators cannot isolate persistence latency in the trace waterfall. | Add one task.create span around successful task persistence. | fix all | business.task-create-span |

### OTel Closure Details

| Area | OTel concerns | Configuration scopes | Decision / external handoff |
|---|---|---|---|
| HTTP request telemetry | signal-emission<br>semantic-attributes | N/A | Executable in service |
| Task creation KPI | signal-emission | N/A | Executable in service |
| Task telemetry ownership | signal-emission | N/A | Decision owner: task service telemetry owner; question: Which app-owned OTel signal should represent task creation: task.created or task.create?; options: metric-counter = Task metric (Emit task.created once after successful persistence.; unlocks OTEL-002); trace-span = Task span (Emit task.create around successful persistence.; unlocks OTEL-004) |
| Task creation trace | signal-emission | N/A | Executable in service |

## Verification Plan

### Test Environments

| Environment ID | Surface | Config Evidence | Runner / Toolchain | Scope | Shared Prerequisites |
|---|---|---|---|---|---|
| `go.local` | go-chi-basic service | go.mod | go test ./... | module | none |

### Acceptance Scenarios

| Scenario ID | Trigger / Path | Source Entrypoint | Expected Signals | Proof Level | Acceptance Criteria | Environment |
|---|---|---|---|---|---|---|
| `http.health.success` | GET /health | main.go:28 | one route-aware HTTP server span | `full runtime` | The request emits exactly one server span with http.route=/health. | `go.local` |
| `business.task-created` | POST /tasks with a valid bounded title | main.go:53 | one task.created metric increment | `focused call-site` | The successful persistence path records task.created exactly once with no metric attributes. | `go.local` |
| `business.task-create-span` | POST /tasks with a valid bounded title | main.go:53 | one task.create span | `focused call-site` | The successful persistence path emits task.create exactly once. | `go.local` |

## Anti-Patterns

None.

## Recommendation

- Run $otel-instrument --ids OTEL-001; leave OTEL-002 unselected.
