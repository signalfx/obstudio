# Incident Readiness Implementation

Load this instrument-specific reference together with the shared
`../../references/incident-readiness.md` only for incident-readiness scope.
The shared reference defines the surfaces and signal semantics; this file owns
how `$otel-instrument` turns those surfaces into selected, patchable, and
provable work.

## Audit-Driven Incident Readiness

When the canonical audit contains partial or missing
`current_instrumentation.incident_readiness` rows, reconcile each row through
its selected finding with the same `area`. Treat the matched pair as one
implementation contract. The readiness row names the surface and
detection/localization impact; the gap row names the complete required fix and
instrument mode; its acceptance scenarios name the code path, expected
telemetry, proof level, and acceptance criteria. Do not create a second gap
ledger or silently synthesize missing fields. If an older audit lacks the
current prioritized gaps or verification plan, regenerate the audit before
claiming one-to-one closure.

If the user broadly asks to improve incident readiness, faster incident
detection, localization, or MTTD, resolve every safe app-owned incident gap to
exact IDs and create the selection before editing. Do not choose one
representative gap unless the user explicitly narrows scope. `manual decision`
and `external follow-up` rows cannot enter the executable selection. A recorded
`decision_answers` choice may unlock only the matching executable rows, which
still require explicit selection. Track the named external owner outside
instrumentation; never guess either boundary.

For faster incident detection, add or prove the applicable surfaces below.

Use the shared reference to add or prove every applicable surface:

- API/workflow outcome, errors, latency, and detector-ready request/job counts;
- dependency timeout, retry, rate-limit, circuit-breaker, endpoint/target
  health, availability, and operation outcome;
- input complexity, freshness/age, queue depth/lag/oldest age, dropped or
  rejected work, worker/pool saturation, and scheduled-job last success;
- stream/long-lived connection open, auth, active count, duration, close
  reason, timeout, cancellation, and send/write failure;
- auth/identity/token/secret/certificate/edge failure reason, expiry/rotation,
  route/config mismatch, and synthetic/canary result when owned;
- CPU, memory, disk, inflight/concurrency, desired-vs-healthy,
  startup/readiness/healthcheck, target-health, and autoscaling saturation when
  observable by the app or its checked-in runtime configuration; and
- low-cardinality service/artifact/config/schema/feature-flag/rollout context,
  expected-vs-running state, compatibility failure, and rollout outcome.

Start with required semantic-convention signals. Add recommended optional
signals only when an approved readiness or verification requirement depends on
them, the service can observe the value accurately, and privacy/cardinality
rules permit it. Never invent a custom signal where a semantic-convention
signal satisfies the requirement.

Do not treat a bare time-since-last-update or time-since-last-success gauge as
detector-ready staleness when healthy idle periods are possible. Require a
source-backed expected cadence, pending/backlogged work, or accepted input that
should have produced the update. Without that evidence, classify the age gauge
as context or `localization-only` and use backlog, queue delay, or missed
schedule as the MTTD-improving detector input.

When incidents, postmortems, tickets, alerts, or failure examples are supplied,
use Incident-Evidence Mode: map each failure mechanism to the owning code or platform surface and classify the proposed signal as `MTTD-improving`,
`localization-only`, or still uncovered before editing. Target the failure
mechanism rather than its endpoint symptom. Endpoint RED metrics alone do not
close an auth handshake, secret expiry, stale output, rollout skew, dependency
target loss, stream lifecycle, or pool-saturation gap.

## Process Ownership And Proof

For repositories with both web/API and background-worker processes, apply the
shared Multi-Process Web And Worker Services contract. Each process needs a
distinct, operator-overridable `service.name` default. Initialize its provider
and framework instrumentations only from that process's actual entrypoint or
startup hook; importing a worker/task module from the API must not initialize
worker telemetry. Instrument enqueue success/failure and worker task
success/failure at their owning call sites, and explicitly record failure
outcome before rethrowing.

Focused tests must execute success and failure call sites and assert emitted
telemetry through an in-memory exporter or equivalent app-code seam. AST/source-
string checks do not prove telemetry. For detector-critical counters,
histograms, and observable gauges, drive each incident state to a non-default
value and assert its emitted datapoint and bounded dimensions; metric
registration, name presence, or a zero-value observation alone is not
incident-readiness proof. Exercise a saturated or deterministic backpressure
path and prove nonzero depth and oldest-age values when those are required.

For Go changes involving goroutines, channels, queues, asynchronous persistence
or indexing, eviction, or observable callbacks, run `go test -race` for every
changed package. If that cannot run, record the exact toolchain/platform
blocker; a normal `go test` pass does not satisfy this concurrency gate. If
dependencies cannot be restored or imported, keep the executable tests, keep
the verification result `Partial`, and report the exact blocker rather than
substituting static assertions.

Extend the internal Audit-Driven Gap Closure matrix with readiness surface,
required signals, MTTD/localization classification, implemented or proven
signals, tests, remaining signals, and owner. A row cannot be `Working` while
any required signal is absent, merely listed as a follow-up, or supported only
by an unexecuted test. If no app-owned candidate can be patched accurately and
safely, add no placeholder instrument; owner-map the exact prerequisite and
keep the row `Deferred`, `Not configured`, or `Not proven` as appropriate.

Do not report unselected findings as implemented work.
