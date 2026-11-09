#!/usr/bin/env python3
"""Resolve or create one AO Project and its Agent Stream.

Run with the application's Python runner and configured SPLUNK_AO_* environment.
Omitted selectors use that environment; explicit selectors override it per
resource. An environment name/ID pair is rejected rather than guessed.
The default uses the installed SDK. --studio-api-origin explicitly selects an
SDK-free local Studio API proved reachable in the application's network namespace.
No credentials are accepted as arguments or copied into the evidence report.
This script downloads nothing and executes nothing; its only network access is
the installed SDK or a loopback-only Studio API origin.
"""

from __future__ import annotations

import argparse
import http.client
import ipaddress
import json
import os
import re
import sys
import tempfile
import time
import unicodedata
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
from urllib.parse import urlencode, urlsplit
from uuid import UUID


STUDIO_HTTP_TIMEOUT = 10
STUDIO_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
STUDIO_MAX_PAGES = 1000


class ResolutionError(Exception):
    """A value-free error carrying resumable, resource-only evidence."""

    def __init__(self, code: str, evidence: dict[str, Any]) -> None:
        self.code = code
        self.evidence = evidence
        super().__init__(code)


class StudioAPIError(Exception):
    """A local HTTP failure with no response body, URL, or credentials."""

    def __init__(self, status_code: int | None = None, *, uncertain_create: bool = False) -> None:
        self.status_code = status_code
        self.uncertain_create = uncertain_create
        super().__init__("studio_api_failed")


def native_trace_binding(evidence: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Derive native HTTP headers and trace-only Resource fields from one pair.

    This pure mapping does not resolve names, contact a gateway, change an
    environment, or configure SDK-owned exporters.
    """
    try:
        if evidence["status"] != "resolved":
            raise ValueError()
        project = evidence["project"]["id"]
        stream = evidence["agent_stream"]["id"]
        if evidence["agent_stream"]["project_id"] != project:
            raise ValueError()
        if any(not isinstance(value, str) or str(UUID(value)) != value.lower()
               for value in (project, stream)):
            raise ValueError()
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ValueError("invalid_native_trace_binding") from None
    return {
        "headers": {"projectid": project, "logstreamid": stream},
        "resource_attributes": {
            "splunk_ao.project.id": project,
            "splunk_ao.logstream.id": stream,
        },
    }


def _status(error: Exception) -> int | None:
    status = getattr(error, "status_code", None)
    if status is None:
        status = getattr(getattr(error, "response", None), "status_code", None)
    return status if isinstance(status, int) and not isinstance(status, bool) else None


def _project_not_found(error: Exception) -> bool:
    try:
        from splunk_ao.projects import ProjectNotFoundError
    except ImportError:
        return False
    return isinstance(error, ProjectNotFoundError)


def _identity(resource: Any, *, project_id: str | None = None) -> dict[str, str]:
    resource_id = getattr(resource, "id", None)
    name = getattr(resource, "name", None)
    if not isinstance(resource_id, str) or not resource_id.strip():
        raise ValueError("invalid_identity")
    result = {"id": resource_id}
    if isinstance(name, str):
        result["name"] = name
    if project_id is not None:
        if getattr(resource, "project_id", None) != project_id:
            raise ValueError("wrong_project")
        result["project_id"] = project_id
    return result


def _invalid_selector(value: Any) -> bool:
    return value is not None and (
        not isinstance(value, str) or not value.strip() or len(value) > 512
        or value != value.strip()
        or any(unicodedata.category(character).startswith("C") for character in value)
    )


def resolve_resources(
    projects: Any,
    agent_streams: Any,
    *,
    project_name: str | None = None,
    project_id: str | None = None,
    agent_stream_name: str | None = None,
    agent_stream_id: str | None = None,
    reuse_only: bool = False,
    relookup_attempts: int = 3,
    relookup_delay: float = 0.25,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Accept Projects-compatible clients and a stream client whose list is complete.

    A failed name lookup never authorizes creation. ID selectors never create.
    The CLI supplies adapters so name lookup covers every page.
    """
    evidence: dict[str, Any] = {"schema_version": 1, "status": "resolving"}

    def fail(code: str) -> None:
        evidence.update(status="failed", error=code)
        raise ResolutionError(code, evidence)

    selectors = ((project_name, project_id), (agent_stream_name, agent_stream_id))
    if any(
        (name is None) == (resource_id is None)
        or any(_invalid_selector(value) for value in (name, resource_id))
        for name, resource_id in selectors
    ):
        fail("invalid_selectors")
    if not 1 <= relookup_attempts <= 5 or not 0 <= relookup_delay <= 5:
        fail("invalid_relookup_bounds")

    def resolve(
        kind: str, client: Any, name: str | None, resource_id: str | None,
        parent_id: str | None = None,
    ) -> Any:
        record: dict[str, Any] = {
            "selector": "id" if resource_id is not None else "name",
            "lookup_attempts": 0, "create_attempts": 0, "relookup_attempts": 0,
        }
        evidence[kind] = record
        scope = {"project_id": parent_id} if parent_id is not None else {}

        def validate(resource: Any) -> Any:
            try:
                identity = _identity(resource, project_id=parent_id)
            except ValueError as error:
                fail(f"{kind}_{error.args[0]}")
            if resource_id is not None and identity["id"] != resource_id:
                fail(f"{kind}_selector_mismatch")
            if name is not None and identity.get("name") != name:
                fail(f"{kind}_selector_mismatch")
            record.update(identity)
            return resource

        def lookup() -> Any:
            record["lookup_attempts"] += 1
            try:
                if resource_id is not None:
                    resource = client.get(id=resource_id, **scope)
                    return validate(resource) if resource is not None else None
                resources = client.list(**scope)
                if not isinstance(resources, list):
                    fail(f"{kind}_invalid_lookup_response")
                matches = []
                for resource in resources:
                    # Validate all parent bindings before trusting an absent result.
                    _identity(resource, project_id=parent_id)
                    if getattr(resource, "name", None) == name:
                        matches.append(resource)
                if len(matches) > 1:
                    fail(f"{kind}_ambiguous_name")
                return validate(matches[0]) if matches else None
            except ResolutionError:
                raise
            except Exception as error:
                status = _status(error)
                if status is not None:
                    record["lookup_http_status"] = status
                # Missing selected IDs are failures, never name creation requests.
                if resource_id is not None and (
                    status == 404
                    or (
                        kind == "project" and status is None
                        and not isinstance(error, StudioAPIError) and _project_not_found(error)
                    )
                ):
                    fail(f"{kind}_id_not_found")
                if isinstance(error, ValueError) and error.args == ("wrong_project",):
                    fail(f"{kind}_wrong_project")
                fail(f"{kind}_lookup_failed")

        resource = lookup()
        if resource is not None:
            record["outcome"] = "reused"
            return resource
        if resource_id is not None:
            fail(f"{kind}_id_not_found")
        if reuse_only:
            fail(f"{kind}_name_not_found_reuse_only")

        record["create_attempts"] = 1
        creation_code = f"{kind}_create_unresolved"
        created_id = None
        create_exception = False
        try:
            resource = client.create(name=name, **scope)
        except Exception as error:
            status = _status(error)
            if status is not None:
                record["create_http_status"] = status
            # Legacy APIException omits HTTP status. Reconcile its uncertain
            # outcome by identity; never infer a duplicate from message text.
            if (status is not None and status != 409) or (
                isinstance(error, StudioAPIError) and status != 409 and not error.uncertain_create
            ):
                fail(f"{kind}_create_failed")
            create_exception = True
            reconciliation = "reused-after-conflict" if status == 409 else "reused-after-uncertain-create"
        else:
            if resource is not None:
                try:
                    _identity(resource, project_id=parent_id)
                except ValueError as error:
                    if error.args != ("invalid_identity",):
                        fail(f"{kind}_{error.args[0]}")
                else:
                    validate(resource)
                    created_id = resource.id
                    record["create_response"] = "identity-returned"
            reconciliation = "created" if created_id else "reused-after-uncertain-create"

        for attempt in range(relookup_attempts):
            if attempt:
                sleep(relookup_delay)
            record["relookup_attempts"] += 1
            try:
                resource = lookup()
            except ResolutionError as error:
                if not create_exception:
                    raise
                record["reconciliation_error"] = error.code
                fail(creation_code)
            if resource is not None:
                if created_id is not None and resource.id != created_id:
                    fail(f"{kind}_create_identity_mismatch")
                record["outcome"] = reconciliation
                return resource
        fail(creation_code)

    project = resolve("project", projects, project_name, project_id)
    resolve("agent_stream", agent_streams, agent_stream_name, agent_stream_id, project.id)
    evidence["status"] = "resolved"
    return evidence


class SDKAgentStreams:
    """Preserve page metadata the high-level SDK list() currently discards."""

    def __init__(self, client: Any, *, page_loader: Any, unset_type: type) -> None:
        self.client = client
        self.page_loader = page_loader
        self.unset_type = unset_type

    def list(self, *, project_id: str) -> list[Any]:
        resources: list[Any] = []
        token = 0
        seen_tokens = {token}
        # Bound a corrupt or endlessly advancing server response, with failure
        # rather than treating a partial scan as an absent name.
        for _ in range(1000):
            response = self.page_loader(
                client=self.client.config.api_client,
                project_id=project_id, limit=100, starting_token=token,
            )
            if response is None or not isinstance(getattr(response, "log_streams", None), list):
                raise ValueError("invalid_page")
            resources.extend(response.log_streams)
            paginated = getattr(response, "paginated", None)
            if paginated is False:
                return resources
            if paginated is not True:
                raise ValueError("invalid_pagination")
            next_token = getattr(response, "next_starting_token", None)
            if next_token is None or isinstance(next_token, self.unset_type):
                return resources
            if not isinstance(next_token, int) or isinstance(next_token, bool) or next_token in seen_tokens:
                raise ValueError("nonadvancing_pagination")
            seen_tokens.add(next_token)
            token = next_token
        raise ValueError("pagination_limit")

    def get(self, **kwargs: Any) -> Any:
        return self.client.get(**kwargs)

    def create(self, **kwargs: Any) -> Any:
        return self.client.create(**kwargs)


def _sdk_clients() -> tuple[Any, Any]:
    from splunk_ao.agent_streams import AgentStreams
    from splunk_ao.projects import Projects
    from splunk_ao.resources.api.log_stream import (
        list_log_streams_paginated_projects_project_id_log_streams_paginated_get as pages,
    )
    from splunk_ao.resources.types import Unset

    return Projects(), SDKAgentStreams(AgentStreams(), page_loader=pages.sync, unset_type=Unset)


def _studio_resource_id(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,512}", value):
        raise StudioAPIError()
    return value


def _studio_resource(payload: Any, *, stream: bool = False) -> Any:
    if not isinstance(payload, dict):
        raise StudioAPIError()
    fields = {"id": _studio_resource_id(payload.get("id"))}
    name = payload.get("name")
    if stream and (name is None or "project_id" not in payload):
        raise StudioAPIError()
    if name is not None:
        if _invalid_selector(name):
            raise StudioAPIError()
        fields["name"] = name
    if "project_id" in payload:
        fields["project_id"] = _studio_resource_id(payload["project_id"])
    return SimpleNamespace(**fields)


class StudioAPI:
    """Only the explicit numeric loopback API origin; no discovery or redirects."""

    def __init__(self, origin: str) -> None:
        try:
            parsed = urlsplit(origin)
            if (
                _invalid_selector(origin) or parsed.scheme != "http"
                or parsed.username is not None or parsed.password is not None
                or parsed.path not in ("", "/") or "?" in origin or "#" in origin
                or parsed.port is None or not 1 <= parsed.port <= 65535
                or not ipaddress.ip_address(parsed.hostname).is_loopback
            ):
                raise ValueError()
            self.host, self.port = parsed.hostname, parsed.port
        except (TypeError, ValueError):
            code = "studio_api_origin_invalid"
            raise ResolutionError(code, {"schema_version": 1, "status": "failed", "error": code}) from None

    def request(self, method: str, path: str, body: dict | None = None) -> Any:
        # HTTPConnection neither uses environment proxies/netrc nor follows a
        # Location header. The only authentication value is the public marker.
        connection = http.client.HTTPConnection(self.host, self.port, timeout=STUDIO_HTTP_TIMEOUT)
        response = None
        headers = {"Accept": "application/json", "X-SF-Token": "local-gateway"}
        encoded = None
        if body is not None:
            encoded = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        try:
            connection.request(method, "/ao/api/projects" + path, encoded, headers)
            response = connection.getresponse()
            if response.status != 200 and not (method == "POST" and response.status == 201):
                raise StudioAPIError(response.status)
            payload = response.read(STUDIO_MAX_RESPONSE_BYTES + 1)
            if len(payload) > STUDIO_MAX_RESPONSE_BYTES:
                raise StudioAPIError()
            if response.length not in (None, 0):
                raise StudioAPIError(uncertain_create=method == "POST")
            try:
                return json.loads(payload.decode("utf-8"))
            except (UnicodeError, ValueError):
                raise StudioAPIError() from None
        except StudioAPIError:
            raise
        except (OSError, http.client.HTTPException):
            # A transport failure can occur after the server committed a POST.
            # Reconcile by identity; the resolver never retries the creation.
            raise StudioAPIError(uncertain_create=True) from None
        finally:
            if response is not None:
                response.close()
            connection.close()


class StudioProjects:
    def __init__(self, api: StudioAPI) -> None:
        self.api = api

    def list(self) -> list[Any]:
        payload = self.api.request("GET", "/all?type=gen_ai")
        if not isinstance(payload, list):
            raise StudioAPIError()
        resources = [_studio_resource(item) for item in payload]
        if any(getattr(item, "name", None) is None for item in resources):
            raise StudioAPIError()
        return resources

    def get(self, *, id: str) -> Any:
        return _studio_resource(self.api.request("GET", "/" + _studio_resource_id(id)))

    def create(self, *, name: str) -> Any:
        return _studio_resource(self.api.request("POST", "", {
            "name": name, "type": "gen_ai", "create_example_templates": False,
        }))


class StudioAgentStreams:
    def __init__(self, api: StudioAPI) -> None:
        self.api = api

    def list(self, *, project_id: str) -> list[Any]:
        path = "/" + _studio_resource_id(project_id) + "/log_streams/paginated?"
        resources: list[Any] = []
        token = 0
        seen_tokens = {token}
        for _ in range(STUDIO_MAX_PAGES):
            page = self.api.request("GET", path + urlencode({
                "include_counts": "false", "limit": 100, "starting_token": token,
            }))
            if not isinstance(page, dict) or not isinstance(page.get("log_streams"), list):
                raise StudioAPIError()
            for item in page["log_streams"]:
                stream = _studio_resource(item, stream=True)
                _identity(stream, project_id=project_id)
                resources.append(stream)
            paginated = page.get("paginated")
            next_token = page.get("next_starting_token")
            if next_token is None and (
                paginated is False or (paginated is True and "next_starting_token" in page)
            ):
                return resources
            if (
                paginated is not True or not isinstance(next_token, int)
                or isinstance(next_token, bool) or next_token < 0 or next_token in seen_tokens
            ):
                raise StudioAPIError()
            seen_tokens.add(next_token)
            token = next_token
        raise StudioAPIError()

    def get(self, *, id: str, project_id: str) -> Any:
        path = "/" + _studio_resource_id(project_id) + "/log_streams/" + _studio_resource_id(id)
        return _studio_resource(self.api.request("GET", path), stream=True)

    def create(self, *, name: str, project_id: str) -> Any:
        path = "/" + _studio_resource_id(project_id) + "/log_streams"
        return _studio_resource(self.api.request("POST", path, {"name": name}), stream=True)


def _studio_clients(origin: str) -> tuple[Any, Any]:
    api = StudioAPI(origin)
    return StudioProjects(api), StudioAgentStreams(api)


def _write_evidence(path: Path, evidence: dict[str, Any]) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".ao-resources-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(evidence, output, indent=2)
            output.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _cli_selector(
    kind: str, name: str | None, resource_id: str | None, name_key: str, id_key: str,
) -> tuple[str | None, str | None]:
    if name is None and resource_id is None:
        name = os.environ.get(name_key) or None
        resource_id = os.environ.get(id_key) or None
        code = None
        if name is not None and resource_id is not None:
            code = f"{kind}_environment_selectors_conflict"
        elif name is None and resource_id is None:
            code = f"{kind}_selector_missing"
        if code:
            raise ResolutionError(code, {"schema_version": 1, "status": "failed", "error": code})
    if any(_invalid_selector(value) for value in (name, resource_id)):
        code = "invalid_selectors"
        raise ResolutionError(code, {"schema_version": 1, "status": "failed", "error": code})
    return name, resource_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    project = parser.add_mutually_exclusive_group()
    project.add_argument("--project-name", help="Otherwise use SPLUNK_AO_PROJECT")
    project.add_argument("--project-id", help="Otherwise use SPLUNK_AO_PROJECT_ID")
    stream = parser.add_mutually_exclusive_group()
    stream.add_argument("--agent-stream-name", help="Otherwise use SPLUNK_AO_AGENT_STREAM")
    stream.add_argument("--agent-stream-id", help="Otherwise use SPLUNK_AO_AGENT_STREAM_ID")
    parser.add_argument("--reuse-only", action="store_true")
    parser.add_argument(
        "--native-otel-binding", action="store_true",
        help="Include matching UUID headers and trace Resource fields for an existing native exporter",
    )
    parser.add_argument(
        "--studio-api-origin",
        help="Use SDK-free Studio HTTP at an explicitly discovered http://numeric-loopback:port origin",
    )
    parser.add_argument("--output", type=Path, help="Write resource-only JSON evidence atomically")
    args = parser.parse_args(argv)
    try:
        project_name, project_id = _cli_selector(
            "project", args.project_name, args.project_id,
            "SPLUNK_AO_PROJECT", "SPLUNK_AO_PROJECT_ID",
        )
        stream_name, stream_id = _cli_selector(
            "agent_stream", args.agent_stream_name, args.agent_stream_id,
            "SPLUNK_AO_AGENT_STREAM", "SPLUNK_AO_AGENT_STREAM_ID",
        )
        projects, streams = _studio_clients(args.studio_api_origin) if args.studio_api_origin is not None else _sdk_clients()
        evidence = resolve_resources(
            projects, streams, project_name=project_name, project_id=project_id,
            agent_stream_name=stream_name, agent_stream_id=stream_id,
            reuse_only=args.reuse_only,
        )
        if args.native_otel_binding:
            try:
                evidence["native_otel_binding"] = native_trace_binding(evidence)
            except ValueError:
                evidence.update(status="failed", error="invalid_native_trace_binding")
    except ResolutionError as error:
        evidence = error.evidence
    except ImportError:
        evidence = {"schema_version": 1, "status": "failed", "error": "sdk_unavailable"}
    except Exception:
        code = "studio_api_initialization_failed" if args.studio_api_origin is not None else "sdk_initialization_failed"
        evidence = {"schema_version": 1, "status": "failed", "error": code}
    if args.output:
        try:
            _write_evidence(args.output, evidence)
        except OSError:
            print("AO resource resolution: evidence_write_failed", file=sys.stderr)
            return 1
    print(json.dumps(evidence, indent=2))
    if evidence["status"] == "failed":
        print(f"AO resource resolution: {evidence['error']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
