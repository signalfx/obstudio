from __future__ import annotations

import contextlib
import builtins
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


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
        self.assertEqual(raised.exception.code, "agent_stream_ambiguous_name")
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


class CLITests(unittest.TestCase):
    def run_with_environment(self, environment, arguments=None, clients=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        clients = clients or (Client([resource("p", "project")]), Client([resource("s", "stream", "p")]))
        with patch.dict(os.environ, environment, clear=True), patch.object(MODULE, "_sdk_clients", return_value=clients), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = MODULE.main(arguments or [])
        return result, json.loads(stdout.getvalue()), stderr.getvalue()

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
