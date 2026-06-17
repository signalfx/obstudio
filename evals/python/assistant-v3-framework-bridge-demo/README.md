# Assistant v3 Framework Bridge Demo

Small fixture for the GenAI single-source span contract. It represents an app
that already emits app-owned assistant v3 workflow, agent, chat, and tool spans,
while the runtime also preloads framework instrumentation for LangChain/OpenAI.

The correct skill behavior is to choose one canonical GenAI span source. For
this app, the app-owned spans are canonical because they preserve the stable
workflow name `assistant_v3_turn`, the stable agent name `deepagents`, and the
tool/model lifecycle emitted from the app's event translator. The instrumented
startup surface must suppress overlapping framework GenAI instrumentors before
`opentelemetry-instrument` bootstraps, while keeping HTTP/database/runtime
instrumentation active.

The fixture intentionally models the bad coexistence mode. When
`OTEL_PYTHON_DISABLED_INSTRUMENTATIONS` does not include both `langchain` and
`openai`, `app.py` returns framework shadow nodes such as `LangGraph` and
`step tools` alongside the app-owned nodes. A correct instrumentation pass
removes those shadow nodes by changing the startup surface, not by renaming the
canonical app-owned spans.
