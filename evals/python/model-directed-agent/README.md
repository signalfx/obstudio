# Model-directed agent regression fixture

SmashBot is a custom OpenAI tool-using assistant, with CLI (`python agent.py`)
and Flask (`python app.py`) entrypoints. The source has existing native OTel
providers and spans. Inspect their semantic correctness independently of names,
comments and the historical instrumentation test. `roles.py` also exposes an
independent one-request facade and a fixed two-stage composition; neither is
called by SmashBot. Fake model responses suffice for local tests; no cloud key
or AO adoption is needed. Use a project-compatible Python environment.
