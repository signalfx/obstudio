"""Frozen, paired audit-skill challenge; opt-in model runs, no skill edits.

Run from the repository root with the eval venv Python. ``prepare`` freezes
inputs before any audited output; ``truth`` executes separate real-SDK probes.
``run`` and ``grade`` use an explicitly supplied authenticated Codex home.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tarfile
import time


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "evals/benchmarks/audit-accuracy"
BASELINE = "f56299311afa7c62c9896de1aa76d4ff5a22106f"
CANDIDATE = "e9162c27e07be461997fb3021f686db5875c7414"
CLI = "/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"
GO = "/Users/tithumma/.cache/tooling/obstudio-go-1.27.2/go/bin/go"
NODE_BIN = "/Users/tithumma/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin"
MODEL = "gpt-6.1-sol"
REPEATS = 2
SEED = 2640290


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def source_hashes(directory):
    return {str(p.relative_to(directory)): digest(p) for p in sorted(directory.rglob("*"))
            if p.is_file() and p.suffix in {".go", ".mod", ".sum", ".py", ".txt"}
            and not any(part.startswith(".") or part == "__pycache__" for part in p.relative_to(directory).parts)}


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def prepare(workspace):
    workspace.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    rng = random.Random(SEED)
    bundle_paths = {}
    for version, revision in [("baseline", BASELINE), ("candidate", CANDIDATE)]:
        target = workspace / "bundles" / f"{rng.getrandbits(64):016x}"
        target.mkdir(parents=True)
        data = subprocess.check_output(["git", "archive", revision, "skills"], cwd=ROOT)
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            archive.extractall(target, filter="data")
        bundle_paths[version] = target / "skills"
    jobs = []
    for case in manifest["cases"]:
        for repeat in range(REPEATS):
            for version in bundle_paths:
                opaque = f"r{rng.getrandbits(64):016x}"
                target = workspace / "runs" / opaque / "service"
                shutil.copytree(FIXTURES / case, target)
                (target / ".agents/skills").mkdir(parents=True)
                (target / ".agents/skills/otel-audit").symlink_to(bundle_paths[version] / "otel-audit")
                subprocess.run(["git", "init", "-q", str(target)], check=True)
                jobs.append(dict(id=opaque, case=case, repeat=repeat, version=version,
                                 source_hashes=source_hashes(target)))
    rng.shuffle(jobs)
    protocol = {
        "schema_version": 1, "frozen_utc": now(), "baseline_revision": BASELINE,
        "candidate_revision": CANDIDATE, "prompt": "$otel-audit", "model": MODEL,
        "reasoning_effort": "xhigh", "runs_per_version_per_app": REPEATS,
        "seed": SEED, "timeout_seconds": 1500,
        "cases": {name: dict(value, source_hashes=source_hashes(FIXTURES / name))
                  for name, value in manifest["cases"].items()},
        "grading": {
            "primary": "Mean of per-application closed-set F1, averaging repeats within each application. Both actual and predicted empty sets score 1; actual empty with any false prediction scores 0.",
            "primary_excluded_units": ["environment-resource"],
            "exclusion_reason": "The SDK environment-resource behavior was already examined in the earlier post-hoc probe. It remains a diagnostic control and is excluded from the primary score to avoid presenting a known mechanism as new holdout evidence.",
            "secondary": "Micro precision/recall and per-unit mistakes. All finding IDs receive supported/contradicted/unresolved factual-premise review; recommendations are not defects solely for being optional.",
            "blinding": "Two fresh grading sessions per paired report set, randomized opaque report IDs/order; version labels and skill source are withheld. Model grading, not independent human review.",
            "agreement": "Only unanimous unit predictions and factual finding verdicts are accepted; disagreement is unresolved. Any unresolved unit blocks a superiority claim; unknown finding premises remain visible and conservatively count as not established supported.",
            "acceptance": "Candidate macro-F1 gain at least 0.05, paired application-cluster bootstrap 95% percentile interval lower bound above 0, and factual finding support rate no more than 0.02 below baseline. No post-output skill changes or case removal.",
            "bootstrap": {"replicates": 20000, "seed": SEED, "cluster": "application; repeat scores averaged before resampling"},
            "limits": "Six newly authored synthetic applications, two languages, two repetitions. Exploratory evidence for these patterns, not proof for arbitrary production applications. Cases are not used to tune either frozen skill version.",
        },
        "probes": source_hashes(FIXTURES / "probes"),
        "execution_harness_sha256": digest(Path(__file__)),
    }
    write_json(workspace / "protocol.json", protocol)
    write_json(workspace / "jobs.json", jobs)
    print(f"Frozen {len(jobs)} runs; protocol SHA256 {digest(workspace / 'protocol.json')}", flush=True)


def truth(workspace):
    protocol = json.loads((workspace / "protocol.json").read_text())
    if source_hashes(FIXTURES / "probes") != protocol["probes"]:
        raise ValueError("Frozen truth probes changed")
    for case, metadata in protocol["cases"].items():
        target = workspace / "truth" / case
        shutil.copytree(FIXTURES / case, target)
        if source_hashes(target) != metadata["source_hashes"]:
            raise ValueError(f"Source changed: {case}")
        if metadata["language"] == "go":
            probe = (FIXTURES / "probes/go_probe.txt").read_text()
            if case == "order-api":
                call = 'handleOrder(context.Background(), tracer, propagation.MapCarrier{"traceparent":"00-11111111111111111111111111111111-2222222222222222-01"}, "order-A"); handleOrder(context.Background(), tracer, propagation.MapCarrier{}, "order-B")'
                check = '''if len(spans)!=4 { t.Fatal(len(spans)) }
                if spans[0].Name!="reserve.order-A" || spans[2].Name!="reserve.order-B" { t.Fatal("dynamic names absent") }
                if spans[0].Parent.IsValid() || spans[0].SpanContext.TraceID()==spans[1].SpanContext.TraceID() { t.Fatal("broken parentage not reproduced") }
                if spans[1].Parent.SpanID().String()!="2222222222222222" { t.Fatal("incoming propagation missing") }
                if spans[1].SpanKind!=trace.SpanKindServer { t.Fatal("server span absent") }'''
                probe = probe.replace(' "go.opentelemetry.io/otel/codes"\n', '')
            elif case == "feed-api":
                call = 'if readFeed(context.Background(), tracer, true)==nil { t.Fatal("expected application failure") }'
                check = '''if len(spans)!=2 { t.Fatal(len(spans)) }
                for _, s := range spans { if s.SpanKind!=trace.SpanKindServer || s.Status.Code!=codes.Unset || len(s.Events)!=0 { t.Fatal("duplicate/error contract differs") } }
                if spans[0].Parent.SpanID()!=spans[1].SpanContext.SpanID() { t.Fatal("duplicate relation missing") }'''
                probe = probe.replace(' "go.opentelemetry.io/otel/propagation"\n', '')
            else:
                call = '''reader := sdkmetric.NewManualReader(); meters := sdkmetric.NewMeterProvider(sdkmetric.WithReader(reader)); defer meters.Shutdown(context.Background())
                ctx, cancel := context.WithCancel(context.Background()); cancel()
                if err:=serve(ctx,tracer,meters);err!=nil{t.Fatal(err)}
                if settle(context.Background(),tracer,true)==nil{t.Fatal("expected application failure")}
                var data metricdata.ResourceMetrics; if err:=reader.Collect(context.Background(),&data);err!=nil{t.Fatal(err)}
                count:=0; for _, sm:=range data.ScopeMetrics { for _, m:=range sm.Metrics { if m.Name=="settlement.batches" { sum:=m.Data.(metricdata.Sum[int64]);for _,p:=range sum.DataPoints{value,ok:=p.Attributes.Value("outcome");if !ok||value.AsString()!="ok"||p.Attributes.Len()!=1{t.Fatal("unbounded metric")};count++} } } };if count!=1{t.Fatal("counter missing")}'''
                check = '''if len(spans)!=4{t.Fatal(len(spans))};for i:=0;i<4;i+=2{if spans[i].Name!="ledger.write"||spans[i+1].Name!="settle.batch"||spans[i].Parent.SpanID()!=spans[i+1].SpanContext.SpanID(){t.Fatal("healthy parentage broken")}}
                if spans[2].Status.Code!=codes.Error||spans[3].Status.Code!=codes.Error||len(spans[2].Events)==0{t.Fatal("error reporting absent")}'''
                probe = probe.replace(' "go.opentelemetry.io/otel/propagation"\n', '').replace(' "go.opentelemetry.io/otel/trace"\n', '')
                probe = probe.replace(' "testing"', ' "testing"\n sdkmetric "go.opentelemetry.io/otel/sdk/metric"\n "go.opentelemetry.io/otel/sdk/metric/metricdata"')
            (target / "proof_test.go").write_text(probe.replace("CASE_CALL", call).replace("CASE_ASSERT", check))
            command = [GO, "test", "-count=1", "-v", "./..."]
        else:
            command = [sys.executable, str(FIXTURES / "probes/python_probe.py"), case, str(target), str(target / "sdk-evidence.json")]
        result = subprocess.run(command, cwd=target, text=True, capture_output=True, timeout=180)
        (target / "probe.log").write_text(result.stdout + result.stderr)
        write_json(target / "result.json", dict(command=command, exit_code=result.returncode, source_hashes=metadata["source_hashes"], evidence_sha256=digest(target / "sdk-evidence.json") if (target / "sdk-evidence.json").exists() else None))
        print(case, result.returncode, flush=True)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)


def environment(codex_home):
    env = dict(os.environ, CODEX_HOME=str(codex_home), OBSTUDIO_SKILL_MCP_ENDPOINT="none", UV_NO_CONFIG="1")
    env["PATH"] = f"{Path(sys.executable).parent}:{Path(GO).parent}:{NODE_BIN}:/Users/tithumma/.local/bin:" + env["PATH"]
    return env


def invoke(directory, prompt, output, codex_home, schema=None, timeout=1500):
    command = [CLI, "exec", "--ignore-user-config", "--ephemeral", "--sandbox", "danger-full-access",
               "--config", 'otel.exporter="none"', "--config", 'otel.trace_exporter="none"',
               "--config", 'model_reasoning_effort="xhigh"', "--model", MODEL,
               "-C", str(directory), "--json", "-o", str(output)]
    if schema:
        command.extend(["--output-schema", str(schema)])
    command.append(prompt)
    started = now()
    start = time.monotonic()
    with output.with_suffix(".jsonl").open("w") as log, output.with_suffix(".stderr").open("w") as errors:
        try:
            result = subprocess.run(command, env=environment(codex_home), stdout=log, stderr=errors, timeout=timeout)
            status = {"exit_code": result.returncode}
        except subprocess.TimeoutExpired:
            status = {"timeout": True}
    return dict(status, started_utc=started, seconds=round(time.monotonic() - start, 3))


def run(workspace, codex_home, workers):
    jobs = json.loads((workspace / "jobs.json").read_text())
    def one(job):
        target = workspace / "runs" / job["id"]
        if (target / "result.json").exists():
            return
        if source_hashes(target / "service") != job["source_hashes"]:
            raise ValueError("Input source changed")
        status = invoke(target / "service", "$otel-audit", target / "final.md", codex_home)
        status["source_unchanged"] = source_hashes(target / "service") == job["source_hashes"]
        report = target / "service/.observe/otel-audit.json"
        status["report_sha256"] = digest(report) if report.exists() else None
        write_json(target / "result.json", status)
        print(job["id"], job["case"], job["version"], job["repeat"], status, flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, jobs))


def grade(workspace, codex_home, workers):
    jobs = json.loads((workspace / "jobs.json").read_text())
    protocol = json.loads((workspace / "protocol.json").read_text())
    tasks = []
    for case in protocol["cases"]:
        for repeat in range(REPEATS):
            pair = [j for j in jobs if j["case"] == case and j["repeat"] == repeat]
            if len(pair) != 2:
                raise ValueError("Each grading pair must contain both frozen versions")
            if any(not (workspace / "runs" / j["id"] / "result.json").exists() for j in pair):
                continue
            for judge in range(2):
                directory = workspace / "grading" / f"{case}-{repeat}-{judge}"
                if (directory / "result.json").exists():
                    continue
                directory.mkdir(parents=True, exist_ok=True)
                random.Random(SEED + judge + repeat).shuffle(pair)
                inputs = {"case": case, "source": {name: (FIXTURES / case / name).read_text() for name in protocol["cases"][case]["source_hashes"] if not name.endswith(".sum")},
                          "truth": protocol["cases"][case]["units"],
                          "sdk_evidence": json.loads((workspace / "truth" / case / "sdk-evidence.json").read_text()),
                          "reports": [{"id": j["id"], "report": json.loads((workspace / "runs" / j["id"] / "service/.observe/otel-audit.json").read_text())} for j in pair]}
                write_json(directory / "inputs.json", inputs)
                subprocess.run(["git", "init", "-q", str(directory)], check=True)
                tasks.append(directory)
    schema = {
        "type": "object", "additionalProperties": False, "required": ["reports"],
        "properties": {"reports": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["id", "units", "findings"],
            "properties": {"id": {"type": "string"}, "units": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["id", "reported_gap", "finding_ids", "reason"],
                "properties": {"id": {"type": "string"}, "reported_gap": {"type": "boolean"}, "finding_ids": {"type": "array", "items": {"type": "string"}}, "reason": {"type": "string"}}}},
                "findings": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                    "required": ["id", "verdict", "reason"], "properties": {"id": {"type": "string"}, "verdict": {"type": "string", "enum": ["supported", "contradicted", "unresolved"]}, "reason": {"type": "string"}}}}}
        }}}}
    schema_path = workspace / "grading-schema.json"
    write_json(schema_path, schema)
    prompt = """Independently grade the two anonymized audit reports in inputs.json against the supplied frozen source facts and real-SDK evidence. You are not auditing the application again and must not load any skill. Version labels are withheld. Return the requested JSON only.
For EVERY truth unit, reported_gap is true only if the report asserts that specific defect as an existing gap/anti-pattern; false if it says covered, says nothing, or merely recommends checking a possibility. A missing global provider is not a defect when an explicit SDK tracer/meter is used. A report that correctly says application-default service identity is absent does NOT claim OTEL_SERVICE_NAME is ignored. Distinguish runtime absence from static configuration. Include exact matching finding IDs, with a short cited quote/path and reason.
For EVERY entry in the report's findings array, judge its MATERIAL FACTUAL PREMISES: supported if source/probe establishes them, contradicted if a material premise is false, unresolved if not decidable from the available evidence. Judge the entire finding, not only its headline. Optional recommendations are acceptable if their factual premises are accurate; missing a metric/log is not itself a false claim. No invented requirements. Claims outside the frozen truth units still need a finding verdict. Do not score an audit's self-reported pass flag or workflow traces as correctness. Read local files only; do not change files or fetch remote sources."""
    def one(directory):
        status = invoke(directory, prompt, directory / "grade.json", codex_home, schema_path, timeout=900)
        status["harness_sha256"] = digest(Path(__file__))
        write_json(directory / "result.json", status)
        print("graded", directory.name, status, flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, tasks))


def confusion(units, predictions):
    if set(predictions) != {u["id"] for u in units} or any(type(v) is not bool for v in predictions.values()):
        raise ValueError("Missing, extra, or non-boolean unit predictions")
    result = dict(tp=0, fp=0, tn=0, fn=0)
    for unit in units:
        key = ("t" if unit["gap"] == predictions[unit["id"]] else "f") + ("p" if predictions[unit["id"]] else "n")
        result[key] += 1
    return result


def f1(counts):
    denominator = 2 * counts["tp"] + counts["fp"] + counts["fn"]
    return 2 * counts["tp"] / denominator if denominator else 1.0


def cluster_interval(differences, replicates=20000):
    if not differences:
        raise ValueError("No application pairs")
    rng = random.Random(SEED)
    values = sorted(sum(rng.choices(differences, k=len(differences))) / len(differences) for _ in range(replicates))
    return [values[int(0.025 * replicates)], values[int(0.975 * replicates)]]


def summarize(workspace):
    protocol = json.loads((workspace / "protocol.json").read_text())
    jobs = json.loads((workspace / "jobs.json").read_text())
    rows = []
    unresolved = []
    for job in jobs:
        run_dir = workspace / "runs" / job["id"]
        status = json.loads((run_dir / "result.json").read_text())
        if status.get("exit_code") != 0 or not status.get("source_unchanged"):
            raise ValueError(f"Incomplete/changed audit: {job['id']}")
        original = json.loads((run_dir / "service/.observe/otel-audit.json").read_text())
        finding_ids = {f["id"] for f in original["findings"]}
        grades = []
        for judge in range(2):
            directory = workspace / "grading" / f"{job['case']}-{job['repeat']}-{judge}"
            if json.loads((directory / "result.json").read_text()).get("exit_code") != 0:
                raise ValueError("Incomplete grade")
            reports = json.loads((directory / "grade.json").read_text())["reports"]
            matches = [r for r in reports if r["id"] == job["id"]]
            if len(matches) != 1:
                raise ValueError("Missing/duplicate report grade")
            grade = matches[0]
            if len(grade["findings"]) != len(finding_ids) or {f["id"] for f in grade["findings"]} != finding_ids:
                raise ValueError("A finding was not graded exactly once")
            if len(grade["units"]) != len(protocol["cases"][job["case"]]["units"]):
                raise ValueError("Unit count mismatch")
            for unit in grade["units"]:
                if not set(unit["finding_ids"]) <= finding_ids:
                    raise ValueError("Unknown finding citation")
                if unit["reported_gap"] and not unit["finding_ids"]:
                    raise ValueError("Positive prediction lacks finding evidence")
            confusion(protocol["cases"][job["case"]]["units"], {u["id"]: u["reported_gap"] for u in grade["units"]})
            grades.append(grade)
        predictions = {}
        for unit in protocol["cases"][job["case"]]["units"]:
            votes = [next(u for u in g["units"] if u["id"] == unit["id"])["reported_gap"] for g in grades]
            if votes[0] != votes[1]:
                unresolved.append({"run": job["id"], "unit": unit["id"]})
            predictions[unit["id"]] = votes[0]
        primary_units = [u for u in protocol["cases"][job["case"]]["units"] if u["id"] not in protocol["grading"]["primary_excluded_units"]]
        counts = confusion(primary_units, {u["id"]: predictions[u["id"]] for u in primary_units})
        verdicts = []
        for finding_id in sorted(finding_ids):
            votes = [next(f for f in g["findings"] if f["id"] == finding_id)["verdict"] for g in grades]
            verdicts.append({"id": finding_id, "verdict": votes[0] if votes[0] == votes[1] else "unresolved", "judges": votes})
        rows.append(dict(job, run=status, scores=dict(counts, f1=f1(counts)), predictions=predictions, findings=verdicts, judges=grades))
    scores = {v: {c: sum(r["scores"]["f1"] for r in rows if r["version"] == v and r["case"] == c) / REPEATS for c in protocol["cases"]} for v in ["baseline", "candidate"]}
    differences = [scores["candidate"][c] - scores["baseline"][c] for c in protocol["cases"]]
    delta = sum(differences) / len(differences)
    interval = cluster_interval(differences)
    support = {}
    for version in scores:
        verdicts = [f["verdict"] for r in rows if r["version"] == version for f in r["findings"]]
        support[version] = {v: verdicts.count(v) for v in ["supported", "contradicted", "unresolved"]}
        support[version]["established_support_rate"] = verdicts.count("supported") / len(verdicts) if verdicts else 1.0
    accepted = not unresolved and delta >= 0.05 and interval[0] > 0 and support["candidate"]["established_support_rate"] >= support["baseline"]["established_support_rate"] - 0.02
    result = {"protocol_sha256": digest(workspace / "protocol.json"), "created_utc": now(), "per_application_macro_f1": scores, "macro_f1_delta": delta, "paired_application_bootstrap_95_percent_interval": interval, "unresolved_units": unresolved, "factual_finding_review": support, "superiority_acceptance_passed": accepted, "rows": rows}
    write_json(workspace / "results.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "truth", "run", "grade", "summarize"])
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--codex-home", type=Path)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.action in {"run", "grade"}:
        if args.codex_home is None:
            parser.error("--codex-home is required for model-backed work")
        globals()[args.action](args.workspace.resolve(), args.codex_home.resolve(), args.workers)
    else:
        globals()[args.action](args.workspace.resolve())


if __name__ == "__main__":
    main()
