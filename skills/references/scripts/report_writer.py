#!/usr/bin/env python3
"""Publish canonical OTel reports from structured inputs, without model-authored views."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys


def load_engine():
    path = Path(__file__).with_name("observe_report.py")
    spec = importlib.util.spec_from_file_location("observe_report", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ENGINE = load_engine()
MAX_REPORT_FILE_BYTES = 4 * 1024 * 1024
NAMES = {
    "audit": "otel-audit.json",
    "instrumentation": "otel-instrumentation.json",
    "verification": "otel-verify.json",
}
LABELS = {
    "working": "Working",
    "not_working": "Not working",
    "not_proven": "Not proven",
    "not_configured": "Not configured",
    "blocked": "Not proven",
    "deferred": "Deferred",
}


def cell(value):
    if isinstance(value, list):
        value = "; ".join(str(v) for v in value)
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("|", r"\|")
        .replace("\r", "&#13;")
        .replace("\n", "&#10;")
    )


def table(headers, rows):
    return (
        "\n".join(
            [
                "| " + " | ".join(headers) + " |",
                "| " + " | ".join("---" for _ in headers) + " |",
            ]
            + ["| " + " | ".join(cell(v) for v in row) + " |" for row in rows]
        )
        + "\n"
    )


def audit_html(audit, selection, root, directory):
    document = ENGINE.render_html(audit, selection, root, directory)
    marker = f"<span><b>{len(audit['findings'])}</b> findings</span>"
    if document.count(marker) != 1:
        raise ValueError("Audit report summary marker is unavailable")
    ownership = "Yes" if audit["meta"]["genai_ownership_detected"] else "No"
    return document.replace(
        marker,
        f"<span>GenAI ownership detected: <b>{ownership}</b></span>\n      " + marker,
        1,
    )


def bullets(values, empty="None."):
    return "\n".join("- " + cell(v) for v in values) if values else empty


def detail(value):
    # Retain supplied nested evidence and receipts; never infer missing proof.
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    fence = "`" * max(
        3, max((len(m[0]) + 1 for m in re.finditer(r"`+", text)), default=3)
    )
    return fence + "json\n" + text + "\n" + fence


def reader_proof(value):
    if isinstance(value, dict):
        return {
            k: (
                f"{len(v)} generated trace(s)"
                if k in {"trace_ids", "span_ids"} and isinstance(v, list)
                else reader_proof(v)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [reader_proof(v) for v in value]
    return value


def extra_sections(details):
    sections = []
    tables = {
        "genaiClosure": (
            "## GenAI Readiness Closure",
            [
                "Surface",
                "Required signals",
                "Implemented / proven",
                "Tests",
                "Remaining signals",
                "Result",
            ],
        ),
        "validationGates": (
            "## Validation Gates",
            ["Gate", "Command / check", "Result / evidence"],
        ),
        "runtimeDependencies": (
            "## Runtime Dependency Resolution",
            [
                "Runtime",
                "Configuration source",
                "Resolved dependencies",
                "Command",
                "Result / evidence",
            ],
        ),
    }
    for key, (heading, headers) in tables.items():
        if key in details:
            sections.extend([heading, table(headers, details[key])])
    sections.extend(
        [
            "## Verification Handoff / Results",
            bullets(
                details.get("verificationHandoff", []),
                "See the bound scenario, command, proof-mode and evidence inventory in Proof.",
            ),
            "## Detector Handoff / Results",
            bullets(
                details.get("detectorHandoff", []),
                "Not requested; report publication does not create cloud resources.",
            ),
        ]
    )
    return sections


def validate_details(details, audit):
    if not isinstance(details, dict) or set(details) - {
        "summary",
        "incidentRoles",
        "genaiClosure",
        "validationGates",
        "runtimeDependencies",
        "verificationHandoff",
        "detectorHandoff",
        "remainingGaps",
        "supplementalEvidence",
    }:
        raise ValueError("Invalid structured report details")
    widths = {
        "incidentRoles": 6,
        "genaiClosure": 6,
        "validationGates": 3,
        "runtimeDependencies": 5,
    }
    for key, values in details.items():
        if not isinstance(values, list) or len(values) > 256:
            raise ValueError("Report details must contain bounded lists")
        if key in widths:
            if any(
                not isinstance(row, list)
                or len(row) != widths[key]
                or any(not isinstance(v, str) or not v.strip() for v in row)
                for row in values
            ):
                raise ValueError("Invalid table rows: " + key)
        elif any(not isinstance(v, str) or not v.strip() for v in values):
            raise ValueError("Report details must contain nonempty strings")
    for row in details.get("incidentRoles", []):
        if row[2] not in {
            "MTTD-improving",
            "localization-only",
            "provider/platform-owned",
            "uncovered",
        }:
            raise ValueError("Invalid incident signal role")
    for row in details.get("genaiClosure", []):
        if row[5] not in {
            "Working",
            "Partial",
            "Not working",
            "Not proven",
            "Not configured",
            "Deferred",
            "Owner-mapped",
        }:
            raise ValueError("Invalid GenAI closure result")


def instrumentation_markdown(audit, selection, implementation, verification, details):
    by_id = {f["id"]: f for f in audit["findings"]}
    proofs = {f["id"]: f for f in (verification or {}).get("findings", [])}
    result = ENGINE.aggregate_instrumentation_result(implementation, verification)
    service = implementation["meta"]["service_name"]
    rows = []
    signals = []
    for finding in implementation["findings"]:
        proof = proofs.get(finding["id"], finding)
        rows.append(
            [
                finding["id"] + " — " + by_id[finding["id"]]["title"],
                finding["changes"],
                finding["tests"],
                LABELS[proof["status"]],
                finding["evidence"],
            ]
        )
        for item in finding["telemetry_changes"]:
            signals.append(
                [
                    item["type"],
                    item["name"] if item["change_kind"] == "added" else "None",
                    item["name"] if item["change_kind"] == "modified" else "None",
                    item["name"] if item["change_kind"] == "removed" else "None",
                    item["product_view"],
                    finding["evidence"],
                    LABELS[proof["status"]],
                ]
            )
    body = [
        f"# OTel Instrumentation Report: {cell(service)}",
        f"**Result:** {result}",
        "**Source audit:** `.observe/otel-audit.json`\n\n**Selected scope:** `.observe/otel-selection.json`\n\n**Verification report:** "
        + ("`.observe/otel-verify.md`" if verification else "Not run")
        + "\n\n**Detector report:** not requested",
        "## Executive Summary",
        bullets(
            [
                f"Selected findings: {len(selection['approved_ids'])}.",
                f"Implementation result: {implementation['meta']['result']}.",
                f"Verification result: {verification['meta']['result'] if verification else 'Not run; implementation is not runtime proof'}.",
            ]
        ),
        "## Flow",
        "audit → select → instrument → verify",
        "## Files Changed",
        bullets(
            [
                item["source"] + ": " + item["change"]
                for f in implementation["findings"]
                for item in f["telemetry_changes"]
            ]
        ),
        "## Signals Changed",
        table(
            [
                "Signal type",
                "Added",
                "Modified",
                "Removed",
                "Product result / next product action",
                "Evidence",
                "Verification status",
            ],
            signals,
        ),
        "## Audit Gap Closure",
        table(
            ["Finding", "What changed", "Tested", "Result", "Evidence / reason"], rows
        ),
        "## Proof",
        detail(
            {
                "audit_sha256": implementation["audit_sha256"],
                "selection_sha256": implementation["selection_sha256"],
                "implementation": implementation,
                "verification": reader_proof(verification),
            }
        ),
        "## Next Steps",
        bullets(implementation["next_steps"]),
    ]
    body[body.index("## Audit Gap Closure") : body.index("## Audit Gap Closure")] = [
        "### Consumer compatibility",
        detail(
            [
                item["consumer_compatibility"]
                for f in implementation["findings"]
                for item in f["telemetry_changes"]
                if "consumer_compatibility" in item
            ]
        ),
    ]
    if "incidentRoles" in details:
        index = body.index("## Audit Gap Closure")
        body[index:index] = [
            "### Incident Readiness Signal Roles",
            table(
                [
                    "Surface",
                    "Exact signal",
                    "Role",
                    "Detector use / reason",
                    "Proof",
                    "Remaining owner / prerequisite",
                ],
                details["incidentRoles"],
            ),
        ]
    index = body.index("## Proof")
    body[index:index] = extra_sections(details) + [
        "## Remaining Gaps",
        bullets(
            details.get("remainingGaps", []),
            "See the bound finding and item states below; absence of a separate narrative is not proof of completeness.",
        ),
    ]
    if details.get("summary"):
        body[body.index("## Executive Summary") + 1] = bullets(details["summary"])
    if details.get("supplementalEvidence"):
        body += ["## Supplemental Evidence", bullets(details["supplementalEvidence"])]
    return "\n\n".join(body) + "\n"


def tested_projection(proof):
    return (
        "proof_mode="
        + proof["proof_mode"]
        + "; scenarios="
        + (", ".join(proof["scenarios"]) or "none")
    )


def product_projection(proof):
    return "; ".join(
        [*proof.get("product_validation", []), "visibility=" + proof["visibility"]]
    )


def verification_markdown(implementation, verification, details):
    source = {
        i["id"]: i for f in implementation["findings"] for i in f["telemetry_changes"]
    }
    proofs = [i for f in verification["findings"] for i in f["item_results"]]
    rows = [
        [
            p["id"],
            source[p["id"]]["name"],
            source[p["id"]]["type"],
            source[p["id"]]["change"],
            LABELS[p["status"]],
            tested_projection(p),
            product_projection(p),
            p["evidence"],
        ]
        for p in proofs
    ]
    gaps = [
        [
            p["id"],
            LABELS[p["status"]],
            p.get("observed_telemetry", []),
            p.get("evidence", []),
        ]
        for p in proofs
        if p["status"] != "working"
    ]
    working = sum(p["status"] == "working" for p in proofs)
    body = [
        f"# OTel Verification Report: {cell(verification['meta']['service_name'])}",
        f"**Result:** {verification['meta']['result']}",
        "**Proof boundary:** This report reconciles the supplied scenario and item evidence. Report publication does not execute application checks or independently establish application-wide coverage, correctness, explorer visibility or cloud delivery.",
        bullets(details.get("summary", []), ""),
        "## What Changed",
        bullets([i["id"] + ": " + i["change"] for i in source.values()]),
        "## Tested And Working",
        f"**Individual result:** {working}/{len(proofs)} working",
        table(
            [
                "Item ID",
                "OTel item",
                "Type",
                "Added or modified",
                "Working status",
                "How it was tested",
                "Product result / visibility",
                "Evidence",
            ],
            rows,
        ),
    ]
    if not proofs:
        body.append(
            "No telemetry items. Selected findings are proof-first verification scope."
        )
        body.append(
            "The 0/0 item count does not establish application-wide coverage. Inspect the finding/scenario proof and remaining prerequisites below."
        )
    body += [
        "## Not Working Or Not Proven",
        (
            table(["Item ID", "State", "Observation", "Evidence"], gaps)
            if gaps
            else "None among the declared item results. This does not close separate evidence limitations or optional correctness prerequisites."
        ),
        bullets(
            [
                f["id"] + ": " + r
                for f in verification["findings"]
                for r in f.get("remaining", [])
            ]
            + details.get("remainingGaps", []),
            "",
        ),
    ]
    body += extra_sections(details)
    if details.get("supplementalEvidence"):
        body += ["## Supplemental Evidence", bullets(details["supplementalEvidence"])]
    body += [
        "## Proof",
        detail(reader_proof(verification)),
        "## Next Steps",
        bullets(verification["next_steps"]),
    ]
    return "\n\n".join(body) + "\n"


def snapshot(directory, name):
    path = directory / name
    if (
        path.exists()
        and ENGINE.path_is_link_or_reparse(path.lstat())
        or path.is_symlink()
    ):
        raise ValueError("Report paths must not be symbolic links")
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0),
        )
    except FileNotFoundError:
        return None
    with os.fdopen(descriptor, "rb") as source:
        status = os.fstat(source.fileno())
        current = path.lstat()
        if ENGINE.path_is_link_or_reparse(current) or (
            status.st_dev,
            status.st_ino,
        ) != (current.st_dev, current.st_ino):
            raise ValueError("Report input changed while opening")
        if not stat.S_ISREG(status.st_mode) or status.st_size > MAX_REPORT_FILE_BYTES:
            raise ValueError("Invalid or oversized report file")
        value = source.read(MAX_REPORT_FILE_BYTES + 1)
        if len(value) > MAX_REPORT_FILE_BYTES:
            raise ValueError("Oversized report file")
        return value


@contextlib.contextmanager
def report_lock(directory):
    path = directory / ".report-writer.lock"
    descriptor = os.open(
        path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600
    )
    try:
        current = path.lstat()
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or ENGINE.path_is_link_or_reparse(current)
            or (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino)
        ):
            raise ValueError("Invalid report writer lock")
        if os.name == "nt":
            import msvcrt

            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)


def publish(request):
    if set(request) - {"kind", "repoRoot", "report", "serve", "details"}:
        raise ValueError("Unknown report writer argument")
    kind = request["kind"]
    root = Path(request["repoRoot"])
    if kind not in NAMES or not root.is_absolute() or not root.is_dir():
        raise ValueError(
            "A supported report kind and existing absolute repoRoot are required"
        )
    root = root.resolve()
    directory = root / ".observe"
    if (
        directory.is_symlink()
        or directory.exists()
        and ENGINE.path_is_link_or_reparse(directory.lstat())
    ):
        raise ValueError(".observe must not be a symbolic link")
    directory.mkdir(mode=0o700, exist_ok=True)
    identity = directory.stat()
    with report_lock(directory):
        return publish_locked(
            request, kind, root, directory, (identity.st_dev, identity.st_ino)
        )


def publish_locked(request, kind, root, directory, directory_identity):
    names = [
        *NAMES.values(),
        "otel-selection.json",
        "otel.html",
        "otel-instrumentation.html",
        "otel-instrumentation.md",
        "otel-verify.md",
        "otel-instrumentation.details.json",
        "otel-verify.details.json",
    ]
    before = {name: snapshot(directory, name) for name in names}
    raw = request["report"]
    if not isinstance(raw, dict):
        raise ValueError("report must be a structured canonical JSON object")

    def existing(name):
        value = before[name]
        if value is None:
            raise ValueError("Missing prerequisite: .observe/" + name)
        return json.loads(value)

    audit_raw = raw if kind == "audit" else existing("otel-audit.json")
    errors = ENGINE.audit_finalization_preflight_errors(audit_raw)
    if errors:
        raise ValueError("; ".join(errors))
    audit = ENGINE.normalize_audit_report(audit_raw)
    details = request.get("details", {})
    validate_details(details, audit)
    outputs = {
        NAMES[kind]: json.dumps(raw, ensure_ascii=False, indent=2, allow_nan=False)
        + "\n"
    }
    report_result = audit["meta"]["status"]
    if kind == "audit":
        if before["otel-audit.json"] is not None:
            previous = ENGINE.normalize_audit_report(
                json.loads(before["otel-audit.json"])
            )
            if ENGINE.audit_digest(previous) != ENGINE.audit_digest(audit) and any(
                before[n] is not None
                for n in (
                    "otel-selection.json",
                    "otel-instrumentation.json",
                    "otel-verify.json",
                )
            ):
                raise ValueError(
                    "Audit changed while bound downstream reports exist; archive or explicitly resolve the previous flow first"
                )
        selection = (
            ENGINE.normalize_selection(existing("otel-selection.json"), audit)
            if before["otel-selection.json"] is not None
            else ENGINE.load_selection(None, audit, audit_raw)
        )
        outputs["otel.html"] = audit_html(audit, selection, root, directory)
    else:
        selection = ENGINE.normalize_selection(existing("otel-selection.json"), audit)
        implementation = ENGINE.normalize_instrumentation(
            raw if kind == "instrumentation" else existing("otel-instrumentation.json"),
            audit,
            selection,
        )
        if (
            kind == "verification"
            and before["otel-instrumentation.details.json"] is not None
        ):
            prior = existing("otel-instrumentation.details.json")
            if prior.get("instrumentation_sha256") != ENGINE.instrumentation_digest(
                implementation
            ):
                raise ValueError(
                    "Saved reader details do not match the current instrumentation"
                )
            details = {**prior["details"], **details}
            validate_details(details, audit)
        if audit["meta"]["genai_ownership_detected"] and not details.get(
            "genaiClosure"
        ):
            raise ValueError(
                "GenAI ownership requires structured details.genaiClosure rows; preserve the source-scoped closure"
            )
        if audit.get("current_instrumentation", {}).get(
            "incident_readiness"
        ) and not details.get("incidentRoles"):
            raise ValueError(
                "Incident readiness requires structured details.incidentRoles rows"
            )
        verification = None
        if kind == "verification":
            verification = ENGINE.normalize_verify(
                raw, audit, selection, implementation
            )
            outputs["otel-verify.md"] = verification_markdown(
                implementation, verification, details
            )
        elif before["otel-verify.json"] is not None:
            # A stale verification must never be silently rendered against changed code.
            verification = ENGINE.normalize_verify(
                existing("otel-verify.json"), audit, selection, implementation
            )
        if ENGINE.aggregate_instrumentation_result(
            implementation, verification
        ) == "Pass" and any(
            row[5] in {"Partial", "Not working", "Not proven", "Not configured"}
            for row in details.get("genaiClosure", [])
        ):
            raise ValueError(
                "Pass contradicts unproven GenAI closure; reconcile the canonical result"
            )
        outputs["otel-instrumentation.md"] = instrumentation_markdown(
            audit, selection, implementation, verification, details
        )
        detail_name = (
            "otel-instrumentation.details.json"
            if kind == "instrumentation"
            else "otel-verify.details.json"
        )
        outputs[detail_name] = (
            json.dumps(
                {
                    "schema_version": 1,
                    "instrumentation_sha256": ENGINE.instrumentation_digest(
                        implementation
                    ),
                    "details": details,
                },
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            + "\n"
        )
        outputs["otel-instrumentation.html"] = ENGINE.render_instrumentation_html(
            audit, selection, implementation, verification, root, directory
        )
        if before["otel.html"] is None:
            outputs["otel.html"] = audit_html(audit, selection, root, directory)
        report_result = (
            verification["meta"]["result"]
            if verification
            else ENGINE.aggregate_instrumentation_result(implementation, None)
        )
    for name in names:
        if snapshot(directory, name) != before[name]:
            raise ValueError(
                "Report inputs changed during rendering; retry with the current flow"
            )
    current = directory.stat()
    if directory.is_symlink() or (current.st_dev, current.st_ino) != directory_identity:
        raise ValueError("Report directory changed during rendering")
    changed = {
        name: value for name, value in outputs.items() if before[name] != value.encode()
    }
    if any(len(value.encode()) > MAX_REPORT_FILE_BYTES for value in outputs.values()):
        raise ValueError(
            "Generated report exceeds the 4 MiB artifact limit; narrow the report scope before publication"
        )
    # All data and views are validated/rendered before the first canonical mutation.
    # Individual replacements use the existing descriptor-safe atomic writer.
    written = []
    try:
        for name, value in changed.items():
            ENGINE.write_text(directory / name, value)
            written.append(name)
    except OSError as exc:
        raise ValueError(
            "Report publication interrupted after "
            + ", ".join(written)
            + "; inspect canonical artifacts before retrying"
        ) from exc
    files = {
        name: "sha256:" + hashlib.sha256(value.encode()).hexdigest()
        for name, value in outputs.items()
    }
    receipt = (
        "sha256:"
        + hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    )
    server = {"requested": bool(request.get("serve", True))}
    if server["requested"]:
        try:
            server.update(
                ENGINE.start_or_reuse_report_server(
                    directory,
                    "otel.html" if kind == "audit" else "otel-instrumentation.html",
                )
            )
        except (OSError, RuntimeError, SystemExit, ENGINE.ReportError) as exc:
            server.update({"available": False, "reason": str(exc)[:800]})
    links = {
        "machine_report": ENGINE.markdown_local_file_link(
            NAMES[kind], directory / NAMES[kind]
        ),
    }
    if kind != "audit":
        markdown_name = (
            "otel-instrumentation.md" if kind == "instrumentation" else "otel-verify.md"
        )
        links["technical_report"] = ENGINE.markdown_local_file_link(
            markdown_name, directory / markdown_name
        )
    for name, key in [
        ("otel.html", "review_report"),
        ("otel-instrumentation.html", "instrumentation_report"),
    ]:
        if name not in outputs and before[name] is None:
            continue
        if "url" in server:
            links[key] = ENGINE.markdown_web_link(
                name, server["url"].rsplit("/", 1)[0] + "/" + name
            )
        else:
            links[key] = ENGINE.markdown_local_file_link(name, directory / name)
    return {
        "validated": True,
        "kind": kind,
        "reportResult": report_result,
        "receipt": receipt,
        "reused": not changed,
        "files": {
            name: {"path": str(directory / name), "sha256": digest}
            for name, digest in files.items()
        },
        "server": server,
        "links": links,
        "scope": "Report validation and rendering; supplied findings and proof are not independently reproduced.",
    }


def main():
    try:
        data = sys.stdin.buffer.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise ValueError("Report request exceeds 2 MiB")
        request = json.loads(
            data,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError("Non-finite JSON value")
            ),
        )
        print(
            json.dumps(
                publish(request),
                ensure_ascii=True,
                allow_nan=False,
                separators=(",", ":"),
            )
        )
    except (ValueError, KeyError, TypeError, OSError, SystemExit) as exc:
        print(json.dumps({"error": str(exc)[:4000]}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
