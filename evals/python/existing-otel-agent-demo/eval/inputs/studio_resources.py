"""Loopback-only Studio resource API fixture; records requests, never calls cloud."""

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


SCENARIOS = (
    "existing", "missing", "mixed", "race", "stream_race", "ambiguous",
    "auth", "server_error", "wrong_parent", "uncertain_create",
    "reconcile_error", "pagination_error",
)


class ResourceServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, scenario, journal_path=None):
        super().__init__(("127.0.0.1", 0), ResourceHandler)
        self.scenario = scenario
        self.journal_path = Path(journal_path) if journal_path else None
        self.journal = []
        self.lock = threading.RLock()
        self.projects = [] if scenario in {"missing", "race", "uncertain_create", "reconcile_error"} else [self.project()]
        self.streams = [self.stream()] if scenario in {"existing", "auth", "server_error", "wrong_parent"} else []
        if scenario == "ambiguous":
            self.projects.append(self.project("ambiguous-project"))
        if scenario == "wrong_parent":
            self.streams[0]["project_id"] = "05e31022-a741-4a31-a5e1-1557544b9ab5"
        self.project_conflicted = False
        self.stream_conflicted = False
        self.reconciliation_failed = False

    @staticmethod
    def project(resource_id="b12aba69-843d-47ce-ae9a-7f385f498100"):
        return {"id": resource_id, "name": "fixture-project"}

    @staticmethod
    def stream():
        return {"id": "87abe6cc-c350-401f-9d09-b33955b02742", "name": "fixture-agent", "project_id": "b12aba69-843d-47ce-ae9a-7f385f498100"}

    def record(self, record):
        self.journal.append(json.loads(json.dumps(record)))
        if self.journal_path:
            self.journal_path.parent.mkdir(parents=True, exist_ok=True)
            self.journal_path.write_text(json.dumps(self.journal, indent=2) + "\n")

    @property
    def origin(self):
        return f"http://127.0.0.1:{self.server_port}"


class ResourceHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        self.handle_resource("GET")

    def do_POST(self):
        self.handle_resource("POST")

    def handle_resource(self, method):
        body = None
        if method == "POST":
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            except (ValueError, TypeError):
                self.reply(400, {"error": "invalid_json"})
                return
        with self.server.lock:
            status, response = self.resolve(method, body)
            self.server.record({
                "method": method, "path": self.path,
                "headers": {key.lower(): value for key, value in self.headers.items()},
                "body": body, "status": status, "response": response,
            })
        if status is None:
            self.close_connection = True
            self.connection.shutdown(2)
            self.connection.close()
            return
        self.reply(status, response)

    def resolve(self, method, body):
        server = self.server
        parts = urlsplit(self.path)
        path = parts.path
        prefix = "/ao/api/projects"
        if not path.startswith(prefix):
            return 404, {"error": "not_found"}
        if self.headers.get("X-SF-Token") != "local-gateway":
            return 401, {"error": "missing_local_marker"}
        if server.scenario == "auth":
            return 403, {"error": "fixture_permission_denied"}
        if server.scenario == "server_error":
            return 503, {"error": "fixture_unavailable"}
        if server.reconciliation_failed:
            return 503, {"error": "fixture_relookup_failed"}
        suffix = path[len(prefix):]
        if method == "GET" and suffix == "/all":
            if parse_qs(parts.query) != {"type": ["gen_ai"]}:
                return 400, {"error": "project_type_required"}
            return 200, server.projects
        if method == "POST" and suffix == "":
            if body != {"name": "fixture-project", "type": "gen_ai", "create_example_templates": False}:
                return 400, {"error": "unexpected_project_body"}
            if server.scenario in {"race", "reconcile_error"} and not server.project_conflicted:
                server.project_conflicted = True
                if server.scenario == "reconcile_error":
                    server.reconciliation_failed = True
                else:
                    server.projects.append(server.project())
                return 409, {"error": "duplicate"}
            if not server.projects:
                server.projects.append(server.project())
            if server.scenario == "uncertain_create":
                return None, {"error": "response_connection_closed_after_create"}
            return 200, server.projects[0]
        segments = suffix.strip("/").split("/")
        if method == "GET" and len(segments) == 1:
            resource = next((item for item in server.projects if item["id"] == segments[0]), None)
            return (200, resource) if resource else (404, {"error": "missing_project"})
        if len(segments) >= 2 and segments[1] == "log_streams":
            if not any(item["id"] == segments[0] for item in server.projects):
                return 404, {"error": "missing_project"}
            if method == "GET" and len(segments) == 3 and segments[2] == "paginated":
                query = parse_qs(parts.query)
                token = query.get("starting_token", [""])[0]
                if query.get("include_counts") != ["false"] or query.get("limit") != ["100"]:
                    return 400, {"error": "unexpected_pagination"}
                if server.scenario == "pagination_error":
                    if token == "0":
                        return 200, {"log_streams": [], "paginated": True, "next_starting_token": 100}
                    return 503, {"error": "fixture_later_page_unavailable"}
                return 200, {"log_streams": server.streams, "paginated": False, "next_starting_token": None}
            if method == "GET" and len(segments) == 3:
                resource = next((item for item in server.streams if item["id"] == segments[2]), None)
                return (200, resource) if resource else (404, {"error": "missing_stream"})
            if method == "POST" and len(segments) == 2:
                if body != {"name": "fixture-agent"}:
                    return 400, {"error": "unexpected_stream_body"}
                if server.scenario == "stream_race" and not server.stream_conflicted:
                    server.stream_conflicted = True
                    server.streams.append(server.stream())
                    return 409, {"error": "duplicate"}
                if not server.streams:
                    server.streams.append(server.stream())
                return 200, server.streams[0]
        return 404, {"error": "not_found"}

    def reply(self, status, payload):
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=SCENARIOS, default="existing")
    parser.add_argument("--ready-file", type=Path, required=True)
    parser.add_argument("--journal", type=Path, required=True)
    args = parser.parse_args()
    with ResourceServer(args.scenario, args.journal) as server:
        args.ready_file.parent.mkdir(parents=True, exist_ok=True)
        args.ready_file.write_text(json.dumps({"origin": server.origin, "scenario": args.scenario}) + "\n")
        server.serve_forever(poll_interval=0.1)


if __name__ == "__main__":
    main()
