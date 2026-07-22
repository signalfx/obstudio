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

Before authoring a local receiver, temporary runtime harness, or start plan
that requires a listener, run exactly one bounded capability probe:

```bash
python3 -I \
  "<directory-containing-loaded-SKILL.md>/scripts/probe_loopback_bind.py"
```

Resolve the wrapper from the active `otel-instrument` or `otel-verify` skill
directory. When the complete JSON result is `status: blocked`, preserve its
error type, errno, and message as the concrete runtime prerequisite; do not
author or repeatedly execute a receiver/harness that necessarily needs the
same forbidden bind. Mark only the listener-dependent rows `Blocked` or `Not
proven`, while retaining compile and focused-test evidence. When the result is
`status: available`, continue with the real runtime gate: the probe is a
prerequisite check, not startup, readiness, emission, or export proof. Do not
run this probe when the chosen repository-native plan requires no local
listener.

Then:

1. Identify the repository's actual start command, auto-instrumentation
   bootstrap, and execution boundary: host/forked JVM, container, Compose
   service, or deployed-image equivalent.
2. When the boundary uses a Java agent, follow the active skill's project
   runtime reference and run its `scripts/resolve_java_agent.py` wrapper before
   startup. Bind the resolver's absolute validated path/version/hash/identity as
   the verification pin, execute its exact `pre_attach_recheck_argv` immediately
   before JVM startup, and attach only the `javaagent_argv` returned by that
   successful exact-pin recheck. A missing path from a different boundary is a
   rejected candidate, not a blocker. Keep an unknown deployed-production
   version as a parity gap; do not ask the user to supply a JAR when a valid
   local candidate resolved.
3. Inventory required local dependencies and prefer existing test profiles,
   fake services, embedded fixtures, Testcontainers, Compose services, or
   repository-provided substitutes. Never use production credentials or data.
4. Start the real process with the project runtime, local OTLP endpoint, short
   export intervals, stable `service.name`, and test/local environment. Resolve
   configuration ownership per signal: agent `-Dotel.*` properties do not
   substitute for actual `OTEL_*` environment variables read by an app-owned
   reporter/exporter.
5. Wait for an observable readiness condition. Capture startup failure output
   and stop if the process cannot become ready.
6. Exercise every runtime-required scenario from the audit contract. Use a
   parameterized route/request matrix when many routes share setup.
7. Query in-memory exporters and the local collector/explorer while the exact
   emitting process or test fork is alive, following the verifier's explorer
   witness contract. Save the query evidence before allowing that process to
   exit; a parent build process remaining alive does not preserve a child
   emitter's source.
8. Shut down the process and dependencies cleanly after evidence is captured.

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

Successful current-run agent attachment supersedes earlier path-absence
probes. A process that attached its agent and then failed application startup
or an assertion is `Fail`/`Not working`, not agent-blocked. Unknown production
agent parity remains a separate limitation and does not erase proof from the
resolved verification pin.

Keep baseline compile and focused-test results separate from this gate so a
runtime prerequisite does not erase valid app-code proof.
