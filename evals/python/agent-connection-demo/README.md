# Agent connection fixture

This existing native OTel replay agent has local traces, metrics and correlated
logs. `python launch.py --profile PATH` loads an operator profile and runs one
model-directed tool/result turn. Resource setup is missing: inherited AO
headers currently have no matching trace Resource binding.

Keep `app.py` and `probe.py` unchanged during instrumentation. Preserve the
existing providers and signals in `telemetry.py`; its trace exporter may use an
owned public delegate for a live binding. Implement project/stream resolution
in the launcher, owned setup scripts and profile. `AGENT_INTERACTIVE=1` runs
stdin-triggered turns within one provider lifecycle and PID. The seven-case
probe checks names-only recovery and retention of valid headers plus trace
Resource IDs across a temporary outage. The probe uses local numeric-loopback
HTTP resource/OTLP boundaries and real SDK records, including a lost create
response after commit. Its cloud is synthetic; no receipt proves live Splunk.

Run `python gateway_contract_check.py --resolver PATH` with the bundled
`resolve_ao_resources.py` CLI before the application probe. This checks the
gateway's pagination response, reuse, ordered creation and uncertain-create
recovery against the maintained helper rather than an actor-owned equivalent.
