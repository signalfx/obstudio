---
name: obstudio-help
description: >-
  List the Obstudio skills available in the Codex plugin and point the user to
  the right skill for opening, checking, restarting, or stopping the local
  Observer.
---

# Obstudio Help

Use this skill when you want a quick index of the Obstudio commands available
in Codex.

This skill is read-only. It should not start, stop, or restart anything.
Observer command skills are loopback-only and use the fixed local Observer
endpoints at `127.0.0.1:3000`, `127.0.0.1:4317`, and `127.0.0.1:4318`.
Status, restart, and stop checks may require narrow elevated/outside-sandbox
permission for host-local endpoint or listener verification.
If Obstudio MCP is configured to a non-default endpoint, command skills should
report the custom URL but must not probe or control it automatically.

## Available Skills

- `observer-open` - open `http://127.0.0.1:3000/` and confirm the UI is
  reachable without starting, stopping, or restarting anything.
- `observer-status` - report whether the local Observer is installed,
  bootstrapped, and reachable using `http://127.0.0.1:3000/api/health`.
- `observer-restart` - restart the Observer only when the current plugin owns
  the runtime.
- `observer-stop` - stop the Observer only when the current plugin owns the
  runtime.
- `otel-audit` - scan a codebase for observability gaps.
- `otel-generate-app-collector-config` - generate coordinated Collector Helm
  files, Kubernetes YAML, and application connection config without deploying.
- `otel-instrument` - add OpenTelemetry instrumentation.
- `otel-verify` - verify existing instrumentation with deterministic checks.
- `splunk-configure` - generate detector and dashboard Terraform from audit
  reports.
- `splunk-dashboard` - generate dashboard Terraform from an audit report.
- `splunk-dashboard-publish` - diff and publish dashboard gaps.
- `splunk-detector-publish` - diff and publish detector gaps.

## Steps

1. Read the list above and pick the narrowest skill for the task.
2. If the user wants the local Observer UI, use `observer-open`.
3. If the user wants runtime state, use `observer-status`.
4. If the user wants a destructive action, check ownership before using
   `observer-restart` or `observer-stop`.
5. Do not route Observer command skills to alternate hosts from MCP or user
   config.
6. If Obstudio MCP is configured to a non-default endpoint, report:
   `Obstudio MCP is configured to a non-default endpoint: <url>. For safety,
   this command skill only verifies or controls the default loopback Observer
   at 127.0.0.1:3000. I will not probe or control the custom endpoint. Use the
   MCP server directly, update the config back to the default local Observer,
   or manually verify the custom Observer.`
