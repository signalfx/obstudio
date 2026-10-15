from __future__ import annotations

import contextlib
import builtins
import importlib.util
import io
import json
import os
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit


SCRIPT = Path(__file__).parents[1] / "scripts" / "resolve_ao_resources.py"
SPEC = importlib.util.spec_from_file_location("resolve_ao_resources", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def resource(resource_id: str, name: str, parent: str | None = None) -> SimpleNamespace:
    fields = {"id": resource_id, "name": name}
    if parent is not None:
        fields["project_id"] = parent
    return SimpleNamespace(**fields)


class HTTPError(Exception):
    def __init__(self, status: int) -> None:
        self.status_code = status
        super().__init__("private-token-and-response-body")


class Client:
    def __init__(self, resources: list | None = None) -> None:
        self.resources = resources or []
        self.create_calls: list[dict] = []
        self.lookup_calls: list[dict] = []
        self.lookup_error = None
        self.on_create = None

    def list(self, **scope):
        self.lookup_calls.append(scope)
        if self.lookup_error:
            raise self.lookup_error
        if scope:
            return [item for item in self.resources if item.project_id == scope["project_id"]]
        return self.resources.copy()

    def get(self, *, id, **scope):
        return next((item for item in self.list(**scope) if item.id == id), None)

    def create(self, *, name, **scope):
        self.create_calls.append({"name": name, **scope})
        if self.on_create:
            return self.on_create(name, scope)
        created = resource(f"id-{len(self.resources) + 1}", name, scope.get("project_id"))
        self.resources.append(created)
        return created


@contextlib.contextmanager
def local_studio(route):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def handle_resource(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            payload = json.loads(body) if body else None
            requests.append((self.command, self.path, payload, dict(self.headers)))
            status, response, headers = route(self.command, self.path, payload)
            if status is None:
                self.close_connection = True
                return
            encoded = response if isinstance(response, bytes) else json.dumps(response).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            if "Content-Length" not in headers:
                self.send_header("Content-Length", str(len(encoded)))
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()
            try:
                self.wfile.write(encoded)
            except OSError:
                pass  # A timeout test deliberately closes the connection.

        do_GET = handle_resource
        do_POST = handle_resource

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


class StudioResourceAPI:
    def __init__(self, *, existing=True):
        self.projects = [{"id": "p", "name": "project"}] if existing else []
        self.streams = [{"id": "s", "name": "stream", "project_id": "p"}] if existing else []

    def __call__(self, method, target, body):
        path = urlsplit(target).path
        if method == "GET" and path == "/ao/api/projects/all":
            return 200, self.projects, {}
        if method == "GET" and path == "/ao/api/projects/p/log_streams/paginated":
            return 200, {"log_streams": self.streams, "paginated": False}, {}
        if method == "POST" and path == "/ao/api/projects":
            project = {"id": "p", "name": body["name"], "ignored_secret": "private-response"}
            self.projects.append(project)
            return 200, project, {}
        if method == "POST" and path == "/ao/api/projects/p/log_streams":
            stream = {"id": "s", "name": body["name"], "project_id": "p"}
            self.streams.append(stream)
            return 200, stream, {}
        resources = self.streams if "/log_streams/" in path else self.projects
        found = next((item for item in resources if item["id"] == path.rsplit("/", 1)[-1]), None)
        return (200, found, {}) if found else (404, {"error": "private-response"}, {})


class ResolverTests(unittest.TestCase):
    def setUp(self):
        self.project = resource("p", "project")
        self.stream = resource("s", "stream", "p")

    def run_resolver(self, projects, streams, **kwargs):
        return MODULE.resolve_resources(
            projects, streams, project_name="project", agent_stream_name="stream",
            sleep=lambda _: None, **kwargs,
        )

    def test_both_existing_make_no_create_calls(self):
        projects, streams = Client([self.project]), Client([self.stream])
        evidence = self.run_resolver(projects, streams)
        self.assertEqual((evidence["project"]["outcome"], evidence["agent_stream"]["outcome"]), ("reused", "reused"))
        self.assertEqual(projects.create_calls + streams.create_calls, [])

    def test_both_missing_create_once_and_repeat_reuses(self):
        projects, streams = Client(), Client()
        evidence = self.run_resolver(projects, streams)
        self.assertEqual((evidence["project"]["outcome"], evidence["agent_stream"]["outcome"]), ("created", "created"))
        self.assertEqual(streams.create_calls, [{"name": "stream", "project_id": evidence["project"]["id"]}])
        second = self.run_resolver(projects, streams)
        self.assertEqual(second["project"]["outcome"], "reused")
        self.assertEqual(second["agent_stream"]["outcome"], "reused")
        self.assertEqual(len(projects.create_calls), 1)
        self.assertEqual(len(streams.create_calls), 1)

    def test_existing_project_creates_only_missing_stream(self):
        projects, streams = Client([self.project]), Client()
        evidence = self.run_resolver(projects, streams)
        self.assertEqual(evidence["project"]["outcome"], "reused")
        self.assertEqual(evidence["agent_stream"]["outcome"], "created")
        self.assertEqual(projects.create_calls, [])

    def test_created_project_reuses_stream_in_resolved_parent(self):
        projects, streams = Client(), Client([resource("s", "stream", "id-1")])
        evidence = self.run_resolver(projects, streams)
        self.assertEqual(evidence["project"]["outcome"], "created")
        self.assertEqual(evidence["agent_stream"]["outcome"], "reused")
        self.assertEqual(streams.create_calls, [])

    def test_same_stream_name_in_other_project_is_not_reused(self):
        projects, streams = Client([self.project]), Client([resource("other", "stream", "other-project")])
        evidence = self.run_resolver(projects, streams)
        self.assertEqual(evidence["agent_stream"]["outcome"], "created")
        self.assertEqual(streams.create_calls, [{"name": "stream", "project_id": "p"}])

    def test_creation_races_relookup_both_resources_once(self):
        projects, streams = Client(), Client()
        for client, item in ((projects, self.project), (streams, self.stream)):
            def race(name, scope, client=client, item=item):
                client.resources.append(item)
                raise HTTPError(409)
            client.on_create = race
        evidence = self.run_resolver(projects, streams)
        for kind in ("project", "agent_stream"):
            self.assertEqual(evidence[kind]["outcome"], "reused-after-conflict")
            self.assertEqual(evidence[kind]["create_attempts"], 1)
            self.assertEqual(evidence[kind]["relookup_attempts"], 1)

    def test_successful_creation_with_duplicate_name_fails_closed(self):
        projects, streams = Client([self.project]), Client()
        def duplicate(name, scope):
            streams.resources.extend([self.stream, resource("s2", "stream", "p")])
            return self.stream
        streams.on_create = duplicate
        with self.assertRaises(MODULE.ResolutionError) as raised:
            self.run_resolver(projects, streams)
        self.assertEqual(raised.exception.code, "agent_stream_ambiguous_name")
        self.assertEqual(len(streams.create_calls), 1)

    def test_created_identity_must_match_unique_post_create_lookup(self):
        projects, streams = Client([self.project]), Client()
        def mismatch(name, scope):
            streams.resources.append(self.stream)
            return resource("other-id", "stream", "p")
        streams.on_create = mismatch
        with self.assertRaises(MODULE.ResolutionError) as raised:
            self.run_resolver(projects, streams)
        self.assertEqual(raised.exception.code, "agent_stream_create_identity_mismatch")

    def test_successful_create_unseen_on_relookup_stays_unresolved(self):
        projects, streams = Client([self.project]), Client()
        streams.on_create = lambda name, scope: self.stream
        with self.assertRaises(MODULE.ResolutionError) as raised:
            self.run_resolver(projects, streams)
        self.assertEqual(raised.exception.code, "agent_stream_create_unresolved")
        self.assertEqual(raised.exception.evidence["agent_stream"]["id"], "s")
        self.assertEqual(len(streams.create_calls), 1)

    def test_unknown_sdk_error_and_timeout_relookup_without_repeat_create(self):
        for error in (Exception("opaque APIException"), TimeoutError("private endpoint")):
            with self.subTest(error=type(error).__name__):
                projects, streams = Client([self.project]), Client()
                def uncertain(name, scope):
                    streams.resources.append(self.stream)
                    raise error
                streams.on_create = uncertain
                evidence = self.run_resolver(projects, streams)
                self.assertEqual(evidence["agent_stream"]["outcome"], "reused-after-uncertain-create")
                self.assertEqual(len(streams.create_calls), 1)

    def test_unknown_failure_without_relookup_match_stays_failed(self):
        projects, streams = Client([self.project]), Client()
        def fail_create(name, scope):
            raise TimeoutError("private endpoint")
        streams.on_create = fail_create
        with self.assertRaises(MODULE.ResolutionError) as raised:
            self.run_resolver(projects, streams)
        evidence = raised.exception.evidence
        self.assertEqual(raised.exception.code, "agent_stream_create_unresolved")
        self.assertEqual(evidence["agent_stream"]["relookup_attempts"], 3)
        self.assertEqual(evidence["project"]["id"], "p")
        self.assertEqual(len(streams.create_calls), 1)

    def test_create_exception_remains_unresolved_when_relookup_fails(self):
        for kind in ("project", "agent_stream"):
            for create_error in (TimeoutError("private-create-body"), Exception("private-create-body"), HTTPError(409)):
                for relookup_failure in ("timeout", "http503", "ambiguous", "wrong_parent"):
                    if kind == "project" and relookup_failure == "wrong_parent":
                        continue
                    for project_exists in ((True, False) if kind == "agent_stream" else (False,)):
                        with self.subTest(kind=kind, create_error=type(create_error).__name__, relookup_failure=relookup_failure, project_exists=project_exists):
                            projects = Client([self.project] if project_exists else [])
                            streams = Client()
                            client = projects if kind == "project" else streams

                            def failed_create(name, scope):
                                if relookup_failure == "timeout":
                                    client.lookup_error = TimeoutError("private-lookup-body")
                                elif relookup_failure == "http503":
                                    client.lookup_error = HTTPError(503)
                                elif relookup_failure == "ambiguous":
                                    client.resources.extend([
                                        resource("r1", name, scope.get("project_id")),
                                        resource("r2", name, scope.get("project_id")),
                                    ])
                                else:
                                    def wrong_parent(**lookup_scope):
                                        client.lookup_calls.append(lookup_scope)
                                        return [resource("r1", name, "wrong-project")]
                                    client.list = wrong_parent
                                raise create_error

                            client.on_create = failed_create
                            with self.assertRaises(MODULE.ResolutionError) as raised:
                                self.run_resolver(projects, streams)
                            evidence = raised.exception.evidence
                            record = evidence[kind]
                            secondary = {
                                "timeout": "lookup_failed", "http503": "lookup_failed",
                                "ambiguous": "ambiguous_name", "wrong_parent": "wrong_project",
                            }[relookup_failure]
                            self.assertEqual(raised.exception.code, f"{kind}_create_unresolved")
                            self.assertEqual(evidence["error"], raised.exception.code)
                            self.assertEqual(record["reconciliation_error"], f"{kind}_{secondary}")
                            self.assertEqual(record["create_attempts"], 1)
                            self.assertEqual(record["relookup_attempts"], 1)
                            self.assertEqual(len(client.create_calls), 1)
                            self.assertEqual(record.get("create_http_status"), 409 if isinstance(create_error, HTTPError) else None)
                            self.assertEqual(record.get("lookup_http_status"), 503 if relookup_failure == "http503" else None)
                            serialized = json.dumps(evidence) + str(raised.exception)
                            self.assertNotIn("private-create-body", serialized)
                            self.assertNotIn("private-lookup-body", serialized)
                            self.assertNotIn("private-token-and-response-body", serialized)
                            if kind == "agent_stream":
                                resolved_project = evidence["project"]
                                self.assertEqual(resolved_project["id"], projects.resources[0].id)
                                self.assertEqual(resolved_project["outcome"], "reused" if project_exists else "created")
                                self.assertEqual(client.create_calls[0]["project_id"], resolved_project["id"])
                                self.assertTrue(all(call["project_id"] == resolved_project["id"] for call in client.lookup_calls))
                            else:
                                self.assertEqual(streams.lookup_calls + streams.create_calls, [])

    def test_successful_or_empty_create_keeps_relookup_failure_code(self):
        for create_return in (None, self.stream):
            projects, streams = Client([self.project]), Client()
            def create_then_lookup_failure(name, scope):
                streams.lookup_error = HTTPError(503)
                return create_return
            streams.on_create = create_then_lookup_failure
            with self.assertRaises(MODULE.ResolutionError) as raised:
                self.run_resolver(projects, streams)
            self.assertEqual(raised.exception.code, "agent_stream_lookup_failed")
            self.assertNotIn("reconciliation_error", raised.exception.evidence["agent_stream"])
            self.assertEqual(len(streams.create_calls), 1)

    def test_empty_create_response_reconciles(self):
        for malformed in (None, SimpleNamespace(name="stream")):
            projects, streams = Client([self.project]), Client()
            def empty(name, scope):
                streams.resources.append(self.stream)
                return malformed
            streams.on_create = empty
            evidence = self.run_resolver(projects, streams)
            self.assertEqual(evidence["agent_stream"]["outcome"], "reused-after-uncertain-create")

    def test_valid_create_response_with_wrong_parent_fails(self):
        projects, streams = Client([self.project]), Client()
        streams.on_create = lambda name, scope: resource("s", "stream", "wrong")
        with self.assertRaises(MODULE.ResolutionError) as raised:
            self.run_resolver(projects, streams)
        self.assertEqual(raised.exception.code, "agent_stream_wrong_project")
        self.assertEqual(len(streams.create_calls), 1)

    def test_known_http_create_errors_fail_even_if_resource_appears(self):
        for status in (401, 403, 400, 422, 429, 500, 503):
            for kind in ("project", "agent_stream"):
                with self.subTest(status=status, kind=kind):
                    projects = Client([] if kind == "project" else [self.project])
                    streams = Client()
                    client = projects if kind == "project" else streams
                    def forbidden(name, scope):
                        client.resources.append(self.project if kind == "project" else self.stream)
                        raise HTTPError(status)
                    client.on_create = forbidden
                    with self.assertRaises(MODULE.ResolutionError) as raised:
                        self.run_resolver(projects, streams)
                    record = raised.exception.evidence[kind]
                    self.assertEqual(record["create_http_status"], status)
                    self.assertEqual(record["relookup_attempts"], 0)
                    self.assertEqual(raised.exception.code, f"{kind}_create_failed")

    def test_lookup_errors_never_create(self):
        for error in (HTTPError(401), HTTPError(403), HTTPError(500), TimeoutError()):
            projects, streams = Client(), Client()
            projects.lookup_error = error
            with self.assertRaises(MODULE.ResolutionError) as raised:
                self.run_resolver(projects, streams)
            self.assertEqual(raised.exception.code, "project_lookup_failed")
            self.assertEqual(projects.create_calls + streams.create_calls, [])

    def test_stream_lookup_errors_never_create_stream(self):
        for error in (HTTPError(401), HTTPError(403), HTTPError(500), TimeoutError()):
            projects, streams = Client([self.project]), Client()
            streams.lookup_error = error
            with self.assertRaises(MODULE.ResolutionError) as raised:
                self.run_resolver(projects, streams)
            self.assertEqual(raised.exception.code, "agent_stream_lookup_failed")
            self.assertEqual(projects.create_calls + streams.create_calls, [])

    def test_ambiguous_project_or_stream_fails_without_creation(self):
        for kind in ("project", "agent_stream"):
            projects = Client([self.project, resource("p2", "project")]) if kind == "project" else Client([self.project])
            streams = Client([self.stream, resource("s2", "stream", "p")])
            with self.assertRaises(MODULE.ResolutionError) as raised:
                self.run_resolver(projects, streams)
            self.assertEqual(raised.exception.code, f"{kind}_ambiguous_name")
            self.assertEqual(projects.create_calls + streams.create_calls, [])

    def test_conflict_relookup_ambiguity_fails_without_another_create(self):
        projects, streams = Client([self.project]), Client()
        def conflict(name, scope):
            streams.resources.extend([self.stream, resource("s2", "stream", "p")])
            raise HTTPError(409)
        streams.on_create = conflict
        with self.assertRaises(MODULE.ResolutionError) as raised:
            self.run_resolver(projects, streams)
        self.assertEqual(raised.exception.code, "agent_stream_create_unresolved")
        self.assertEqual(raised.exception.evidence["agent_stream"]["reconciliation_error"], "agent_stream_ambiguous_name")
        self.assertEqual(len(streams.create_calls), 1)

    def test_wrong_parent_response_is_rejected(self):
        projects, streams = Client([self.project]), Client()
        streams.list = lambda **scope: [resource("s", "stream", "wrong")]
        with self.assertRaises(MODULE.ResolutionError) as raised:
            self.run_resolver(projects, streams)
        self.assertEqual(raised.exception.code, "agent_stream_wrong_project")
        self.assertEqual(streams.create_calls, [])

    def test_id_selectors_reuse_and_missing_ids_never_create(self):
        projects, streams = Client([self.project]), Client([self.stream])
        evidence = MODULE.resolve_resources(projects, streams, project_id="p", agent_stream_id="s")
        self.assertEqual(evidence["agent_stream"]["id"], "s")
        for project_id, stream_id, code in (("missing", "s", "project_id_not_found"), ("p", "missing", "agent_stream_id_not_found")):
            with self.assertRaises(MODULE.ResolutionError) as raised:
                MODULE.resolve_resources(projects, streams, project_id=project_id, agent_stream_id=stream_id)
            self.assertEqual(raised.exception.code, code)
        self.assertEqual(projects.create_calls + streams.create_calls, [])

    def test_mixed_name_and_id_selectors(self):
        evidence = MODULE.resolve_resources(Client([self.project]), Client([self.stream]), project_id="p", agent_stream_name="stream")
        self.assertEqual(evidence["project"]["selector"], "id")
        self.assertEqual(evidence["agent_stream"]["selector"], "name")

    def test_id_not_found_http_and_wrong_parent_fail_without_creation(self):
        projects, streams = Client([self.project]), Client([self.stream])
        streams.get = lambda **scope: resource("s", "stream", "wrong")
        with self.assertRaises(MODULE.ResolutionError) as raised:
            MODULE.resolve_resources(projects, streams, project_id="p", agent_stream_id="s")
        self.assertEqual(raised.exception.code, "agent_stream_wrong_project")
        projects.lookup_error = HTTPError(404)
        with self.assertRaises(MODULE.ResolutionError) as raised:
            MODULE.resolve_resources(projects, streams, project_id="missing", agent_stream_id="s")
        self.assertEqual(raised.exception.code, "project_id_not_found")
        self.assertEqual(projects.create_calls + streams.create_calls, [])

    def test_sdk_project_not_found_without_http_status_is_missing_id(self):
        class ProjectNotFoundError(Exception):
            pass

        projects, streams = Client(), Client()
        projects.lookup_error = ProjectNotFoundError("private-not-found-body")
        with patch.dict("sys.modules", {
            "splunk_ao.projects": SimpleNamespace(ProjectNotFoundError=ProjectNotFoundError),
        }):
            with self.assertRaises(MODULE.ResolutionError) as raised:
                MODULE.resolve_resources(projects, streams, project_id="missing", agent_stream_name="stream")
        self.assertEqual(raised.exception.code, "project_id_not_found")
        self.assertEqual(projects.create_calls + streams.create_calls + streams.lookup_calls, [])
        self.assertNotIn("private-not-found-body", json.dumps(raised.exception.evidence))

    def test_generic_sdk_error_body_never_implies_missing_project_id(self):
        class ProjectNotFoundError(Exception):
            pass

        projects, streams = Client(), Client()
        projects.lookup_error = Exception("404 ProjectNotFoundError: private-body")
        with patch.dict("sys.modules", {
            "splunk_ao.projects": SimpleNamespace(ProjectNotFoundError=ProjectNotFoundError),
        }):
            with self.assertRaises(MODULE.ResolutionError) as raised:
                MODULE.resolve_resources(projects, streams, project_id="missing", agent_stream_name="stream")
        self.assertEqual(raised.exception.code, "project_lookup_failed")
        self.assertEqual(projects.create_calls + streams.create_calls + streams.lookup_calls, [])
        self.assertNotIn("private-body", json.dumps(raised.exception.evidence))

    def test_sdk_not_found_on_name_lookup_never_authorizes_creation(self):
        class ProjectNotFoundError(Exception):
            pass

        projects, streams = Client(), Client()
        projects.lookup_error = ProjectNotFoundError("private-body")
        with patch.dict("sys.modules", {
            "splunk_ao.projects": SimpleNamespace(ProjectNotFoundError=ProjectNotFoundError),
        }):
            with self.assertRaises(MODULE.ResolutionError) as raised:
                self.run_resolver(projects, streams)
        self.assertEqual(raised.exception.code, "project_lookup_failed")
        self.assertEqual(projects.create_calls + streams.create_calls + streams.lookup_calls, [])

    def test_reuse_only_never_creates(self):
        for projects, streams, kind in ((Client(), Client(), "project"), (Client([self.project]), Client(), "agent_stream")):
            with self.assertRaises(MODULE.ResolutionError) as raised:
                self.run_resolver(projects, streams, reuse_only=True)
            self.assertEqual(raised.exception.code, f"{kind}_name_not_found_reuse_only")
            self.assertEqual(projects.create_calls + streams.create_calls, [])

    def test_partial_project_is_reused_after_stream_failure(self):
        projects, streams = Client(), Client()
        def fail_stream(name, scope):
            raise HTTPError(403)
        streams.on_create = fail_stream
        with self.assertRaises(MODULE.ResolutionError) as raised:
            self.run_resolver(projects, streams)
        self.assertEqual(raised.exception.evidence["project"]["outcome"], "created")
        streams.on_create = None
        evidence = self.run_resolver(projects, streams)
        self.assertEqual(evidence["project"]["outcome"], "reused")
        self.assertEqual(len(projects.create_calls), 1)

    def test_invalid_selectors_fail_before_any_lookup(self):
        for kwargs in ({}, {"project_name": "project", "project_id": "p", "agent_stream_name": "stream"}, {"project_name": "", "agent_stream_name": "stream"}, {"project_name": "project\n", "agent_stream_name": "stream"}, {"project_name": "project", "agent_stream_id": "s\x00"}, {"project_name": " project", "agent_stream_name": "stream"}):
            projects, streams = Client(), Client()
            with self.assertRaises(MODULE.ResolutionError) as raised:
                MODULE.resolve_resources(projects, streams, **kwargs)
            self.assertEqual(raised.exception.code, "invalid_selectors")
            self.assertEqual(projects.lookup_calls + streams.lookup_calls, [])

    def test_unicode_category_c_selectors_fail_before_any_sdk_call(self):
        for character in ("\u0085", "\u202e", "\u200b", "\u2066", "\ud800", "\ue000", "\u0378"):
            for key in ("project_name", "project_id", "agent_stream_name", "agent_stream_id"):
                with self.subTest(codepoint=f"U+{ord(character):04X}", selector=key):
                    selectors = {"project_name": "project", "agent_stream_name": "stream"}
                    if key.endswith("_id"):
                        selectors.pop(key.removesuffix("_id") + "_name")
                    selectors[key] = "safe" + character + "selector"
                    projects, streams = Client(), Client()
                    with self.assertRaises(MODULE.ResolutionError) as raised:
                        MODULE.resolve_resources(projects, streams, **selectors)
                    self.assertEqual(raised.exception.code, "invalid_selectors")
                    self.assertEqual(projects.lookup_calls + streams.lookup_calls, [])
                    self.assertEqual(projects.create_calls + streams.create_calls, [])

    def test_valid_unicode_names_are_preserved(self):
        project_name, stream_name = "Projet-caf\u00e9-\u9879\u76ee", "stream-e\u0301-\u6d41"
        projects = Client([resource("p", project_name)])
        streams = Client([resource("s", stream_name, "p")])
        evidence = MODULE.resolve_resources(
            projects, streams, project_name=project_name, agent_stream_name=stream_name,
        )
        self.assertEqual(evidence["project"]["name"], project_name)
        self.assertEqual(evidence["agent_stream"]["name"], stream_name)
        self.assertEqual(projects.create_calls + streams.create_calls, [])

    def test_selector_length_uses_unicode_codepoints(self):
        for character in ("x", "\U0001f9ea"):
            for key in ("project_name", "project_id", "agent_stream_name", "agent_stream_id"):
                for count in (512, 513):
                    with self.subTest(character=character, selector=key, count=count):
                        selectors = {"project_name": "project", "agent_stream_name": "stream"}
                        if key.endswith("_id"):
                            selectors.pop(key.removesuffix("_id") + "_name")
                        selectors[key] = character * count
                        project = resource(selectors.get("project_id", "p"), selectors.get("project_name", "project"))
                        stream = resource(selectors.get("agent_stream_id", "s"), selectors.get("agent_stream_name", "stream"), project.id)
                        projects, streams = Client([project]), Client([stream])
                        if count == 513:
                            with self.assertRaises(MODULE.ResolutionError) as raised:
                                MODULE.resolve_resources(projects, streams, **selectors)
                            self.assertEqual(raised.exception.code, "invalid_selectors")
                            self.assertEqual(projects.lookup_calls + streams.lookup_calls, [])
                        else:
                            evidence = MODULE.resolve_resources(projects, streams, **selectors)
                            self.assertEqual(evidence["status"], "resolved")
                        self.assertEqual(projects.create_calls + streams.create_calls, [])

    def test_fakes_work_with_sdk_imports_unavailable(self):
        original_import = builtins.__import__
        def without_sdk(name, *args, **kwargs):
            if name.startswith("splunk_ao"):
                raise ImportError("SDK not installed; gateway unavailable")
            return original_import(name, *args, **kwargs)
        with patch("builtins.__import__", side_effect=without_sdk):
            evidence = self.run_resolver(Client(), Client())
        self.assertEqual(evidence["status"], "resolved")


class SDKAdapterTests(unittest.TestCase):
    def test_all_pages_are_scanned_for_name_and_duplicates(self):
        calls = []
        stream = resource("s", "stream", "p")
        def page_loader(**kwargs):
            calls.append(kwargs)
            if kwargs["starting_token"] == 0:
                return SimpleNamespace(log_streams=[resource("x", "other", "p")], paginated=True, next_starting_token=7)
            return SimpleNamespace(log_streams=[stream], paginated=False, next_starting_token=None)
        client = SimpleNamespace(config=SimpleNamespace(api_client=object()))
        adapter = MODULE.SDKAgentStreams(client, page_loader=page_loader, unset_type=type("Unset", (), {}))
        self.assertEqual(adapter.list(project_id="p")[-1], stream)
        self.assertEqual([item["starting_token"] for item in calls], [0, 7])
        self.assertTrue(all(item["project_id"] == "p" for item in calls))

    def test_nonadvancing_or_malformed_page_fails(self):
        for response in (None, SimpleNamespace(log_streams=None), SimpleNamespace(log_streams=[], paginated=True, next_starting_token=0), SimpleNamespace(log_streams=[], next_starting_token=1)):
            adapter = MODULE.SDKAgentStreams(SimpleNamespace(config=SimpleNamespace(api_client=object())), page_loader=lambda **kwargs: response, unset_type=type("Unset", (), {}))
            with self.assertRaises(ValueError):
                adapter.list(project_id="p")

    def test_duplicate_name_on_later_page_is_not_hidden(self):
        def page_loader(**kwargs):
            token = kwargs["starting_token"]
            return SimpleNamespace(
                log_streams=[resource(f"s-{token}", "stream", "p")],
                paginated=token == 0, next_starting_token=7 if token == 0 else None,
            )
        client = SimpleNamespace(config=SimpleNamespace(api_client=object()))
        adapter = MODULE.SDKAgentStreams(client, page_loader=page_loader, unset_type=type("Unset", (), {}))
        with self.assertRaises(MODULE.ResolutionError) as raised:
            MODULE.resolve_resources(Client([resource("p", "project")]), adapter, project_name="project", agent_stream_name="stream")
        self.assertEqual(raised.exception.code, "agent_stream_ambiguous_name")

    def test_pagination_failure_never_creates_from_partial_results(self):
        def page_loader(**kwargs):
            if kwargs["starting_token"]:
                raise HTTPError(500)
            return SimpleNamespace(log_streams=[], paginated=True, next_starting_token=7)
        client = Client()
        client.config = SimpleNamespace(api_client=object())
        adapter = MODULE.SDKAgentStreams(client, page_loader=page_loader, unset_type=type("Unset", (), {}))
        with self.assertRaises(MODULE.ResolutionError) as raised:
            MODULE.resolve_resources(Client([resource("p", "project")]), adapter, project_name="project", agent_stream_name="stream")
        self.assertEqual(raised.exception.code, "agent_stream_lookup_failed")
        self.assertEqual(client.create_calls, [])


class StudioHTTPTests(unittest.TestCase):
    def resolve(self, origin, **selectors):
        projects, streams = MODULE._studio_clients(origin)
        return MODULE.resolve_resources(
            projects, streams,
            **(selectors or {"project_name": "project", "agent_stream_name": "stream"}),
            sleep=lambda _: None,
        )

    def run_cli(self, origin, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = MODULE.main([
                "--studio-api-origin", origin, "--project-name", "project",
                "--agent-stream-name", "stream", *arguments,
            ])
        return result, json.loads(stdout.getvalue()), stdout.getvalue() + stderr.getvalue()

    def test_sdk_free_cli_creates_once_repeats_reuse_and_sends_only_public_marker(self):
        api = StudioResourceAPI(existing=False)
        environment = {
            "SPLUNK_AO_API_KEY": "private-cloud-key", "SPLUNK_AO_URL": "https://private.example",
            "HTTP_PROXY": "http://proxy.invalid:1", "HTTPS_PROXY": "http://proxy.invalid:1",
            "ALL_PROXY": "http://proxy.invalid:1", "NO_PROXY": "",
        }
        with local_studio(api) as (origin, requests), patch.dict(os.environ, environment, clear=True), patch.object(MODULE, "_sdk_clients") as sdk:
            before = dict(os.environ)
            result, evidence, output = self.run_cli(origin)
            self.assertEqual(result, 0)
            self.assertEqual((evidence["project"]["outcome"], evidence["agent_stream"]["outcome"]), ("created", "created"))
            second_result, second, second_output = self.run_cli(origin)
            self.assertEqual(second_result, 0)
            self.assertEqual((second["project"]["outcome"], second["agent_stream"]["outcome"]), ("reused", "reused"))
            sdk.assert_not_called()
            self.assertEqual(dict(os.environ), before)
        creates = [(path, body) for method, path, body, _ in requests if method == "POST"]
        self.assertEqual(creates, [
            ("/ao/api/projects", {"name": "project", "type": "gen_ai", "create_example_templates": False}),
            ("/ao/api/projects/p/log_streams", {"name": "stream"}),
        ])
        for _, _, _, headers in requests:
            self.assertEqual(headers["X-SF-Token"], "local-gateway")
            self.assertNotIn("Authorization", headers)
            self.assertNotIn("Cookie", headers)
        serialized = json.dumps(requests) + output + second_output
        self.assertNotIn("private-cloud-key", serialized)
        self.assertNotIn("private.example", serialized)
        self.assertNotIn("private-response", output + second_output)

    def test_post_created_status_creates_both_resources_once_and_repeat_reuses(self):
        api = StudioResourceAPI(existing=False)
        def route(method, path, body):
            status, payload, headers = api(method, path, body)
            return (201 if method == "POST" else status), payload, headers
        with local_studio(route) as (origin, requests):
            result, evidence, _ = self.run_cli(origin)
            self.assertEqual(result, 0)
            self.assertEqual((evidence["project"]["outcome"], evidence["agent_stream"]["outcome"]), ("created", "created"))
            self.assertEqual(evidence["project"]["id"], "p")
            self.assertEqual(evidence["agent_stream"]["project_id"], "p")
            second_result, second, _ = self.run_cli(origin)
            self.assertEqual(second_result, 0)
            self.assertEqual((second["project"]["outcome"], second["agent_stream"]["outcome"]), ("reused", "reused"))
        self.assertEqual([path for method, path, _, _ in requests if method == "POST"], [
            "/ao/api/projects", "/ao/api/projects/p/log_streams",
        ])

    def test_stream_lookup_scans_all_pages_before_reusing_or_rejecting_duplicates(self):
        for duplicate in (False, True):
            api = StudioResourceAPI()
            def route(method, path, body):
                if "/paginated?" in path:
                    token = int(parse_qs(urlsplit(path).query)["starting_token"][0])
                    page = {
                        "log_streams": [{"id": f"s-{token}", "name": "stream" if token or duplicate else "other", "project_id": "p"}],
                        "paginated": token == 0, "next_starting_token": 7 if token == 0 else None,
                    }
                    return 200, page, {}
                return api(method, path, body)
            with self.subTest(duplicate=duplicate), local_studio(route) as (origin, requests):
                if duplicate:
                    with self.assertRaises(MODULE.ResolutionError) as raised:
                        self.resolve(origin)
                    self.assertEqual(raised.exception.code, "agent_stream_ambiguous_name")
                else:
                    self.assertEqual(self.resolve(origin)["agent_stream"]["id"], "s-7")
            stream_queries = [parse_qs(urlsplit(path).query) for _, path, _, _ in requests if "/paginated?" in path]
            self.assertEqual([query["starting_token"] for query in stream_queries], [["0"], ["7"]])
            self.assertTrue(all(query["include_counts"] == ["false"] and query["limit"] == ["100"] for query in stream_queries))
            self.assertFalse(any(method == "POST" for method, _, _, _ in requests))

    def test_explicit_null_token_is_eof_even_when_paginated_is_true(self):
        api = StudioResourceAPI()
        def route(method, path, body):
            if "/paginated?" in path:
                return 200, {"log_streams": api.streams, "paginated": True, "next_starting_token": None}, {}
            return api(method, path, body)
        with local_studio(route) as (origin, requests):
            self.assertEqual(self.resolve(origin)["agent_stream"]["outcome"], "reused")
        self.assertEqual(len(requests), 2)
        self.assertFalse(any(method == "POST" for method, _, _, _ in requests))

    def test_later_page_failure_or_wrong_parent_never_creates_from_partial_results(self):
        for failure in (401, 403, 503, "malformed", "wrong-parent", "timeout"):
            api = StudioResourceAPI()
            def route(method, path, body):
                if "/paginated?" not in path:
                    return api(method, path, body)
                if parse_qs(urlsplit(path).query)["starting_token"] == ["0"]:
                    return 200, {"log_streams": [], "paginated": True, "next_starting_token": 7}, {}
                if isinstance(failure, int):
                    return failure, {"error": "private-response"}, {}
                if failure == "wrong-parent":
                    return 200, {"log_streams": [{"id": "s", "name": "unrelated", "project_id": "other"}], "paginated": False}, {}
                if failure == "timeout":
                    time.sleep(0.05)
                return 200, b"private-response-not-json", {}
            with self.subTest(failure=failure), local_studio(route) as (origin, requests), patch.object(MODULE, "STUDIO_HTTP_TIMEOUT", 0.02):
                with self.assertRaises(MODULE.ResolutionError) as raised:
                    self.resolve(origin)
                self.assertEqual(raised.exception.code, "agent_stream_wrong_project" if failure == "wrong-parent" else "agent_stream_lookup_failed")
                self.assertNotIn("private-response", json.dumps(raised.exception.evidence))
            self.assertFalse(any(method == "POST" for method, _, _, _ in requests))

    def test_invalid_pages_fail_closed_and_pagination_is_bounded(self):
        pages = (
            None, [], {"log_streams": None}, {"log_streams": []},
            {"log_streams": [], "paginated": True, "next_starting_token": 0},
            {"log_streams": [], "paginated": True, "next_starting_token": -1},
            {"log_streams": [], "paginated": True, "next_starting_token": True},
            {"log_streams": [], "paginated": True},
            {"log_streams": [], "paginated": False, "next_starting_token": 7},
            {"log_streams": [{"name": "other", "project_id": "p"}], "paginated": False},
            {"log_streams": [{"id": "s", "name": {"bad": "shape"}, "project_id": "p"}], "paginated": False},
            {"log_streams": [{"id": "s", "project_id": "p"}], "paginated": False},
            {"log_streams": [{"id": "s", "name": "stream"}], "paginated": False},
        )
        api = StudioResourceAPI()
        for page in pages:
            def route(method, path, body):
                return (200, page, {}) if "/paginated?" in path else api(method, path, body)
            with self.subTest(page=page), local_studio(route) as (origin, requests):
                with self.assertRaises(MODULE.ResolutionError) as raised:
                    self.resolve(origin)
                self.assertEqual(raised.exception.code, "agent_stream_lookup_failed")
            self.assertFalse(any(method == "POST" for method, _, _, _ in requests))
        def endless(method, path, body):
            if "/paginated?" not in path:
                return api(method, path, body)
            token = int(parse_qs(urlsplit(path).query)["starting_token"][0])
            return 200, {"log_streams": [], "paginated": True, "next_starting_token": token + 1}, {}
        with local_studio(endless) as (origin, requests), patch.object(MODULE, "STUDIO_MAX_PAGES", 2):
            with self.assertRaises(MODULE.ResolutionError):
                self.resolve(origin)
        self.assertEqual(len(requests), 3)

    def test_resource_ids_validate_parent_and_missing_ids_never_create(self):
        for project_id, stream_id, code in (("p", "s", None), ("missing", "s", "project_id_not_found"), ("p", "missing", "agent_stream_id_not_found"), ("../api_keys", "s", "project_lookup_failed")):
            with self.subTest(project_id=project_id, stream_id=stream_id), local_studio(StudioResourceAPI()) as (origin, requests):
                if code:
                    with self.assertRaises(MODULE.ResolutionError) as raised:
                        self.resolve(origin, project_id=project_id, agent_stream_id=stream_id)
                    self.assertEqual(raised.exception.code, code)
                else:
                    self.assertEqual(self.resolve(origin, project_id=project_id, agent_stream_id=stream_id)["agent_stream"]["id"], "s")
            self.assertFalse(any(method == "POST" for method, _, _, _ in requests))
        api = StudioResourceAPI()
        api.streams[0]["project_id"] = "other"
        with local_studio(api) as (origin, _), self.assertRaises(MODULE.ResolutionError) as raised:
            self.resolve(origin, project_id="p", agent_stream_id="s")
        self.assertEqual(raised.exception.code, "agent_stream_wrong_project")

    def test_local_id_failures_never_import_the_sdk(self):
        original_import = builtins.__import__
        imports = []
        def without_sdk(name, *args, **kwargs):
            if name.startswith("splunk_ao"):
                imports.append(name)
                raise ImportError("SDK absent")
            return original_import(name, *args, **kwargs)
        with local_studio(StudioResourceAPI()) as (origin, _), patch("builtins.__import__", side_effect=without_sdk):
            with self.assertRaises(MODULE.ResolutionError) as raised:
                self.resolve(origin, project_id="../invalid", agent_stream_id="s")
            self.assertEqual(raised.exception.code, "project_lookup_failed")
        self.assertEqual(imports, [])

    def test_project_id_lookup_keeps_optional_name_contract(self):
        for project in ({"id": "p"}, {"id": "p", "name": None}):
            api = StudioResourceAPI()
            api.projects = [project]
            with self.subTest(project=project), local_studio(api) as (origin, requests):
                evidence = self.resolve(origin, project_id="p", agent_stream_id="s")
                self.assertEqual(evidence["project"]["id"], "p")
                self.assertEqual(evidence["agent_stream"]["project_id"], "p")
            self.assertFalse(any(method == "POST" for method, _, _, _ in requests))

    def test_conflicts_reconcile_by_identity_once_for_both_resources(self):
        api = StudioResourceAPI(existing=False)
        def route(method, path, body):
            response = api(method, path, body)
            return (409, {"error": "private-duplicate-response"}, {}) if method == "POST" else response
        with local_studio(route) as (origin, requests):
            evidence = self.resolve(origin)
            self.assertEqual((evidence["project"]["outcome"], evidence["agent_stream"]["outcome"]), ("reused-after-conflict", "reused-after-conflict"))
            second = self.resolve(origin)
            self.assertEqual(second["agent_stream"]["outcome"], "reused")
        self.assertEqual(sum(method == "POST" for method, _, _, _ in requests), 2)
        self.assertNotIn("private-duplicate-response", json.dumps(evidence))

    def test_unresolved_or_ambiguous_conflict_has_bounded_relookup_without_recreate(self):
        for ambiguous in (False, True):
            api = StudioResourceAPI(existing=False)
            def route(method, path, body):
                if method == "POST":
                    if ambiguous:
                        api.projects.extend([{"id": "p1", "name": "project"}, {"id": "p2", "name": "project"}])
                    return 409, {"error": "private-duplicate-response"}, {}
                return api(method, path, body)
            with self.subTest(ambiguous=ambiguous), local_studio(route) as (origin, requests):
                with self.assertRaises(MODULE.ResolutionError) as raised:
                    self.resolve(origin)
                self.assertEqual(raised.exception.code, "project_create_unresolved")
                record = raised.exception.evidence["project"]
                self.assertEqual(record["relookup_attempts"], 1 if ambiguous else 3)
                self.assertEqual(record["create_attempts"], 1)
                self.assertNotIn("agent_stream", raised.exception.evidence)
            self.assertEqual(sum(method == "POST" for method, _, _, _ in requests), 1)

    def test_unknown_create_errors_are_terminal_and_repeat_recovers_existing_identity(self):
        for failure in (403, 422, 503, "malformed"):
            api = StudioResourceAPI(existing=False)
            def route(method, path, body):
                response = api(method, path, body)
                if method != "POST":
                    return response
                if isinstance(failure, int):
                    return failure, {"error": "duplicate private-response"}, {}
                return 200, b"private-response-not-json", {}
            with self.subTest(failure=failure), local_studio(route) as (origin, requests), patch.object(MODULE, "STUDIO_HTTP_TIMEOUT", 0.02):
                with self.assertRaises(MODULE.ResolutionError) as raised:
                    self.resolve(origin)
                self.assertEqual(raised.exception.code, "project_create_failed")
                self.assertEqual(raised.exception.evidence["project"]["relookup_attempts"], 0)
                self.assertEqual(len(requests), 2)
                self.assertNotIn("private-response", json.dumps(raised.exception.evidence))
                api.streams.append({"id": "s", "name": "stream", "project_id": "p"})
                self.assertEqual(self.resolve(origin)["project"]["outcome"], "reused")
            self.assertEqual(sum(method == "POST" for method, _, _, _ in requests), 1)

    def test_transport_failure_after_create_reconciles_without_repeating_the_post(self):
        for kind in ("project", "agent_stream"):
            for failure in ("disconnect", "timeout"):
                api = StudioResourceAPI(existing=kind == "agent_stream")
                api.streams = []
                create_path = "/ao/api/projects" if kind == "project" else "/ao/api/projects/p/log_streams"
                def route(method, path, body):
                    response = api(method, path, body)
                    if method == "POST" and path == create_path:
                        if failure == "disconnect":
                            return None, None, {}
                        time.sleep(0.05)
                    return response
                with self.subTest(kind=kind, failure=failure), local_studio(route) as (origin, requests), patch.object(MODULE, "STUDIO_HTTP_TIMEOUT", 0.02):
                    evidence = self.resolve(origin)
                    self.assertEqual(evidence[kind]["outcome"], "reused-after-uncertain-create")
                    self.assertEqual(evidence[kind]["create_attempts"], 1)
                    self.assertEqual(evidence[kind]["relookup_attempts"], 1)
                    self.assertEqual(self.resolve(origin)[kind]["outcome"], "reused")
                self.assertEqual(sum(method == "POST" and path == create_path for method, path, _, _ in requests), 1)

    def test_truncated_project_or_stream_lookup_never_authorizes_creation(self):
        for kind in ("project", "agent_stream"):
            api = StudioResourceAPI(existing=kind == "agent_stream")
            api.streams = []
            lookup_path = "/ao/api/projects/all" if kind == "project" else "/ao/api/projects/p/log_streams/paginated"
            def route(method, target, body):
                status, payload, headers = api(method, target, body)
                if method == "GET" and urlsplit(target).path == lookup_path:
                    encoded = json.dumps(payload).encode()
                    return status, encoded, {"Content-Length": str(len(encoded) + 10), "Connection": "close"}
                return status, payload, headers
            with self.subTest(kind=kind), local_studio(route) as (origin, requests):
                result, evidence, output = self.run_cli(origin)
                self.assertEqual(result, 1)
                self.assertEqual(evidence["error"], f"{kind}_lookup_failed")
                self.assertEqual(evidence[kind]["lookup_attempts"], 1)
                self.assertEqual(evidence[kind]["create_attempts"], 0)
                self.assertNotIn("private-response", output)
                self.assertEqual(sum(method == "POST" for method, _, _, _ in requests), 0)

    def test_truncated_successful_create_reconciles_exact_identity_without_repeating_post(self):
        for kind in ("project", "agent_stream"):
            for status in (200, 201):
                api = StudioResourceAPI(existing=kind == "agent_stream")
                api.streams = []
                create_path = "/ao/api/projects" if kind == "project" else "/ao/api/projects/p/log_streams"
                def route(method, target, body):
                    response = api(method, target, body)
                    if method == "POST" and target == create_path:
                        encoded = json.dumps(response[1]).encode()
                        return status, encoded, {"Content-Length": str(len(encoded) + 10), "Connection": "close"}
                    return response
                with self.subTest(kind=kind, status=status), local_studio(route) as (origin, requests):
                    result, evidence, output = self.run_cli(origin)
                    self.assertEqual(result, 0)
                    self.assertEqual(evidence[kind]["outcome"], "reused-after-uncertain-create")
                    self.assertEqual(evidence[kind]["id"], "p" if kind == "project" else "s")
                    self.assertEqual(evidence[kind]["create_attempts"], 1)
                    self.assertEqual(evidence[kind]["relookup_attempts"], 1)
                    self.assertNotIn("create_response", evidence[kind])
                    self.assertEqual(evidence["agent_stream"]["project_id"], evidence["project"]["id"])
                    second_result, second, second_output = self.run_cli(origin)
                    self.assertEqual(second_result, 0)
                    self.assertEqual(second[kind]["outcome"], "reused")
                    self.assertNotIn("private-response", output + second_output)
                self.assertEqual(sum(method == "POST" and target == create_path for method, target, _, _ in requests), 1)

    def test_truncated_create_with_truncated_relookup_stays_unresolved_without_recreate(self):
        for kind in ("project", "agent_stream"):
            api = StudioResourceAPI(existing=kind == "agent_stream")
            api.streams = []
            create_path = "/ao/api/projects" if kind == "project" else "/ao/api/projects/p/log_streams"
            lookup_path = "/ao/api/projects/all" if kind == "project" else "/ao/api/projects/p/log_streams/paginated"
            attempted = False
            def route(method, target, body):
                nonlocal attempted
                status, payload, headers = api(method, target, body)
                if method == "POST" and target == create_path:
                    attempted = True
                if attempted and (target == create_path or urlsplit(target).path == lookup_path):
                    encoded = json.dumps(payload).encode()
                    return status, encoded, {"Content-Length": str(len(encoded) + 10), "Connection": "close"}
                return status, payload, headers
            with self.subTest(kind=kind), local_studio(route) as (origin, requests):
                result, evidence, output = self.run_cli(origin)
                self.assertEqual(result, 1)
                self.assertEqual(evidence["error"], f"{kind}_create_unresolved")
                self.assertEqual(evidence[kind]["reconciliation_error"], f"{kind}_lookup_failed")
                self.assertEqual(evidence[kind]["create_attempts"], 1)
                self.assertEqual(evidence[kind]["relookup_attempts"], 1)
                self.assertNotIn("id", evidence[kind])
                self.assertNotIn("private-response", output)
            self.assertEqual(sum(method == "POST" and target == create_path for method, target, _, _ in requests), 1)

    def test_unsupported_create_success_statuses_fail_without_relookup_or_retry(self):
        for kind in ("project", "agent_stream"):
            for status in (202, 204):
                api = StudioResourceAPI(existing=kind == "agent_stream")
                api.streams = []
                def route(method, path, body):
                    response = api(method, path, body)
                    return (status, response[1], response[2]) if method == "POST" else response
                with self.subTest(kind=kind, status=status), local_studio(route) as (origin, requests):
                    with self.assertRaises(MODULE.ResolutionError) as raised:
                        self.resolve(origin)
                    self.assertEqual(raised.exception.code, f"{kind}_create_failed")
                    record = raised.exception.evidence[kind]
                    self.assertEqual(record["create_http_status"], status)
                    self.assertEqual(record["create_attempts"], 1)
                    self.assertEqual(record["relookup_attempts"], 0)
                self.assertEqual(sum(method == "POST" for method, _, _, _ in requests), 1)

    def test_uncertain_transport_create_unresolved_or_failed_relookup_never_recreates(self):
        for failure in ("absent", "ambiguous", "lookup-error"):
            api = StudioResourceAPI(existing=False)
            attempted = False
            def route(method, path, body):
                nonlocal attempted
                if method == "POST":
                    attempted = True
                    if failure == "ambiguous":
                        api.projects.extend([{"id": "p1", "name": "project"}, {"id": "p2", "name": "project"}])
                    return None, None, {}
                if attempted and failure == "lookup-error":
                    return 503, {"error": "private-response"}, {}
                return api(method, path, body)
            with self.subTest(failure=failure), local_studio(route) as (origin, requests):
                with self.assertRaises(MODULE.ResolutionError) as raised:
                    self.resolve(origin)
                self.assertEqual(raised.exception.code, "project_create_unresolved")
                record = raised.exception.evidence["project"]
                self.assertEqual(record["create_attempts"], 1)
                self.assertEqual(record["relookup_attempts"], 3 if failure == "absent" else 1)
                self.assertNotIn("agent_stream", raised.exception.evidence)
                self.assertNotIn("private-response", json.dumps(raised.exception.evidence))
            self.assertEqual(sum(method == "POST" for method, _, _, _ in requests), 1)

    def test_lookup_errors_oversize_and_redirects_never_create_or_follow_location(self):
        with local_studio(StudioResourceAPI()) as (other_origin, other_requests):
            for status, payload in ((201, [{"id": "p", "name": "project"}]), (401, {}), (403, {}), (503, {}), (302, {}), (307, {}), (200, b"private-response-not-json"), (200, b"x" * 65)):
                def route(*_):
                    return status, payload, {"Location": other_origin + "/ao/api/projects/all"}
                with self.subTest(status=status, payload=payload), local_studio(route) as (origin, requests), patch.object(MODULE, "STUDIO_MAX_RESPONSE_BYTES", 64):
                    result, evidence, output = self.run_cli(origin)
                    self.assertEqual(result, 1)
                    self.assertEqual(evidence["error"], "project_lookup_failed")
                    self.assertNotIn("private-response", output)
                self.assertEqual(len(requests), 1)
                self.assertEqual(requests[0][0], "GET")
            self.assertEqual(other_requests, [])

    def test_malformed_project_list_or_later_identity_never_authorizes_creation(self):
        for payload in (
            {"items": []}, [{"name": "other"}],
            [{"id": "p"}], [{"id": "p", "name": None}],
            [{"id": "p", "name": "project"}, {"id": "p2"}],
            [{"id": "p", "name": "project"}, {"id": "../api_keys", "name": "other"}],
            [{"id": "p", "name": {"unexpected": "name"}}],
        ):
            with self.subTest(payload=payload), local_studio(lambda *_: (200, payload, {})) as (origin, requests):
                with self.assertRaises(MODULE.ResolutionError) as raised:
                    self.resolve(origin)
                self.assertEqual(raised.exception.code, "project_lookup_failed")
            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0][0], "GET")

    def test_origin_rejects_nonloopback_auth_paths_and_controls_before_requests(self):
        origins = (
            "", "http://localhost:4319", "http://remote.example:4319", "http://192.0.2.1:4319",
            "http://127.0.0.1", "http://127.0.0.1:0", "https://127.0.0.1:4319",
            "http://private-user:private-password@127.0.0.1:4319", "http://127.0.0.1:4319/ao/api",
            "http://127.0.0.1:4319?private-query", "http://127.0.0.1:4319#private-fragment",
            "http://127.0.0.1:4319\n", "http://[::1]:invalid", "http://127.0.0.1:4319?",
        )
        for origin in origins:
            with self.subTest(origin=origin), patch.object(MODULE.http.client, "HTTPConnection") as connection, patch.object(MODULE, "_sdk_clients") as sdk:
                result, evidence, output = self.run_cli(origin)
                self.assertEqual(result, 1)
                self.assertEqual(evidence["error"], "studio_api_origin_invalid")
                self.assertNotIn("private-", output)
                connection.assert_not_called()
                sdk.assert_not_called()
        self.assertEqual(MODULE.StudioAPI("http://[::1]:4319").host, "::1")


class CLITests(unittest.TestCase):
    def run_with_environment(self, environment, arguments=None, clients=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        clients = clients or (Client([resource("p", "project")]), Client([resource("s", "stream", "p")]))
        with patch.dict(os.environ, environment, clear=True), patch.object(MODULE, "_sdk_clients", return_value=clients), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = MODULE.main(arguments or [])
        return result, json.loads(stdout.getvalue()), stderr.getvalue()

    def test_overlong_cli_and_env_selectors_fail_before_sdk_initialization(self):
        keys = {
            "project_name": ("--project-name", "SPLUNK_AO_PROJECT"),
            "project_id": ("--project-id", "SPLUNK_AO_PROJECT_ID"),
            "agent_stream_name": ("--agent-stream-name", "SPLUNK_AO_AGENT_STREAM"),
            "agent_stream_id": ("--agent-stream-id", "SPLUNK_AO_AGENT_STREAM_ID"),
        }
        for character in ("x", "\U0001f9ea"):
            for key, (flag, env_key) in keys.items():
                for source in ("cli", "env"):
                    with self.subTest(selector=key, source=source, character=character):
                        environment = {"SPLUNK_AO_PROJECT": "project", "SPLUNK_AO_AGENT_STREAM": "stream"}
                        arguments = []
                        if source == "cli":
                            arguments = [flag, character * 513]
                        else:
                            if key.endswith("_id"):
                                environment.pop("SPLUNK_AO_PROJECT" if key.startswith("project") else "SPLUNK_AO_AGENT_STREAM")
                            environment[env_key] = character * 513
                        stdout = io.StringIO()
                        with patch.dict(os.environ, environment, clear=True), patch.object(MODULE, "_sdk_clients") as sdk, contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
                            self.assertEqual(MODULE.main(arguments), 1)
                        sdk.assert_not_called()
                        self.assertEqual(json.loads(stdout.getvalue())["error"], "invalid_selectors")

    def test_env_only_names_and_ids_resolve_existing_resources(self):
        for environment in (
            {"SPLUNK_AO_PROJECT": "project", "SPLUNK_AO_AGENT_STREAM": "stream"},
            {"SPLUNK_AO_PROJECT_ID": "p", "SPLUNK_AO_AGENT_STREAM_ID": "s"},
        ):
            result, evidence, stderr = self.run_with_environment(environment)
            self.assertEqual(result, 0)
            self.assertEqual(evidence["project"]["id"], "p")
            self.assertEqual(evidence["agent_stream"]["id"], "s")
            self.assertEqual(stderr, "")

    def test_env_fallback_reuse_only_never_creates_missing_resources(self):
        environment = {"SPLUNK_AO_PROJECT": "project", "SPLUNK_AO_AGENT_STREAM": "stream"}
        clients = (Client([resource("p", "project")]), Client())
        result, evidence, _ = self.run_with_environment(environment, ["--reuse-only"], clients)
        self.assertEqual(result, 1)
        self.assertEqual(evidence["error"], "agent_stream_name_not_found_reuse_only")
        self.assertEqual(clients[0].create_calls, [])
        self.assertEqual(clients[1].create_calls, [])

    def test_cli_project_selector_overrides_both_env_project_selectors(self):
        environment = {
            "SPLUNK_AO_PROJECT": "stale-project", "SPLUNK_AO_PROJECT_ID": "stale-id",
            "SPLUNK_AO_AGENT_STREAM": "stream",
        }
        for arguments in (["--project-name", "project"], ["--project-id", "p"]):
            result, evidence, _ = self.run_with_environment(environment, arguments)
            self.assertEqual(result, 0)
            self.assertEqual(evidence["project"]["id"], "p")

    def test_cli_stream_selector_overrides_both_env_stream_selectors(self):
        environment = {
            "SPLUNK_AO_PROJECT": "project", "SPLUNK_AO_AGENT_STREAM": "stale-stream",
            "SPLUNK_AO_AGENT_STREAM_ID": "stale-id",
        }
        for arguments in (["--agent-stream-name", "stream"], ["--agent-stream-id", "s"]):
            result, evidence, _ = self.run_with_environment(environment, arguments)
            self.assertEqual(result, 0)
            self.assertEqual(evidence["agent_stream"]["id"], "s")

    def test_unicode_category_c_cli_and_env_selectors_fail_before_sdk_initialization(self):
        selectors = (
            ("--project-name", "SPLUNK_AO_PROJECT", "SPLUNK_AO_PROJECT_ID"),
            ("--project-id", "SPLUNK_AO_PROJECT_ID", "SPLUNK_AO_PROJECT"),
            ("--agent-stream-name", "SPLUNK_AO_AGENT_STREAM", "SPLUNK_AO_AGENT_STREAM_ID"),
            ("--agent-stream-id", "SPLUNK_AO_AGENT_STREAM_ID", "SPLUNK_AO_AGENT_STREAM"),
        )
        for character in ("\u0085", "\u202e", "\u200b", "\u2066", "\ue000", "\u0378"):
            for flag, env_key, other_key in selectors:
                for source in ("cli", "env"):
                    with self.subTest(codepoint=f"U+{ord(character):04X}", selector=flag, source=source):
                        value = "safe" + character + "selector"
                        environment = {"SPLUNK_AO_PROJECT": "project", "SPLUNK_AO_AGENT_STREAM": "stream"}
                        arguments = [flag, value] if source == "cli" else []
                        if source == "env":
                            environment.pop(other_key, None)
                            environment[env_key] = value
                        projects, streams = Client(), Client()
                        stdout, stderr = io.StringIO(), io.StringIO()
                        with patch.dict(os.environ, environment, clear=True), patch.object(MODULE, "_sdk_clients", return_value=(projects, streams)) as sdk, contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                            result = MODULE.main(arguments)
                        sdk.assert_not_called()
                        self.assertEqual(result, 1)
                        self.assertEqual(json.loads(stdout.getvalue())["error"], "invalid_selectors")
                        self.assertEqual(projects.lookup_calls + streams.lookup_calls, [])
                        self.assertEqual(projects.create_calls + streams.create_calls, [])
                        self.assertNotIn(value, stdout.getvalue() + stderr.getvalue())

    def test_missing_env_selector_fails_before_sdk_initialization(self):
        for environment, code in (
            ({}, "project_selector_missing"),
            ({"SPLUNK_AO_PROJECT": "", "SPLUNK_AO_PROJECT_ID": ""}, "project_selector_missing"),
            ({"SPLUNK_AO_PROJECT": "project"}, "agent_stream_selector_missing"),
        ):
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.dict(os.environ, environment, clear=True), patch.object(MODULE, "_sdk_clients") as sdk, contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                self.assertEqual(MODULE.main([]), 1)
                sdk.assert_not_called()
            self.assertEqual(json.loads(stdout.getvalue())["error"], code)
            self.assertNotIn("project\"", stderr.getvalue())

    def test_environment_name_id_conflict_is_rejected_without_cloud_calls(self):
        for environment, code in (
            ({"SPLUNK_AO_PROJECT": "project", "SPLUNK_AO_PROJECT_ID": "p"}, "project_environment_selectors_conflict"),
            ({"SPLUNK_AO_PROJECT": "project", "SPLUNK_AO_AGENT_STREAM": "stream", "SPLUNK_AO_AGENT_STREAM_ID": "s"}, "agent_stream_environment_selectors_conflict"),
        ):
            stdout = io.StringIO()
            with patch.dict(os.environ, environment, clear=True), patch.object(MODULE, "_sdk_clients") as sdk, contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(MODULE.main([]), 1)
                sdk.assert_not_called()
            self.assertEqual(json.loads(stdout.getvalue())["error"], code)

    def test_cli_and_env_resolution_does_not_mutate_environment(self):
        environment = {
            "SPLUNK_AO_PROJECT_ID": "p", "SPLUNK_AO_AGENT_STREAM": "stream",
            "SPLUNK_AO_API_KEY": "private-key", "SPLUNK_AO_URL": "https://configured.example",
        }
        with patch.dict(os.environ, environment, clear=True):
            before = dict(os.environ)
            with patch.object(MODULE, "_sdk_clients", return_value=(Client(), Client())), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                MODULE.main(["--project-name", "new-project"])
            self.assertEqual(dict(os.environ), before)

    def test_environment_selectors_are_read_fresh_each_invocation(self):
        clients = (Client([resource("p", "project"), resource("p2", "second")]), Client([resource("s", "stream", "p"), resource("s2", "other-stream", "p2")]))
        with patch.object(MODULE, "_sdk_clients", return_value=clients) as sdk, contextlib.redirect_stdout(io.StringIO()):
            for project_id, stream_id in (("p", "s"), ("p2", "s2")):
                with patch.dict(os.environ, {"SPLUNK_AO_PROJECT_ID": project_id, "SPLUNK_AO_AGENT_STREAM_ID": stream_id}, clear=True):
                    self.assertEqual(MODULE.main([]), 0)
            self.assertEqual(sdk.call_count, 2)
        self.assertEqual(clients[1].lookup_calls[-1], {"project_id": "p2"})

    def test_output_is_private_resource_only_json(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "resources.json"
            target.write_text("old evidence")
            os.chmod(target, 0o644)
            with patch.object(MODULE, "_sdk_clients", return_value=(Client(), Client())), contextlib.redirect_stdout(io.StringIO()):
                result = MODULE.main(["--project-name", "project", "--agent-stream-name", "stream", "--output", str(target)])
            self.assertEqual(result, 0)
            self.assertEqual(json.loads(target.read_text())["status"], "resolved")
            self.assertEqual(os.stat(target).st_mode & 0o777, 0o600)

    def test_cli_failure_does_not_expose_sdk_error_values(self):
        projects = Client()
        projects.lookup_error = HTTPError(401)
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(MODULE, "_sdk_clients", return_value=(projects, Client())), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = MODULE.main(["--project-name", "project", "--agent-stream-name", "stream"])
        self.assertEqual(result, 1)
        self.assertNotIn("private-token", stdout.getvalue() + stderr.getvalue())
        self.assertIn("project_lookup_failed", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
