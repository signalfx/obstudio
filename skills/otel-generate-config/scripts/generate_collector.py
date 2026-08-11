#!/usr/bin/env python3
"""Generate a token-free Collector configuration from included templates."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


SUPPORTED_DISTRIBUTIONS = (
    "aks",
    "eks",
    "eks/auto-mode",
    "eks/fargate",
    "gke",
    "gke/autopilot",
    "openshift",
    "other",
)
DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
REALM = re.compile(r"^[a-z][a-z0-9-]{0,30}[a-z0-9]$")
SEMVER = re.compile(
    r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
UNRESOLVED = re.compile(r"@@[A-Z0-9_]+@@")
HELM_RELEASE_NAME_MAX_LENGTH = 47
SECRET_NAME_ERROR = "invalid Kubernetes Secret name"


def reject_token_argument(argv: list[str] | None) -> list[str]:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if any(
        argument == "--token" or argument.startswith("--token=")
        for argument in arguments
    ):
        raise ValueError(
            "--token is forbidden; pass only a Kubernetes Secret name"
        )
    for index, argument in enumerate(arguments):
        if argument in {"--secret-name", "--existing-secret"}:
            if (
                index + 1 >= len(arguments)
                or arguments[index + 1].startswith("--")
                or not DNS_LABEL.fullmatch(arguments[index + 1])
            ):
                raise ValueError(SECRET_NAME_ERROR)
        elif (
            argument.startswith("--secret-name=")
            or argument.startswith("--existing-secret=")
        ):
            if not DNS_LABEL.fullmatch(argument.partition("=")[2]):
                raise ValueError(SECRET_NAME_ERROR)
    return arguments


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    arguments = reject_token_argument(argv)
    parser = argparse.ArgumentParser(
        description=(
            "Generate token-free Collector Kubernetes YAML and Helm files "
            "without invoking Helm."
        )
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--realm", required=True)
    parser.add_argument("--cluster-name", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--namespace", default="observability")
    parser.add_argument("--release-name", default="splunk-otel")
    parser.add_argument("--secret-name", "--existing-secret", dest="secret_name")
    parser.add_argument(
        "--topology",
        choices=("gateway", "agent-service"),
        default="gateway",
    )
    parser.add_argument(
        "--distribution",
        choices=SUPPORTED_DISTRIBUTIONS,
        default="other",
    )
    parser.add_argument("--chart-version")
    parser.add_argument(
        "--collector-version",
        help="Alias for --chart-version.",
    )
    parser.add_argument(
        "--gateway",
        action="store_true",
        help=(
            "Enable the chart's centralized OTLP gateway in addition to "
            "agents. Kept for compatibility; --topology gateway is the "
            "default."
        ),
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help=(
            "Replace generator-managed files and remove stale generated "
            "render and Helm dependency artifacts."
        ),
    )
    parsed = parser.parse_args(arguments)
    if parsed.chart_version and parsed.collector_version:
        if parsed.chart_version != parsed.collector_version:
            parser.error("--chart-version and --collector-version must match")
    parsed.chart_version = parsed.chart_version or parsed.collector_version
    if not parsed.chart_version:
        parser.error("--chart-version is required")
    if parsed.gateway:
        parsed.topology = "gateway"
    parsed.gateway = parsed.topology == "gateway"
    return parsed


def validate_input(name: str, value: str, pattern: re.Pattern[str]) -> None:
    if not pattern.fullmatch(value):
        raise ValueError(f"invalid {name}: {value!r}")


def validate_secret_name(value: str) -> None:
    if not DNS_LABEL.fullmatch(value):
        raise ValueError(SECRET_NAME_ERROR)


def validate_text(name: str, value: str, max_length: int = 253) -> None:
    if not value or len(value) > max_length:
        raise ValueError(f"{name} must contain 1-{max_length} characters")
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"{name} contains a control character")


def cloud_provider(distribution: str) -> str:
    if distribution == "aks":
        return "azure"
    if distribution.startswith("eks"):
        return "aws"
    if distribution.startswith("gke"):
        return "gcp"
    return ""


def replacements(args: argparse.Namespace) -> dict[str, str]:
    secret_name = args.secret_name or f"{args.release_name}-secret"
    validate_input("realm", args.realm, REALM)
    validate_input("namespace", args.namespace, DNS_LABEL)
    validate_input("release name", args.release_name, DNS_LABEL)
    if len(args.release_name) > HELM_RELEASE_NAME_MAX_LENGTH:
        raise ValueError(
            "release name must not exceed "
            f"{HELM_RELEASE_NAME_MAX_LENGTH} characters"
        )
    validate_secret_name(secret_name)
    validate_input("chart version", args.chart_version, SEMVER)
    validate_text("cluster name", args.cluster_name)
    validate_text("environment", args.environment, max_length=128)

    distribution = "" if args.distribution == "other" else args.distribution
    chart_core = args.chart_version.split("-", 1)[0].split("+", 1)[0]
    chart_parts = tuple(int(part) for part in chart_core.split("."))
    token_passthrough = (
        "    tokenPassthrough: false"
        if args.gateway and chart_parts >= (0, 157, 0)
        else ""
    )
    gateway_description = (
        ", plus a centralized OTLP gateway"
        if args.gateway
        else ""
    )
    collector_service = (
        f"{args.release_name}-collector"
        if args.gateway
        else f"{args.release_name}-collector-agent"
    )
    collector_workload = collector_service
    collector_configmap = collector_workload
    for name, value in (
        ("collector Service", collector_service),
        ("collector workload", collector_workload),
        ("collector ConfigMap", collector_configmap),
    ):
        validate_input(name, value, DNS_LABEL)
    return {
        "@@CHART_VERSION@@": json.dumps(args.chart_version),
        "@@CHART_VERSION_RAW@@": args.chart_version,
        "@@COLLECTOR_VERSION_RAW@@": args.chart_version,
        "@@CLUSTER_NAME@@": json.dumps(args.cluster_name),
        "@@CLUSTER_NAME_RAW@@": args.cluster_name,
        "@@CLOUD_PROVIDER@@": json.dumps(cloud_provider(args.distribution)),
        "@@DISTRIBUTION@@": json.dumps(distribution),
        "@@ENVIRONMENT@@": json.dumps(args.environment),
        "@@ENVIRONMENT_RAW@@": args.environment,
        "@@GATEWAY_DESCRIPTION@@": gateway_description,
        "@@GATEWAY_ENABLED@@": "true" if args.gateway else "false",
        "@@GATEWAY_TOKEN_PASSTHROUGH@@": token_passthrough,
        "@@NAMESPACE_RAW@@": args.namespace,
        "@@COLLECTOR_CONFIGMAP_NAME_RAW@@": collector_configmap,
        "@@COLLECTOR_IMAGE@@": json.dumps(
            f"quay.io/signalfx/splunk-otel-collector:{args.chart_version}"
        ),
        "@@COLLECTOR_SERVICE_NAME_RAW@@": collector_service,
        "@@COLLECTOR_WORKLOAD_NAME_RAW@@": collector_workload,
        "@@REALM@@": json.dumps(args.realm),
        "@@REALM_RAW@@": args.realm,
        "@@RELEASE_NAME_RAW@@": args.release_name,
        "@@SECRET_NAME@@": json.dumps(secret_name),
        "@@SECRET_NAME_RAW@@": secret_name,
    }


def render(template: str, values: dict[str, str], source: Path) -> str:
    result = template
    for placeholder, value in values.items():
        result = result.replace(placeholder, value)
    unresolved = sorted(set(UNRESOLVED.findall(result)))
    if unresolved:
        raise ValueError(
            f"{source} contains unresolved placeholders: {', '.join(unresolved)}"
        )
    return result


def managed_templates() -> list[Path]:
    asset_root = Path(__file__).resolve().parent.parent / "assets" / "bundle"
    return sorted(path for path in asset_root.rglob("*.tmpl") if path.is_file())


def destination_for(template: Path) -> Path:
    asset_root = Path(__file__).resolve().parent.parent / "assets" / "bundle"
    relative = template.relative_to(asset_root)
    return relative.with_name(relative.name.removesuffix(".tmpl"))


def reject_symlink_components(path: Path) -> None:
    absolute = Path(os.path.abspath(path))
    for component in reversed((absolute, *absolute.parents)):
        if component.is_symlink():
            raise ValueError(
                f"output path contains a symlink component: {component}"
            )


def generate(args: argparse.Namespace) -> list[Path]:
    output = args.output
    reject_symlink_components(output)
    if output.is_symlink():
        raise ValueError(f"output directory must not be a symlink: {output}")
    if output.exists() and not output.is_dir():
        raise ValueError(f"output path is not a directory: {output}")

    templates = managed_templates()
    if not templates:
        raise ValueError("no configuration templates found")

    destinations = [output / destination_for(template) for template in templates]
    legacy_rendered_manifest = output / "kubernetes" / "helm-rendered.yaml"
    legacy_rendered_provenance = (
        output / "kubernetes" / "helm-rendered.provenance.json"
    )
    chart_lock = output / "helm" / "Chart.lock"
    charts_directory = output / "helm" / "charts"
    for destination in [
        *destinations,
        legacy_rendered_manifest,
        legacy_rendered_provenance,
        chart_lock,
        charts_directory,
    ]:
        cursor = destination
        while cursor != output:
            if cursor.is_symlink():
                raise ValueError(
                    f"managed output path must not be a symlink: {cursor}"
                )
            if (
                cursor != destination
                and cursor.exists()
                and not cursor.is_dir()
            ):
                raise ValueError(
                    f"managed output parent is not a directory: {cursor}"
                )
            cursor = cursor.parent
    for destination in destinations:
        if destination.exists() and not destination.is_file():
            raise ValueError(
                f"managed output is not a regular file: {destination}"
            )
    existing = [
        path
        for path in [
            *destinations,
        ]
        if path.exists()
    ]
    if existing and not args.overwrite:
        joined = ", ".join(str(path) for path in existing)
        raise ValueError(f"managed files already exist; use --overwrite: {joined}")

    values = replacements(args)
    rendered = [
        (
            destination,
            render(template.read_text(encoding="utf-8"), values, template),
        )
        for template, destination in zip(templates, destinations, strict=True)
    ]

    stale_files = [
        path
        for path in (
            legacy_rendered_manifest,
            legacy_rendered_provenance,
            chart_lock,
        )
        if path.exists()
    ]
    dependency_archives: list[Path] = []
    if charts_directory.exists():
        if not charts_directory.is_dir():
            raise ValueError(
                f"Helm charts path is not a directory: {charts_directory}"
            )
        dependency_archives = sorted(
            charts_directory.glob("splunk-otel-collector-*.tgz")
        )
    for stale_file in [*stale_files, *dependency_archives]:
        if stale_file.is_symlink() or not stale_file.is_file():
            raise ValueError(
                f"stale generated artifact is not a regular file: {stale_file}"
            )

    stale_artifacts = [*stale_files, *dependency_archives]
    if stale_artifacts and not args.overwrite:
        joined = ", ".join(str(path) for path in stale_artifacts)
        raise ValueError(
            "generated artifacts already exist; use --overwrite: "
            f"{joined}"
        )
    if args.overwrite:
        for stale_file in stale_artifacts:
            stale_file.unlink()
            print(
                "Removed stale generated artifact: "
                f"{stale_file}"
            )
        for stale_dir in (output / "helm" / "charts",):
            try:
                stale_dir.rmdir()
            except OSError:
                pass

    written: list[Path] = []
    for destination, text in rendered:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")
        written.append(destination)
    return written


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        written = generate(args)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"Generated {len(written)} files:")
    for path in written:
        print(path)
    print("No access token was read or written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
