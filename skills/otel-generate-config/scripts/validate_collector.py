#!/usr/bin/env python3
"""Statically validate generated Collector deployment configuration."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


REQUIRED_FILES = (
    "collector-config.yaml",
    "helm/Chart.yaml",
    "helm/values.yaml",
    "helm/examples/splunk-secret.yaml",
    "kubernetes/collector.yaml",
    "kubernetes/splunk-secret.example.yaml",
    "DEPLOYMENT.md",
)
EXAMPLE_SECRET_FILES = {
    "helm/examples/splunk-secret.yaml",
    "kubernetes/splunk-secret.example.yaml",
}
OFFICIAL_CHART_REPOSITORY = (
    "https://signalfx.github.io/splunk-otel-collector-chart"
)
EXACT_CHART_VERSION = re.compile(
    r"^\s*-\s*name:\s*splunk-otel-collector\s*$"
    r"(?:(?!^\s*-\s*name:).)*?"
    r"^\s*version:\s*[\"']?"
    r"((?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?)"
    r"[\"']?\s*$",
    re.MULTILINE | re.DOTALL,
)
CHART_REPOSITORY = re.compile(
    r"^\s*-\s*name:\s*splunk-otel-collector\s*$"
    r"(?:(?!^\s*-\s*name:).)*?"
    r"^\s*repository:\s*[\"']?([^\"'\s]+)[\"']?\s*$",
    re.MULTILINE | re.DOTALL,
)
INLINE_ACCESS_TOKEN = re.compile(
    r"^[ \t]*(?P<quote>[\"']?)accessToken(?P=quote)[ \t]*:"
    r"[ \t]*(?![\"']{2}[ \t]*$)(\S.*)$",
    re.MULTILINE,
)
EXISTING_SECRET = re.compile(
    r"^[ \t]*(?P<quote>[\"']?)existingSecret(?P=quote)[ \t]*:",
    re.MULTILINE,
)
STRING_DATA = re.compile(
    r"^[ \t]*(?P<quote>[\"']?)stringData(?P=quote)[ \t]*:",
    re.MULTILINE,
)
TOKEN_PASSTHROUGH = re.compile(
    r"^[ \t]*(?P<quote>[\"']?)tokenPassthrough(?P=quote)"
    r"[ \t]*:[ \t]*(?P<value>[^\s#]+)",
    re.MULTILINE,
)
UNRESOLVED = re.compile(r"@@[A-Z0-9_]+@@")
LEGACY_INGEST = re.compile(r"https://ingest\.[^/\s]+\.signalfx\.com")
TEXT_SUFFIXES = {".json", ".lock", ".md", ".txt", ".yaml", ".yml"}
COLLECTOR_MANIFEST_PATH = "kubernetes/collector.yaml"
RENDERED_PATH = COLLECTOR_MANIFEST_PATH
LEGACY_RENDERED_PATH = "kubernetes/helm-rendered.yaml"
PROVENANCE_PATH = "kubernetes/helm-rendered.provenance.json"
HELM_ALLOWED_FILES = {
    "helm/Chart.yaml",
    "helm/Chart.lock",
    "helm/examples/splunk-secret.yaml",
    "helm/values.yaml",
}
HELM_ALLOWED_DIRECTORIES = {
    "helm/charts",
    "helm/examples",
}
DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
DNS_SUBDOMAIN = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
YAML_DOCUMENT_BOUNDARY = re.compile(r"^---\s*(?:#.*)?$", re.MULTILINE)
SECRET_TOKEN_KEY = re.compile(
    r"^[ \t]*(?P<quote>[\"']?)splunk_observability_access_token"
    r"(?P=quote)[ \t]*:"
    r"[ \t]*(?P<value>[^\r\n]*?)[ \t]*$",
    re.MULTILINE,
)
SECRET_TOKEN_MAPPING_KEY = re.compile(
    r"(?<![A-Za-z0-9_])(?P<quote>[\"']?)"
    r"splunk_observability_access_token(?P=quote)[ \t]*:"
)


def expected_dependency_archive_name(lock: str) -> str:
    version_match = EXACT_CHART_VERSION.search(lock)
    if not version_match:
        raise ValueError("helm/Chart.lock has no exact Splunk chart version")
    archive_version = version_match.group(1).replace("+", "_")
    return f"splunk-otel-collector-{archive_version}.tgz"


def expected_dependency_archives(bundle: Path) -> tuple[str, ...]:
    lock_path = bundle / "helm" / "Chart.lock"
    try:
        lock = lock_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"cannot read Helm dependency lock: {exc}") from exc
    expected_name = expected_dependency_archive_name(lock)
    charts = bundle / "helm" / "charts"
    if charts.is_symlink() or not charts.is_dir():
        raise ValueError("helm/charts must be a real directory after dependency update")
    archives = sorted(
        path.relative_to(bundle).as_posix()
        for path in charts.iterdir()
        if path.is_file() and path.suffix == ".tgz"
    )
    expected = f"helm/charts/{expected_name}"
    if archives != [expected]:
        found = ", ".join(archives) if archives else "none"
        raise ValueError(
            "Helm dependency archives differ from Chart.lock; expected exactly "
            f"{expected}, found {found}"
        )
    return tuple(archives)


def unexpected_helm_render_inputs(bundle: Path) -> list[str]:
    helm = bundle / "helm"
    if helm.is_symlink() or not helm.is_dir():
        return []

    allowed_files = set(HELM_ALLOWED_FILES)
    lock_path = helm / "Chart.lock"
    if lock_path.is_file() and not lock_path.is_symlink():
        try:
            lock = lock_path.read_text(encoding="utf-8")
            archive_name = expected_dependency_archive_name(lock)
        except (OSError, UnicodeError, ValueError):
            pass
        else:
            allowed_files.add(f"helm/charts/{archive_name}")

    errors: list[str] = []
    for path in sorted(helm.rglob("*")):
        if path.is_symlink():
            continue
        relative = path.relative_to(bundle).as_posix()
        if path.is_dir():
            allowed = relative in HELM_ALLOWED_DIRECTORIES
        elif path.is_file():
            allowed = relative in allowed_files
        else:
            allowed = False
        if not allowed:
            errors.append(f"unexpected Helm input: {relative}")
    return errors


def _strip_yaml_comment(value: str) -> str:
    quote: str | None = None
    index = 0
    while index < len(value):
        character = value[index]
        if quote == '"':
            if character == "\\":
                index += 2
                continue
            if character == '"':
                quote = None
        elif quote == "'":
            if character == "'" and index + 1 < len(value) and value[index + 1] == "'":
                index += 2
                continue
            if character == "'":
                quote = None
        elif character in "\"'":
            quote = character
        elif character == "#" and (
            index == 0 or value[index - 1].isspace()
        ):
            return value[:index].rstrip()
        index += 1
    return value.rstrip()


def _yaml_key_and_value(fragment: str) -> tuple[str, str] | None:
    quote: str | None = None
    index = 0
    while index < len(fragment):
        character = fragment[index]
        if quote == '"':
            if character == "\\":
                index += 2
                continue
            if character == '"':
                quote = None
        elif quote == "'":
            if character == "'" and index + 1 < len(fragment) and fragment[index + 1] == "'":
                index += 2
                continue
            if character == "'":
                quote = None
        elif character in "\"'":
            quote = character
        elif character == ":" and (
            index + 1 == len(fragment) or fragment[index + 1].isspace()
        ):
            raw_key = fragment[:index].strip()
            if not raw_key:
                return None
            if raw_key.startswith('"') and raw_key.endswith('"'):
                try:
                    key = json.loads(raw_key)
                except json.JSONDecodeError:
                    key = raw_key
            elif raw_key.startswith("'") and raw_key.endswith("'"):
                key = raw_key[1:-1].replace("''", "'")
            else:
                key = raw_key
            return str(key), fragment[index + 1 :].strip()
        index += 1
    return None


def yaml_mapping_entry(
    line: str,
) -> tuple[int, bool, str, str] | None:
    prefix = line[: len(line) - len(line.lstrip(" \t"))]
    if "\t" in prefix:
        return None
    indent = len(prefix)
    content = _strip_yaml_comment(line[indent:]).rstrip()
    if not content:
        return None
    sequence_item = content == "-" or content.startswith("- ")
    if sequence_item:
        content = content[1:].lstrip()
        if not content:
            return indent + 2, True, "", ""
    parsed = _yaml_key_and_value(content)
    if not parsed:
        return None
    key, value = parsed
    logical_indent = indent + 2 if sequence_item else indent
    return logical_indent, sequence_item, key, value


def duplicate_yaml_mapping_keys(relative: str, text: str) -> list[str]:
    errors: list[str] = []
    scopes: dict[int, set[str]] = {}
    block_scalar_indent: int | None = None
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if YAML_DOCUMENT_BOUNDARY.fullmatch(line) or stripped == "...":
            scopes.clear()
            block_scalar_indent = None
            continue
        raw_prefix = line[: len(line) - len(line.lstrip(" \t"))]
        if "\t" in raw_prefix:
            errors.append(
                f"{relative}:{line_number} uses a tab for YAML indentation"
            )
            continue
        physical_indent = len(raw_prefix)
        if block_scalar_indent is not None:
            if not stripped or physical_indent > block_scalar_indent:
                continue
            block_scalar_indent = None
        entry = yaml_mapping_entry(line)
        if not entry:
            continue
        logical_indent, sequence_item, key, value = entry
        if sequence_item:
            for indent in [item for item in scopes if item >= logical_indent]:
                del scopes[indent]
        else:
            for indent in [item for item in scopes if item > logical_indent]:
                del scopes[indent]
        scope = scopes.setdefault(logical_indent, set())
        if key:
            if key in scope:
                errors.append(
                    f"{relative}:{line_number} has duplicate YAML mapping key "
                    f"{key!r}"
                )
            else:
                scope.add(key)
        if value in {"|", ">", "|-", ">-", "|+", ">+"}:
            block_scalar_indent = physical_indent
    return errors


def yaml_section(
    text: str,
    key: str,
    *,
    indent: int | None = None,
) -> tuple[str, int] | None:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        entry = yaml_mapping_entry(line)
        if not entry:
            continue
        logical_indent, sequence_item, candidate, value = entry
        if (
            sequence_item
            or candidate != key
            or value
            or (indent is not None and logical_indent != indent)
        ):
            continue
        body: list[str] = []
        parent_indent = logical_indent
        for child in lines[index + 1 :]:
            if not child.strip() or child.lstrip().startswith("#"):
                body.append(child)
                continue
            child_entry = yaml_mapping_entry(child)
            child_indent = len(child) - len(child.lstrip(" "))
            indentless_list = (
                child_entry is not None
                and child_entry[1]
                and child_indent == parent_indent
            )
            if child_indent <= parent_indent and not indentless_list:
                break
            body.append(child)
        return "\n".join(body), parent_indent
    return None


def yaml_scalar(text: str, key: str, *, indent: int) -> str | None:
    values: list[str] = []
    for line in text.splitlines():
        entry = yaml_mapping_entry(line)
        if not entry:
            continue
        logical_indent, sequence_item, candidate, value = entry
        if not sequence_item and logical_indent == indent and candidate == key:
            values.append(value)
    if len(values) != 1:
        return None
    value = values[0]
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        if value[0] == '"':
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return None
            return parsed if isinstance(parsed, str) else None
        return value[1:-1].replace("''", "'")
    return value


def direct_child_indent(text: str, parent_indent: int) -> int | None:
    candidates = [
        entry[0]
        for line in text.splitlines()
        if (entry := yaml_mapping_entry(line)) is not None
        and entry[0] > parent_indent
    ]
    return min(candidates, default=None)


def nested_yaml_scalar(text: str, path: tuple[str, ...]) -> str | None:
    body = text
    indent = 0
    for key in path[:-1]:
        result = yaml_section(body, key, indent=indent)
        if not result:
            return None
        body, parent_indent = result
        child_indent = direct_child_indent(body, parent_indent)
        if child_indent is None:
            return None
        indent = child_indent
    return yaml_scalar(body, path[-1], indent=indent)


def split_yaml_documents(text: str) -> list[str]:
    return [
        document
        for document in YAML_DOCUMENT_BOUNDARY.split(text)
        if any(
            line.strip() and not line.lstrip().startswith("#")
            for line in document.splitlines()
        )
    ]


def matching_service_routes(
    text: str,
    *,
    service: str,
    namespace: str,
    port_name: str,
    port: int,
) -> tuple[int, bool]:
    matching_services = 0
    duplicate_ports = False
    for document in split_yaml_documents(text):
        if yaml_scalar(document, "kind", indent=0) != "Service":
            continue
        metadata_result = yaml_section(document, "metadata", indent=0)
        spec_result = yaml_section(document, "spec", indent=0)
        if not metadata_result or not spec_result:
            continue
        metadata, metadata_indent = metadata_result
        metadata_child_indent = direct_child_indent(metadata, metadata_indent)
        if metadata_child_indent is None:
            continue
        if (
            yaml_scalar(metadata, "name", indent=metadata_child_indent)
            != service
            or yaml_scalar(metadata, "namespace", indent=metadata_child_indent)
            != namespace
        ):
            continue
        spec, spec_indent = spec_result
        spec_child_indent = direct_child_indent(spec, spec_indent)
        if spec_child_indent is None:
            continue
        ports_result = yaml_section(spec, "ports", indent=spec_child_indent)
        if not ports_result:
            continue
        ports, ports_indent = ports_result
        port_entries: list[dict[str, str]] = []
        current: dict[str, str] | None = None
        current_indent: int | None = None
        for line in ports.splitlines():
            entry = yaml_mapping_entry(line)
            if not entry:
                continue
            logical_indent, sequence_item, key, value = entry
            if sequence_item:
                if current is not None:
                    port_entries.append(current)
                current = {}
                current_indent = logical_indent
            if (
                current is not None
                and current_indent == logical_indent
                and key
            ):
                current[key] = value.strip("\"'")
        if current is not None:
            port_entries.append(current)
        matching_ports = sum(
            1
            for entry in port_entries
            if entry.get("name") == port_name
            and entry.get("port") == str(port)
        )
        if matching_ports == 1:
            matching_services += 1
        elif matching_ports > 1:
            duplicate_ports = True
    return matching_services, duplicate_ports


def service_routes_in_namespace(
    text: str,
    *,
    namespace: str,
    port_name: str,
    port: int,
) -> tuple[int, int, bool]:
    service_count = 0
    matching_services = 0
    duplicate_ports = False
    for document in split_yaml_documents(text):
        if yaml_scalar(document, "kind", indent=0) != "Service":
            continue
        metadata_result = yaml_section(document, "metadata", indent=0)
        spec_result = yaml_section(document, "spec", indent=0)
        if not metadata_result or not spec_result:
            continue
        metadata, metadata_indent = metadata_result
        metadata_child_indent = direct_child_indent(metadata, metadata_indent)
        if metadata_child_indent is None:
            continue
        if (
            yaml_scalar(metadata, "namespace", indent=metadata_child_indent)
            != namespace
        ):
            continue
        service_count += 1
        spec, spec_indent = spec_result
        spec_child_indent = direct_child_indent(spec, spec_indent)
        if spec_child_indent is None:
            continue
        ports_result = yaml_section(spec, "ports", indent=spec_child_indent)
        if not ports_result:
            continue
        ports, _ports_indent = ports_result
        port_entries: list[dict[str, str]] = []
        current: dict[str, str] | None = None
        current_indent: int | None = None
        for line in ports.splitlines():
            entry = yaml_mapping_entry(line)
            if not entry:
                continue
            logical_indent, sequence_item, key, value = entry
            if sequence_item:
                if current is not None:
                    port_entries.append(current)
                current = {}
                current_indent = logical_indent
            if (
                current is not None
                and current_indent == logical_indent
                and key
            ):
                current[key] = value.strip("\"'")
        if current is not None:
            port_entries.append(current)
        matching_ports = sum(
            1
            for entry in port_entries
            if entry.get("name") == port_name
            and entry.get("port") == str(port)
        )
        if matching_ports == 1:
            matching_services += 1
        elif matching_ports > 1:
            duplicate_ports = True
    return service_count, matching_services, duplicate_ports


def rendered_secret_references(text: str) -> list[tuple[str | None, str | None]]:
    references: list[tuple[str | None, str | None]] = []
    for document in split_yaml_documents(text):
        lines = document.splitlines()
        for index, line in enumerate(lines):
            entry = yaml_mapping_entry(line)
            if not entry or entry[1] or entry[2] != "secretKeyRef" or entry[3]:
                continue
            parent_indent = entry[0]
            body: list[str] = []
            for child in lines[index + 1 :]:
                if not child.strip() or child.lstrip().startswith("#"):
                    body.append(child)
                    continue
                child_indent = len(child) - len(child.lstrip(" "))
                if child_indent <= parent_indent:
                    break
                body.append(child)
            section_text = "\n".join(body)
            child_indent = direct_child_indent(section_text, parent_indent)
            references.append(
                (
                    (
                        yaml_scalar(section_text, "name", indent=child_indent)
                        if child_indent is not None
                        else None
                    ),
                    (
                        yaml_scalar(section_text, "key", indent=child_indent)
                        if child_indent is not None
                        else None
                    ),
                )
            )
    return references


def read(path: Path, errors: list[str]) -> str:
    if path.is_symlink():
        errors.append(f"managed file must not be a symlink: {path}")
        return ""
    if not path.is_file():
        errors.append(f"missing required file: {path}")
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(f"cannot read {path}: {exc}")
        return ""


def validate_rendered_resources(
    rendered: str,
    *,
    namespace: str,
    secret_name: str | None,
) -> list[str]:
    errors: list[str] = []
    identities: set[tuple[str, str, str]] = set()
    documents = split_yaml_documents(rendered)
    if not documents:
        return [f"{RENDERED_PATH} has no Kubernetes resources"]
    for index, document in enumerate(documents, start=1):
        api_version = yaml_scalar(document, "apiVersion", indent=0)
        kind = yaml_scalar(document, "kind", indent=0)
        metadata_result = yaml_section(document, "metadata", indent=0)
        if not api_version or not kind or not metadata_result:
            errors.append(
                f"{RENDERED_PATH} document {index} must have one apiVersion, "
                "kind, and metadata mapping"
            )
            continue
        metadata, metadata_indent = metadata_result
        child_indent = direct_child_indent(metadata, metadata_indent)
        if child_indent is None:
            errors.append(
                f"{RENDERED_PATH} document {index} has empty metadata"
            )
            continue
        name = yaml_scalar(metadata, "name", indent=child_indent)
        resource_namespace = yaml_scalar(
            metadata, "namespace", indent=child_indent
        )
        if not name:
            errors.append(
                f"{RENDERED_PATH} document {index} has an invalid resource name"
            )
            continue
        if kind == "Service" and not DNS_LABEL.fullmatch(name):
            errors.append(
                f"{RENDERED_PATH} Service {name!r} is not a valid DNS label"
            )
            continue
        if not DNS_SUBDOMAIN.fullmatch(name):
            errors.append(
                f"{RENDERED_PATH} document {index} has an invalid resource name"
            )
            continue
        if resource_namespace and not DNS_LABEL.fullmatch(resource_namespace):
            errors.append(
                f"{RENDERED_PATH} document {index} has an invalid namespace"
            )
        identity = (kind, resource_namespace or "", name)
        if identity in identities:
            errors.append(
                f"{RENDERED_PATH} has duplicate resource identity: "
                f"{kind} {resource_namespace or '<cluster>'}/{name}"
            )
        identities.add(identity)
        if kind == "Service" and resource_namespace != namespace:
            errors.append(
                f"{COLLECTOR_MANIFEST_PATH} Service {name!r} is not in namespace "
                f"{namespace!r}"
            )

    token_key = "splunk_observability_access_token"
    references = rendered_secret_references(rendered)
    matching_secret_references = [
        (name, key)
        for name, key in references
        if name == secret_name and key == token_key
    ]
    token_references = [
        (name, key) for name, key in references if key == token_key
    ]
    if secret_name and not matching_secret_references:
        errors.append(
            f"{COLLECTOR_MANIFEST_PATH} has no Collector Secret reference to "
            f"{secret_name!r}/{token_key}"
        )
    for name, _ in token_references:
        if name != secret_name:
            errors.append(
                f"{COLLECTOR_MANIFEST_PATH} Collector Secret reference name differs "
                f"from helm/values.yaml: {name!r}"
            )
    service_count, grpc_routes, duplicate_grpc_routes = service_routes_in_namespace(
        rendered,
        namespace=namespace,
        port_name="otlp",
        port=4317,
    )
    _service_count, http_routes, duplicate_http_routes = service_routes_in_namespace(
        rendered,
        namespace=namespace,
        port_name="otlp-http",
        port=4318,
    )
    if service_count != 1:
        errors.append(
            f"{COLLECTOR_MANIFEST_PATH} must contain exactly one Service "
            f"in namespace {namespace!r}"
        )
    if grpc_routes != 1 or duplicate_grpc_routes:
        errors.append(
            f"{COLLECTOR_MANIFEST_PATH} must contain exactly one generated "
            "OTLP/gRPC Service route: port 'otlp'=4317"
        )
    if http_routes != 1 or duplicate_http_routes:
        errors.append(
            f"{COLLECTOR_MANIFEST_PATH} must contain exactly one generated "
            "OTLP/HTTP Service route: port 'otlp-http'=4318"
        )
    return errors


def validate(bundle: Path, *, include_rendered: bool = True) -> list[str]:
    errors: list[str] = []
    if bundle.is_symlink():
        return [f"configuration directory must not be a symlink: {bundle}"]
    if not bundle.is_dir():
        return [f"configuration directory does not exist: {bundle}"]

    contents: dict[str, str] = {}
    for relative in REQUIRED_FILES:
        contents[relative] = read(bundle / relative, errors)
    for relative in (LEGACY_RENDERED_PATH, PROVENANCE_PATH):
        if (bundle / relative).exists():
            errors.append(
                f"{relative} is no longer generated; rerun with --overwrite"
            )
    errors.extend(unexpected_helm_render_inputs(bundle))

    for path in sorted(bundle.rglob("*")):
        if path.is_symlink():
            relative = path.relative_to(bundle).as_posix()
            errors.append(f"configuration contains a symlink: {relative}")
            continue
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        relative = path.relative_to(bundle).as_posix()
        if relative in {LEGACY_RENDERED_PATH, PROVENANCE_PATH}:
            continue
        if relative not in contents:
            contents[relative] = read(path, errors)

    for relative, text in contents.items():
        if not text:
            continue
        if relative.endswith((".yaml", ".yml")) or relative == "helm/Chart.lock":
            errors.extend(duplicate_yaml_mapping_keys(relative, text))
        unresolved = sorted(set(UNRESOLVED.findall(text)))
        if unresolved:
            errors.append(
                f"{relative} has unresolved placeholders: {', '.join(unresolved)}"
            )
        if LEGACY_INGEST.search(text):
            errors.append(f"{relative} uses a legacy signalfx.com ingest domain")
        if relative not in EXAMPLE_SECRET_FILES:
            if re.search(r":\s*REPLACE_AT_DEPLOY_TIME\s*$", text, re.MULTILINE):
                errors.append(f"{relative} contains an example token value")
            if STRING_DATA.search(text):
                errors.append(f"{relative} contains inline Kubernetes secret data")
            if SECRET_TOKEN_MAPPING_KEY.search(text):
                errors.append(
                    f"{relative} contains the Collector access-token key "
                    "outside an approved example Secret"
                )
        if INLINE_ACCESS_TOKEN.search(text):
            errors.append(f"{relative} contains a non-empty inline accessToken")
        for header in re.findall(
            r"X-SF-Token[\"']?\s*:\s*[\"']?([^\n\"']+)",
            text,
            re.IGNORECASE,
        ):
            if "${" not in header:
                errors.append(f"{relative} contains a literal X-SF-Token value")
        for access_token in re.findall(
            r"^[ \t]*(?:[\"']?access_token[\"']?)[ \t]*:"
            r"[ \t]*[\"']?([^\n\"']+)",
            text,
            re.MULTILINE,
        ):
            if "${" not in access_token:
                errors.append(f"{relative} contains a literal access_token value")

    collector = contents.get("collector-config.yaml", "")
    collector_required = (
        "receivers:",
        "processors:",
        "exporters:",
        "service:",
        "extensions: [health_check]",
        "processors: [memory_limiter, batch]",
        "traces_endpoint: \"https://ingest.${env:SPLUNK_REALM}.observability.splunkcloud.com/v2/trace/otlp\"",
        "metrics_endpoint: \"https://ingest.${env:SPLUNK_REALM}.observability.splunkcloud.com/v2/datapoint/otlp\"",
        "X-SF-Token: \"${env:SPLUNK_ACCESS_TOKEN}\"",
    )
    for value in collector_required:
        if value not in collector:
            errors.append(f"collector-config.yaml missing required value: {value}")

    chart = contents.get("helm/Chart.yaml", "")
    chart_repository_match = CHART_REPOSITORY.search(chart)
    if (
        not chart_repository_match
        or chart_repository_match.group(1) != OFFICIAL_CHART_REPOSITORY
    ):
        errors.append("helm/Chart.yaml does not use the official chart repository")
    version_match = EXACT_CHART_VERSION.search(chart)
    if not version_match:
        errors.append("helm/Chart.yaml dependency version is not exact semver")
    elif "latest" in version_match.group(1).lower():
        errors.append("helm/Chart.yaml must not use latest")
    chart_lock = contents.get("helm/Chart.lock")
    if chart_lock:
        lock_match = EXACT_CHART_VERSION.search(chart_lock)
        lock_repository_match = CHART_REPOSITORY.search(chart_lock)
        if not lock_match:
            errors.append("helm/Chart.lock has no exact Splunk chart version")
        elif version_match and lock_match.group(1) != version_match.group(1):
            errors.append("helm/Chart.lock is stale; run helm dependency update")
        if (
            not lock_repository_match
            or lock_repository_match.group(1) != OFFICIAL_CHART_REPOSITORY
        ):
            errors.append(
                "helm/Chart.lock does not use the official chart repository"
            )

    values = contents.get("helm/values.yaml", "")
    realm = nested_yaml_scalar(
        values,
        ("collector", "splunkObservability", "realm"),
    )
    if not realm or not re.fullmatch(
        r"[a-z][a-z0-9-]{0,30}[a-z0-9]",
        realm,
    ):
        errors.append("helm/values.yaml has an invalid Collector realm")
    expected_values = {
        ("collector", "splunkObservability", "metricsEnabled"): "true",
        ("collector", "splunkObservability", "tracesEnabled"): "true",
        ("collector", "secret", "create"): "false",
        ("collector", "secret", "validateSecret"): "true",
        ("collector", "agent", "enabled"): "true",
    }
    for path, expected in expected_values.items():
        actual = nested_yaml_scalar(values, path)
        if actual != expected:
            errors.append(
                "helm/values.yaml requires "
                f"{'.'.join(path)}={expected}, found {actual!r}"
            )
    values_secret_name = nested_yaml_scalar(
        values,
        ("collector", "secret", "name"),
    )
    if not values_secret_name or not DNS_LABEL.fullmatch(values_secret_name):
        errors.append("helm/values.yaml has an invalid Collector Secret name")
    gateway_enabled = nested_yaml_scalar(
        values,
        ("collector", "gateway", "enabled"),
    )
    if gateway_enabled not in {"true", "false"}:
        errors.append("helm/values.yaml has an invalid collector.gateway.enabled")
    if EXISTING_SECRET.search(values):
        errors.append("helm/values.yaml uses unsupported existingSecret")
    passthrough = nested_yaml_scalar(
        values,
        ("collector", "gateway", "tokenPassthrough"),
    )
    passthrough_values = [
        match.group("value")
        for match in TOKEN_PASSTHROUGH.finditer(values)
    ]
    if len(passthrough_values) > 1:
        errors.append("helm/values.yaml has duplicate gateway tokenPassthrough")
    if (
        passthrough is not None and passthrough.lower() != "false"
    ) or any(value.lower() != "false" for value in passthrough_values):
        errors.append("helm/values.yaml enables gateway token passthrough")

    example_namespaces: set[str] = set()
    for relative in EXAMPLE_SECRET_FILES:
        secret = contents.get(relative, "")
        token_values = [
            match.group("value")
            for match in SECRET_TOKEN_KEY.finditer(secret)
        ]
        if len(token_values) != 1:
            errors.append(
                f"{relative} must contain exactly one access-token key"
            )
        elif token_values[0] != "REPLACE_AT_DEPLOY_TIME":
            errors.append(
                f"{relative} access-token key must use "
                "REPLACE_AT_DEPLOY_TIME"
            )
        if yaml_scalar(secret, "kind", indent=0) != "Secret":
            errors.append(f"{relative} is not a Kubernetes Secret")
            continue
        metadata_result = yaml_section(secret, "metadata", indent=0)
        if not metadata_result:
            errors.append(f"{relative} has no Secret metadata")
            continue
        metadata, metadata_indent = metadata_result
        child_indent = direct_child_indent(metadata, metadata_indent)
        secret_name = (
            yaml_scalar(metadata, "name", indent=child_indent)
            if child_indent is not None
            else None
        )
        secret_namespace = (
            yaml_scalar(metadata, "namespace", indent=child_indent)
            if child_indent is not None
            else None
        )
        if secret_name != values_secret_name:
            errors.append(
                f"{relative} Secret name differs from helm/values.yaml"
            )
        if not secret_namespace or not DNS_LABEL.fullmatch(secret_namespace):
            errors.append(f"{relative} has an invalid Secret namespace")
        else:
            example_namespaces.add(secret_namespace)
    if len(example_namespaces) > 1:
        errors.append("Collector Secret examples use different namespaces")

    manifest = contents.get(COLLECTOR_MANIFEST_PATH, "")
    if not manifest.strip():
        errors.append(f"{COLLECTOR_MANIFEST_PATH} is empty")
    if "apiVersion:" not in manifest or "kind:" not in manifest:
        errors.append(f"{COLLECTOR_MANIFEST_PATH} has no Kubernetes resources")
    if "REPLACE_AT_DEPLOY_TIME" in manifest:
        errors.append(f"{COLLECTOR_MANIFEST_PATH} contains a token placeholder")
    if "helm.sh/hook" in manifest:
        errors.append(f"{COLLECTOR_MANIFEST_PATH} contains Helm hooks")
    namespace = next(iter(example_namespaces)) if len(example_namespaces) == 1 else None
    secret_name = nested_yaml_scalar(
        values,
        ("collector", "secret", "name"),
    )
    if isinstance(namespace, str):
        errors.extend(
            validate_rendered_resources(
                manifest,
                namespace=namespace,
                secret_name=secret_name,
            )
        )

    return errors


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config_dir", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    errors = validate(args.config_dir)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    manifest = args.config_dir / COLLECTOR_MANIFEST_PATH
    suffix = " including generated Kubernetes YAML" if manifest.exists() else ""
    print(f"Validated Collector configuration{suffix}: {args.config_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
