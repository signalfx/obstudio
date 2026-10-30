"""Credential-free stand-in for the existing native OTel resource setup path."""

import json
import os


def configure_resource_resolution(api_origin, project_name, stream_name):
    print(json.dumps({
        "status": "configured" if all((api_origin, project_name, stream_name)) else "local_only",
        "api_origin": api_origin,
        "project_name": project_name,
        "stream_name": stream_name,
    }, sort_keys=True))


if __name__ == "__main__":
    configure_resource_resolution(
        os.environ.get("SPLUNK_AO_API_URL"),
        os.environ.get("SPLUNK_AO_PROJECT"),
        os.environ.get("SPLUNK_AO_AGENT_STREAM"),
    )
