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
that surface when wiring instrumentation. The check
owns app startup and bounded shutdown,sends real traced requests,captures original
stdout/stderr and queries the configured isolated local Studio receiver. It
writes raw evidence and `result.json` under `.observe/logging-workflow-proof/`.
Preserve the verifier;repair application instrumentation when it fails. Do not
run another app on the provided port while invoking it. No Docker/cloud account
is needed.
