### 6. Enable Debugging in VS Code

This step is REQUIRED whenever `.vscode/launch.json` exists.

1. Check whether `.vscode/launch.json` exists.
2. If it exists, update at least one debug configuration for this service to include:
   - `OTEL_EXPORTER_OTLP_ENDPOINT=<resolved-local-otlp-http-endpoint>`; use
     `http://127.0.0.1:4318` only when resolution reaches the conventional fallback
   - `OTEL_LOGS_EXPORTER=otlp` when no explicit exporter exists and the logs
     endpoint is absent or is the detected local Splunk Observability Studio endpoint
   - `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=<resolved-local-otlp-http-endpoint>/v1/logs`
     when the exporter is absent/`otlp` and no explicit logs endpoint exists;
     preserve an existing signal path and never double-append `/v1/logs`
   - `OTEL_METRIC_EXPORT_INTERVAL=1000`
   - `OTEL_BSP_SCHEDULE_DELAY=100`
   If an absent/`otlp` exporter is paired with an explicit non-local logs
   endpoint, do not add either logs setting; stop and report the operator-owned
   boundary conflict instead of enabling a Splunk Observability Studio log path.
3. After editing, report which configuration was updated, the file path, and whether the env vars were added or already present.
4. If `.vscode/launch.json` exists and you do not update it, stop and explain why.
5. If `.vscode/launch.json` does not exist, explicitly report: `No .vscode/launch.json found; Step 6 skipped.`

