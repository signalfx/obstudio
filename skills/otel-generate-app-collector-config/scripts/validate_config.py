#!/usr/bin/env python3
"""Validate that generated Collector and application configs agree."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from pathlib import Path

from validate_application import (
    integer_value,
    quoted_value,
    section,
    validate as validate_application,
)
from validate_collector import (
    RENDERED_PATH,
    direct_child_indent,
    duplicate_yaml_mapping_keys,
    matching_service_routes,
    validate as validate_collector,
    yaml_scalar,
    yaml_section,
)


def scalar_value(text: str, key: str) -> str | None:
    match = re.search(
        rf"^\s*{re.escape(key)}:\s*(?:\"([^\"\r\n]*)\"|'([^'\r\n]*)'|([^#\r\n]*?))\s*(?:#.*)?$",
        text,
        re.MULTILINE,
    )
    if not match:
        return None
    return next((value for value in match.groups() if value is not None), "").strip()


def secret_metadata(secret: str) -> tuple[str | None, str | None]:
    if yaml_scalar(secret, "kind", indent=0) != "Secret":
        return None, None
    metadata_result = yaml_section(secret, "metadata", indent=0)
    if not metadata_result:
        return None, None
    metadata, metadata_indent = metadata_result
    child_indent = direct_child_indent(metadata, metadata_indent)
    if child_indent is None:
        return None, None
    return (
        yaml_scalar(metadata, "name", indent=child_indent),
        yaml_scalar(metadata, "namespace", indent=child_indent),
    )


def env_value(manifest: str, name: str) -> str | None:
    values: list[str | None] = []
    name_pattern = re.escape(name)
    marker = re.compile(
        rf"^[ \t]*-[ \t]*name:[ \t]*(?:\"{name_pattern}\"|'{name_pattern}'|{name_pattern})[ \t]*(?:#.*)?$"
    )
    lines = manifest.splitlines()
    for index, line in enumerate(lines):
        if not marker.fullmatch(line):
            continue
        parent_indent = len(line) - len(line.lstrip(" "))
        body: list[str] = []
        for child in lines[index + 1 :]:
            if not child.strip() or child.lstrip().startswith("#"):
                body.append(child)
                continue
            child_indent = len(child) - len(child.lstrip(" "))
            if child_indent <= parent_indent:
                break
            body.append(child)
        values.append(scalar_value("\n".join(body), "value"))
    if len(values) != 1:
        return None
    return values[0]


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def resolve_workspace_root(
    application_bundle: Path,
    source: str | None,
    errors: list[str],
) -> Path | None:
    if not source:
        errors.append("application contract has no workspace root")
        return None
    source_path = Path(source)
    if source_path.is_absolute():
        errors.append("workspace root must be relative to the generated configuration")
        return None

    bundle = application_bundle.resolve()
    lexical = Path(os.path.abspath(bundle / source_path))
    if not is_within(bundle, lexical):
        errors.append("generated application configuration is outside its workspace root")
        return None
    try:
        resolved = lexical.resolve(strict=True)
    except OSError as exc:
        errors.append(f"cannot resolve workspace root: {exc}")
        return None
    if not resolved.is_dir() or not is_within(bundle, resolved):
        errors.append("workspace root must be a directory containing the configuration")
        return None
    return resolved


def resolve_application_root(
    application_bundle: Path,
    workspace: Path,
    source: str | None,
    errors: list[str],
) -> Path | None:
    if not source:
        errors.append("application contract has no application root")
        return None
    source_path = Path(source)
    if source_path.is_absolute():
        errors.append("application root must be relative to the generated configuration")
        return None

    bundle = application_bundle.resolve()
    lexical = Path(os.path.abspath(bundle / source_path))
    if not is_within(lexical, workspace):
        errors.append("application root escapes the workspace")
        return None
    if not is_within(bundle, lexical):
        errors.append("generated application configuration is outside its application root")
        return None

    cursor = lexical
    while True:
        if cursor.is_symlink():
            errors.append(f"application root contains a symlink: {cursor}")
            return None
        if cursor == workspace or cursor.parent == cursor:
            break
        cursor = cursor.parent
    try:
        resolved = lexical.resolve(strict=True)
    except OSError as exc:
        errors.append(f"cannot resolve application root: {exc}")
        return None
    if not resolved.is_dir() or not is_within(resolved, workspace):
        errors.append("application root must be a directory inside the workspace")
        return None
    if not is_within(bundle, resolved):
        errors.append("generated application configuration is outside its application root")
        return None
    return resolved


def resolve_local_evidence(
    app_root: Path,
    workspace: Path,
    source: str,
    errors: list[str],
) -> Path | None:
    source_path = Path(source)
    if source_path.is_absolute():
        errors.append("local Collector evidence source must be relative to the application")
        return None
    lexical = Path(os.path.abspath(app_root / source_path))
    if not is_within(lexical, workspace):
        errors.append("local Collector evidence source escapes the workspace")
        return None
    cursor = lexical
    while True:
        if cursor.is_symlink():
            errors.append(
                f"local Collector evidence source contains a symlink: {cursor}"
            )
            return None
        if cursor == workspace or cursor.parent == cursor:
            break
        cursor = cursor.parent
    try:
        resolved = lexical.resolve(strict=True)
    except OSError as exc:
        errors.append(f"cannot resolve local Collector evidence: {exc}")
        return None
    if not resolved.is_file() or not is_within(resolved, workspace):
        errors.append("local Collector evidence must be a file inside the workspace")
        return None
    return resolved


def validate(
    collector_bundle: Path,
    application_bundle: Path,
) -> list[str]:
    rendered = collector_bundle / RENDERED_PATH
    errors = [
        *(
            f"Collector: {error}"
            for error in validate_collector(
                collector_bundle,
            )
        ),
        *(f"Application: {error}" for error in validate_application(application_bundle)),
    ]
    contract_path = application_bundle / "otel-connection.yaml"
    values_path = collector_bundle / "helm" / "values.yaml"
    secret_example_path = (
        collector_bundle / "kubernetes" / "splunk-secret.example.yaml"
    )
    helm_secret_example_path = (
        collector_bundle / "helm" / "examples" / "splunk-secret.yaml"
    )
    required_paths = [
        ("canonical generated Collector YAML", rendered),
        ("application connection contract", contract_path),
        ("Collector Helm values", values_path),
        ("Collector Secret example", secret_example_path),
        ("Collector Helm Secret example", helm_secret_example_path),
    ]
    missing_required = False
    for label, path in required_paths:
        if not path.is_file():
            errors.append(f"missing {label}: {path}")
            missing_required = True
    if missing_required:
        return errors

    try:
        contract = contract_path.read_text(encoding="utf-8")
        values = values_path.read_text(encoding="utf-8")
        rendered_text = rendered.read_text(encoding="utf-8")
        secret_example = secret_example_path.read_text(encoding="utf-8")
        helm_secret_example = helm_secret_example_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(f"cannot read coordinated configuration: {exc}")
        return errors

    collector_contract = section(contract, "collector")
    application_contract = section(contract, "application")
    secret_contract = section(collector_contract, "secretRef")
    verification = section(contract, "verification")
    otlp = section(contract, "otlp")
    chart_values = section(values, "collector")
    chart_o11y = section(chart_values, "splunkObservability")
    chart_secret = section(chart_values, "secret")
    chart_gateway = section(chart_values, "gateway")

    realm = quoted_value(section(contract, "splunkObservability"), "realm")
    manifest_realm = env_value(rendered_text, "SPLUNK_REALM")
    chart_realm = scalar_value(chart_o11y, "realm")
    if realm != manifest_realm or realm != chart_realm:
        errors.append("realm differs between Collector and application configuration")

    secret_name = quoted_value(secret_contract, "name")
    chart_secret_name = scalar_value(chart_secret, "name")
    if secret_name != chart_secret_name:
        errors.append("Secret name differs between Collector and application configuration")
    namespace = quoted_value(collector_contract, "namespace")
    secret_namespace = quoted_value(secret_contract, "namespace")
    if namespace != secret_namespace:
        errors.append("application contract Secret namespace differs from Collector namespace")

    example_secret_names: list[str | None] = []
    example_secret_namespaces: list[str | None] = []
    for current_secret_example in (
        secret_example,
        helm_secret_example,
    ):
        example_secret_name, example_namespace = secret_metadata(
            current_secret_example
        )
        example_secret_names.append(example_secret_name)
        example_secret_namespaces.append(example_namespace)

    if any(example != secret_name for example in example_secret_names):
        errors.append("Secret name differs between Collector and application configuration")
    if any(example != namespace for example in example_secret_namespaces):
        errors.append(
            "Collector namespace differs between generated Secret resources "
            "and application configuration"
        )

    topology = quoted_value(collector_contract, "topology")
    gateway_enabled = scalar_value(chart_gateway, "enabled")
    expected_gateway = "true" if topology == "gateway" else "false"
    if gateway_enabled != expected_gateway:
        errors.append("topology differs between Collector and application configuration")

    release = quoted_value(collector_contract, "release")
    service = quoted_value(collector_contract, "service")
    if not release:
        errors.append("application contract has no Collector release")
    if topology not in {"gateway", "agent-service"}:
        errors.append("application contract has invalid Collector topology")

    if quoted_value(verification, "serviceResolution") != "generated-collector-yaml":
        errors.append("application route is not bound to generated Collector YAML")
    evidence_source = quoted_value(verification, "source")
    evidence_hash = quoted_value(verification, "sha256")
    evidence_path: Path | None = None
    workspace_root = resolve_workspace_root(
        application_bundle,
        quoted_value(application_contract, "workspaceRoot"),
        errors,
    )
    app_root = (
        resolve_application_root(
            application_bundle,
            workspace_root,
            quoted_value(application_contract, "root"),
            errors,
        )
        if workspace_root is not None
        else None
    )
    if (
        evidence_source
        and app_root is not None
        and workspace_root is not None
    ):
        evidence_path = resolve_local_evidence(
            app_root,
            workspace_root,
            evidence_source,
            errors,
        )
        if (
            evidence_path is not None
            and evidence_path != rendered.resolve()
        ):
            errors.append(
                "application evidence source is not the canonical generated Collector YAML"
            )
    else:
        if not evidence_source:
            errors.append("application contract has no Collector evidence source")

    if evidence_path is not None:
        try:
            evidence_bytes = evidence_path.read_bytes()
            evidence_text = evidence_bytes.decode("utf-8")
        except (OSError, UnicodeError) as exc:
            errors.append(f"cannot read Collector evidence: {exc}")
        else:
            actual_hash = hashlib.sha256(evidence_bytes).hexdigest()
            if evidence_hash != actual_hash:
                errors.append(
                    "application evidence hash does not match Collector evidence"
                )
            evidence_label = (
                evidence_path.relative_to(workspace_root).as_posix()
                if workspace_root is not None
                and is_within(evidence_path, workspace_root)
                else evidence_path.name
            )
            errors.extend(duplicate_yaml_mapping_keys(evidence_label, evidence_text))
            protocol = quoted_value(otlp, "protocol")
            port = integer_value(otlp, "port")
            port_name = quoted_value(otlp, "portName")
            if (
                service
                and namespace
                and protocol in {"http/protobuf", "grpc"}
                and port is not None
                and port_name
            ):
                matching_services, duplicate_ports = matching_service_routes(
                    evidence_text,
                    service=service,
                    namespace=namespace,
                    port_name=port_name,
                    port=port,
                )
                if matching_services != 1 or duplicate_ports:
                    errors.append(
                        "Collector evidence must contain exactly one application "
                        f"route: Service {service!r} in namespace {namespace!r} "
                        f"with port {port_name!r}={port}"
                    )

    return errors


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collector", required=True, type=Path)
    parser.add_argument("--application", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    errors = validate(
        args.collector,
        args.application,
    )
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Validated coordinated Collector and application configuration.")
    print("No resources were deployed; live connectivity remains unverified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
