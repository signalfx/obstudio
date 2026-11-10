# Logging workflow fixture

`GET /logging-workflow/left` and `/logging-workflow/right` logs on the request path and on an owned worker/callback.
A startup log has no request context. Existing task routes retain their behavior.
`PORT` selects an isolated test listener; its normal default remains 8000.

When `LOGGING_WORKFLOW_VERIFIER` is provided, run the existing host smoke check
through the normal configured project test target:

```sh
make test
```

The checker uses the actual foreground `make dev` startup surface. Preserve
that surface when wiring instrumentation. A bounded Flask check can disable the
development reloader. The check
owns app startup and bounded shutdown,sends real traced requests,captures original
stdout/stderr and queries the configured isolated local Studio receiver. It
writes raw evidence and `result.json` under `.observe/logging-workflow-proof/`.
Preserve the verifier;repair application instrumentation when it fails. Do not
run another app on the provided port while invoking it. No Docker/cloud account
is needed.

## Graceful-stop contract

This service's operator policy requires repeated catchable stop requests to be
idempotent during graceful finalization. Once final logging or provider drain
starts, another such request must not interrupt that work or repeat final logs
or provider shutdown. Finalization must remain within the configured stop
budget. Deliberate forced termination is outside this graceful-stop guarantee.

Acceptance must deliver a second stop request to the same process while final
logging or provider drain is still active and retain the delivery and event
order. Separate single-stop runs or a request after process exit do not prove
this contract. This is application policy, not an OpenTelemetry signal-handler
requirement.
