# Logging workflow fixture

`make dev` starts the task API; `PORT` defaults to 8000.
`GET /logging-workflow/left` and `/logging-workflow/right` emit a request log
and an owned worker/callback log. A startup log runs outside request context.
Existing task routes retain their behavior.

`make test` runs project checks and, when `LOGGING_WORKFLOW_VERIFIER` is set,
the host logging check. The checker owns startup through `make dev` and bounded
cleanup, sends traced requests, captures original stdout/stderr and queries the
isolated local Studio receiver. Evidence is saved under
`.observe/logging-workflow-proof/`. Keep the checker unchanged and leave its
assigned port free; repair application instrumentation when its assertions fail.
No Docker or cloud account is required.
