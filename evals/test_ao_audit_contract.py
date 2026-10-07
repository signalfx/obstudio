"""Focused checks for AO audit evidence and local gateway selection guidance."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_ao_audit_requires_early_compatibility_evidence_and_gateway_candidate():
    canonical = (REPO_ROOT / "skills/otel-audit/SKILL.md").read_text()
    bundled = (REPO_ROOT / "plugins/obstudio/skills/otel-audit/SKILL.md").read_text()
    assert canonical == bundled

    discovery = canonical.split("### Step 1 -- Repository Discovery", 1)[1].split(
        "### Step 2 -- Instrumentation Assessment", 1
    )[0]
    for term in (
        "Before scoring AO routing",
        "canonical Audit Evidence",
        "project/Agent Stream API endpoint",
        "SDK auth configuration",
        "per-request trace routing separately",
        "`supported`",
        "`unsupported`",
        "`unverified`",
        "exact package/runtime evidence unavailable",
        "Do not defer this classification",
        "fresh cloud Agent Stream receipt",
        "Splunk Observability Studio as the preferred local AO gateway candidate",
        "availability and concrete endpoint `unverified`",
        "never invent an address",
    ):
        assert term in " ".join(discovery.split())

    gate = canonical.split("Before `finalize-audit`, apply this AO acceptance gate", 1)[1]
    assert "auth configuration and per-request trace-route compatibility as separate" in " ".join(
        gate.split()
    )
    assert "do not defer them to the acceptance scenario" in " ".join(gate.split())


def test_ao_route_dependency_closure_includes_nested_retrieval_producer():
    canonical = (REPO_ROOT / "skills/otel-audit/SKILL.md").read_text()
    contract = canonical.split("An AO routing finding's transitive dependency closure", 1)[1].split(
        "For a new live AO sink", 1
    )[0]
    for term in (
        "nested retrieval spans",
        "each required live GenAI readiness surface",
        "verification scenario",
        "included separately from the tool finding",
    ):
        assert term in " ".join(contract.split())
