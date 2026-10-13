#!/usr/bin/env python3
"""Resolve or create one AO Project and its Agent Stream using the installed SDK.

Run with the application's Python runner and configured SPLUNK_AO_* environment.
Omitted selectors use that environment; explicit selectors override it per
resource. An environment name/ID pair is rejected rather than guessed.
No credentials are accepted as arguments or copied into the evidence report.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import unicodedata
from pathlib import Path
from typing import Any, Callable


class ResolutionError(Exception):
    """A value-free error carrying resumable, resource-only evidence."""

    def __init__(self, code: str, evidence: dict[str, Any]) -> None:
        self.code = code
        self.evidence = evidence
        super().__init__(code)


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
    The CLI supplies SDKAgentStreams so name lookup covers every page.
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
                    or (kind == "project" and status is None and _project_not_found(error))
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
        try:
            resource = client.create(name=name, **scope)
        except Exception as error:
            status = _status(error)
            if status is not None:
                record["create_http_status"] = status
            # Legacy APIException omits HTTP status. Reconcile its uncertain
            # outcome by identity; never infer a duplicate from message text.
            if status is not None and status != 409:
                fail(f"{kind}_create_failed")
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
            resource = lookup()
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
        projects, streams = _sdk_clients()
        evidence = resolve_resources(
            projects, streams, project_name=project_name, project_id=project_id,
            agent_stream_name=stream_name, agent_stream_id=stream_id,
            reuse_only=args.reuse_only,
        )
    except ResolutionError as error:
        evidence = error.evidence
    except ImportError:
        evidence = {"schema_version": 1, "status": "failed", "error": "sdk_unavailable"}
    except Exception:
        evidence = {"schema_version": 1, "status": "failed", "error": "sdk_initialization_failed"}
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
