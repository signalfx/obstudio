"""Current operator-supplied env generator; missing values remain blank."""
import os
import shlex
import sys
from pathlib import Path

FIELDS = (
    "OTEL_SERVICE_NAME", "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_PROTOCOL", "APPLICATION_KEEP_SETTING",
    "SPLUNK_AO_PROJECT", "SPLUNK_AO_PROJECT_ID",
    "SPLUNK_AO_AGENT_STREAM", "SPLUNK_AO_AGENT_STREAM_ID",
    "SPLUNK_AO_API_URL", "SPLUNK_AO_CONSOLE_URL", "SPLUNK_AO_API_KEY",
    "SPLUNK_AO_REALM", "SPLUNK_AO_O11Y_TOKEN",
)

if __name__ == "__main__":
    profile = Path(sys.argv[1])
    profile.write_text("".join(
        f"{name}={shlex.quote(os.environ.get(name, ''))}\n" for name in FIELDS
    ))
