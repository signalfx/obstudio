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

A bounded check may disable the development reloader through the effective
startup command; an environment value does not override an explicit CLI flag.

## Graceful-stop contract

Repeated catchable stop requests must be idempotent during final logging and
provider drain: do not interrupt or repeat finalization, and keep the existing
stop budget. Forced termination is outside this policy. Acceptance sends the
second request to the same process while finalization is active and retains
delivery and event order. Separate single-stop runs do not prove this policy.

## Telemetry privacy contract

Exported application logs and existing HTTP server spans must exclude sensitive
request path/query values, raw exception messages and rendered stacks, including
local source paths. Preserve bounded error categories, HTTP method/route/status,
trace context, Resource identity and SDK limit/drop accounting through supported
sanitization boundaries. A logs-only sanitizer does not establish span privacy.

Acceptance exercises an unmatched sensitive request and an escaping application
error through normal startup, inspecting received server spans and selected log
outputs. Preserve application responses and native sink/level/privacy policy;
do not add payload/header capture, extra exception telemetry or blanket error
suppression. These are fixture operator policies, not universal OTel rules.
