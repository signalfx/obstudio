# Full Runtime Acceptance

Use this contract when an instrumentation or verification result depends on
behavior that exists only after the real process starts with its production
auto-instrumentation bootstrap.

## Trigger

Run this gate when any in-scope claim depends on:

- a Java agent, preload hook, framework middleware, or other runtime
  auto-instrumentation;
- framework-resolved HTTP route names or automatic server metrics;
- startup/exporter/resource configuration changed by instrumentation;
- removing or suppressing a duplicate signal in favor of an automatic signal;
- automatic database, messaging, client, or server span topology; or
- an OTLP log bridge/exporter installed at process startup.

Focused call-site tests remain valid proof for app-owned custom signals, but
they cannot satisfy these runtime-only claims. A synthetic root span cannot
prove the number, kind, name, or attributes of real server spans.

## Safe Runtime Plan

1. Identify the repository's actual start command and auto-instrumentation
   bootstrap.
2. Inventory required local dependencies and prefer existing test profiles,
   fake services, embedded fixtures, Testcontainers, Compose services, or
   repository-provided substitutes. Never use production credentials or data.
3. Start the real process with the project runtime, local OTLP endpoint, short
   export intervals, stable `service.name`, and test/local environment.
4. Wait for an observable readiness condition. Capture startup failure output
   and stop if the process cannot become ready.
5. Exercise every runtime-required scenario from the audit contract. Use a
   parameterized route/request matrix when many routes share setup.
6. Query in-memory exporters and the local collector/explorer while the process
   is alive, following the verifier's explorer witness contract.
7. Shut down the process and dependencies cleanly after evidence is captured.

If the repository has no safe local profile and creating one would change
application behavior materially, record the exact prerequisite and mark the
runtime rows `Blocked` or `Not proven`. Do not substitute a generated SDK
contract for this gate.

## Required Assertions

For HTTP services, assert all applicable items:

- every discovered route emits the expected low-cardinality route/span name;
- each request has exactly one canonical `SERVER` span unless documented
  framework behavior requires a different topology;
- removed or suppressed app-owned server spans do not reappear;
- automatic request-duration metrics emit a datapoint with the expected unit
  and bounded method, route, status, and service dimensions;
- expected controller, client, database, or business child spans have correct
  parentage; and
- failures produce the expected status, exception event, metrics, and logs.

For runtime-installed OTLP logs, also assert body/category, severity,
trace/span correlation, redaction, resource identity, and collector visibility.

## Result Rules

- `Pass`: every runtime-required scenario and assertion has direct evidence.
- `Partial`: focused proof passed but one or more runtime rows were not run or
  could not be proven.
- `Fail`: the real runtime executed and omitted, duplicated, or malformed an
  expected signal, or an instrumentation-introduced startup failure remains.
- `Blocked`: no meaningful runtime proof could execute because a concrete
  prerequisite was unavailable.

Keep baseline compile and focused-test results separate from this gate so a
runtime prerequisite does not erase valid app-code proof.
