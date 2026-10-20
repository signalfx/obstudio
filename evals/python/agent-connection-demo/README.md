# Agent connection fixture

This existing native OTel replay agent has local traces, metrics and correlated
logs. `python launch.py --profile PATH` loads an operator profile and runs one
model-directed tool/result turn. Resource setup is missing: inherited AO
headers currently reach the exporter without active-gateway validation.

Keep `app.py`, `telemetry.py`, and `probe.py` unchanged during instrumentation.
Implement selected project/stream and connection-aware routing work in the
launcher, owned setup scripts and profile. The probe uses local numeric-loopback
HTTP resource/OTLP boundaries and real SDK records, including a lost create
response after commit. Its cloud is synthetic; no receipt proves live Splunk.
