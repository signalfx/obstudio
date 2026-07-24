#!/usr/bin/env python3
"""Probe whether this execution environment permits a local TCP listener.

The probe is bounded and side-effect free beyond opening and immediately
closing one ephemeral IPv4 loopback socket. It does not start an application,
contact a network peer, or prove that an application's runtime path works.
"""

from __future__ import annotations

import json
import socket
from typing import Any, Callable


SCHEMA_VERSION = 1
HOST = "127.0.0.1"


def probe_loopback_bind(
    socket_factory: Callable[..., Any] = socket.socket,
) -> dict[str, object]:
    result: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "capability": "ipv4_loopback_tcp_bind",
        "complete": True,
        "candidate_only": True,
        "proof_boundary": (
            "An available bind is only a runtime-plan prerequisite. It does "
            "not prove application startup, readiness, telemetry emission, "
            "or OTLP export."
        ),
        "host": HOST,
        "requested_port": 0,
        "status": "blocked",
        "error": None,
    }
    listener = None
    try:
        listener = socket_factory(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((HOST, 0))
        listener.listen(1)
    except OSError as error:
        result["error"] = {
            "type": type(error).__name__,
            "errno": error.errno,
            "message": str(error),
        }
    else:
        result["status"] = "available"
    finally:
        if listener is not None:
            listener.close()
    return result


def main() -> int:
    print(json.dumps(probe_loopback_bind(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
