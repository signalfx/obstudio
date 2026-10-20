# Model-directed agent regression fixture

SmashBot is a custom OpenAI tool-using assistant, with CLI (`python agent.py`)
and Flask (`python app.py`) entrypoints. The source has existing native OTel
providers and spans. Inspect their semantic correctness independently of names,
comments and the historical instrumentation test. `roles.py` also exposes an
independent one-request facade and a fixed two-stage composition; neither is
called by SmashBot. Fake model responses suffice for local tests; no live cloud key is needed.
Agent project, stream and routing readiness must still be assessed by default;
selected resource work is separate from the existing role-repair-only scope. Use a project-compatible Python environment.

Run `python checks/review_regressions.py` in that environment for web/CLI
history recovery after a failed tool round, JSON input validation, local
exporter header guards and the four-case native telemetry probe. Real local
HTTP receipts also check generic and signal-specific trace/metric headers
without leaking inherited destination headers into the local log request. These checks
use fake model responses and make no cloud calls. The probe's default mode
preserves the fixture's intentionally incorrect workflow label; `--expect-agent`
remains the acceptance check after a selected role repair.
