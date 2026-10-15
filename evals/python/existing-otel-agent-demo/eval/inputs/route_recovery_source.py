"""Application-owned runtime profile and trace-routing startup adapter."""

import json
from pathlib import Path


def configure_route(profile_path, trace_session, resolve):
    path = Path(profile_path)
    profile = json.loads(path.read_text())
    binding = profile.get("resolved_ids")
    if binding is None:
        result = resolve(profile["project_name"], profile["agent_stream_name"])
        binding = {
            "project_id": result["project"]["id"],
            "agent_stream_id": result["agent_stream"]["id"],
        }
        profile["resolved_ids"] = binding
        path.write_text(json.dumps(profile, indent=2) + "\n")
    trace_session.headers.update({
        "projectid": binding["project_id"],
        "logstreamid": binding["agent_stream_id"],
    })
    return profile
