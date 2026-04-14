"""LLM-based skill evals using deepeval.

A pytest-native deepeval suite. Uses Bedrock models (Claude, Llama, etc.) via the
Converse API as both the generation provider and the LLM-as-judge
evaluator.

Usage:
    uv run pytest test_llm.py -v                   # all LLM evals
    uv run pytest test_llm.py -m trigger -v        # trigger tests only
    uv run pytest test_llm.py -m golden -v         # golden comparison only

Prerequisites:
    - AWS credentials configured (AWS_PROFILE or env vars)
    - Model access enabled in Amazon Bedrock (us-west-2)
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import boto3
import pytest
from deepeval import assert_test
from deepeval.metrics import GEval
from deepeval.models import DeepEvalBaseLLM
from deepeval.test_case import LLMTestCase, LLMTestCaseParams

BEDROCK_REGION = "us-west-2"
GENERATOR_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
JUDGE_MODEL_ID = "us.anthropic.claude-sonnet-4-20250514-v1:0"

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
EXAMPLES_DIR = REPO_ROOT / "examples"

_SOURCE_EXTENSIONS = {".py", ".js", ".ts", ".go", ".java", ".rb", ".mod", ".toml", ".json"}
_SKIP_NAMES = {"uv.lock", "package-lock.json", "go.sum"}


def _load_source_context(app_path: Path) -> str:
    """Read source files from an example app and format as prompt context."""
    files = sorted(
        f
        for f in app_path.rglob("*")
        if f.is_file()
        and f.suffix in _SOURCE_EXTENSIONS
        and f.name not in _SKIP_NAMES
        and not any(p.startswith(".") for p in f.relative_to(app_path).parts)
        and "__pycache__" not in f.parts
        and "node_modules" not in f.parts
    )
    parts = []
    for f in files:
        rel = f.relative_to(app_path)
        content = f.read_text(errors="replace")
        parts.append(f"--- {rel} ---\n{content}")
    return "\n\n".join(parts)


def _load_skill_catalog() -> str:
    """Build a system prompt from skill SKILL.md frontmatter."""
    skills = []
    for skill_file in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        text = skill_file.read_text()
        name_m = re.search(r"^name:\s*(.+)$", text, re.MULTILINE)
        desc_m = re.search(
            r"^description:\s*>-?\s*\n((?:\s+.+\n)+)", text, re.MULTILINE
        )
        if name_m and desc_m:
            name = name_m.group(1).strip()
            desc = " ".join(desc_m.group(1).split())
            skills.append(f"- /{name}: {desc}")
    catalog = "\n".join(skills)
    return (
        "You are an AI coding assistant with access to the following "
        "observability skills. When the user's request matches a skill, "
        "activate that skill by name. When no skill matches, respond as "
        "a general coding assistant without mentioning any skill.\n\n"
        "Available skills:\n" + catalog
    )


SYSTEM_PROMPT = _load_skill_catalog()

_AUDIT_SKILL = (SKILLS_DIR / "splunk-audit" / "SKILL.md").read_text()
GOLDEN_SYSTEM_PROMPT = SYSTEM_PROMPT + "\n\n" + _AUDIT_SKILL


class BedrockModel(DeepEvalBaseLLM):
    """Bedrock wrapper using the Converse API (works with any provider)."""

    def __init__(
        self,
        model_id: str = JUDGE_MODEL_ID,
        region: str = BEDROCK_REGION,
    ):
        self.model_id = model_id
        self.region = region
        self._client = None

    def load_model(self):
        if self._client is None:
            self._client = boto3.client(
                "bedrock-runtime", region_name=self.region
            )
        return self._client

    def generate(
        self, prompt: str, schema=None, *, system: str | None = None
    ) -> str:
        client = self.load_model()
        kwargs: dict = {
            "modelId": self.model_id,
            "messages": [
                {"role": "user", "content": [{"text": prompt}]},
            ],
            "inferenceConfig": {"maxTokens": 4096},
        }
        if system:
            kwargs["system"] = [{"text": system}]
        resp = client.converse(**kwargs)
        text = resp["output"]["message"]["content"][0]["text"]

        if schema is not None:
            return schema(**json.loads(text))
        return text

    async def a_generate(self, prompt: str, schema=None) -> str:
        return self.generate(prompt, schema)

    def get_model_name(self) -> str:
        return self.model_id


# ---------------------------------------------------------------------------
# Model configurations
# ---------------------------------------------------------------------------

MODELS = [
    pytest.param(GENERATOR_MODEL_ID, JUDGE_MODEL_ID, id="haiku"),
    pytest.param("us.meta.llama4-scout-17b-instruct-v1:0", JUDGE_MODEL_ID, id="llama4-scout"),
]

_client_cache: dict[str, BedrockModel] = {}


def _get_client(model_id: str) -> BedrockModel:
    if model_id not in _client_cache:
        _client_cache[model_id] = BedrockModel(
            model_id=model_id, region=BEDROCK_REGION
        )
    return _client_cache[model_id]


# ---------------------------------------------------------------------------
# Trigger test cases
# ---------------------------------------------------------------------------

_NONE_RUBRIC = (
    "The response should NOT activate any observability skill "
    "(splunk-audit, splunk-instrument, splunk-verify, "
    "splunk-provision, splunk-observe). It should treat this "
    "as a general coding request."
)


def _skill_rubric(skill: str) -> str:
    return (
        f"The response should indicate activation of the {skill} "
        f"skill or begin performing the task associated with "
        f"{skill}. It should NOT activate other observability skills."
    )


_R = pytest.mark.release

TRIGGER_CASES = [
    # ── splunk-audit (smoke: obvious + 1 negative) ──────────────
    pytest.param("/splunk-audit", _skill_rubric("splunk-audit"), id="audit-obvious"),
    pytest.param("Scan this service for observability gaps", _skill_rubric("splunk-audit"), id="audit-scan-gaps", marks=_R),
    pytest.param("What signals am I missing in this codebase?", _skill_rubric("splunk-audit"), id="audit-missing-signals", marks=_R),
    pytest.param("Check observability readiness of this project", _skill_rubric("splunk-audit"), id="audit-readiness", marks=_R),
    pytest.param("Assess the instrumentation coverage before I start coding", _skill_rubric("splunk-audit"), id="audit-coverage", marks=_R),
    pytest.param("Write unit tests for the auth module", _NONE_RUBRIC, id="audit-neg-unit-tests"),
    pytest.param("Review this pull request for bugs", _NONE_RUBRIC, id="audit-neg-code-review", marks=_R),

    # ── splunk-instrument (smoke: obvious + 1 negative) ─────────
    pytest.param("/splunk-instrument", _skill_rubric("splunk-instrument"), id="instrument-obvious"),
    pytest.param("Add OpenTelemetry to this service", _skill_rubric("splunk-instrument"), id="instrument-add-otel", marks=_R),
    pytest.param("Add tracing to my Flask app", _skill_rubric("splunk-instrument"), id="instrument-add-tracing", marks=_R),
    pytest.param("Add metrics for my API endpoints", _skill_rubric("splunk-instrument"), id="instrument-add-metrics", marks=_R),
    pytest.param("Wire up telemetry for this Go service", _skill_rubric("splunk-instrument"), id="instrument-wire-telemetry", marks=_R),
    pytest.param("Implement observability for the order processing module", _skill_rubric("splunk-instrument"), id="instrument-impl-observability", marks=_R),
    pytest.param("Deploy this service to production", _NONE_RUBRIC, id="instrument-neg-deploy"),

    # ── splunk-verify (smoke: obvious + 1 negative) ────────────
    pytest.param("/splunk-verify", _skill_rubric("splunk-verify"), id="verify-obvious"),
    pytest.param("Check if telemetry is flowing from my service", _skill_rubric("splunk-verify"), id="verify-check-telemetry", marks=_R),
    pytest.param("Test my traces and make sure they reach the collector", _skill_rubric("splunk-verify"), id="verify-test-traces", marks=_R),
    pytest.param("Are my metrics actually being exported?", _skill_rubric("splunk-verify"), id="verify-metrics-working", marks=_R),
    pytest.param("Validate the instrumentation I just added", _skill_rubric("splunk-verify"), id="verify-validate", marks=_R),
    pytest.param("Run the linter on this file", _NONE_RUBRIC, id="verify-neg-linting"),

    # ── splunk-provision (smoke: obvious + 1 negative) ──────────
    pytest.param("/splunk-provision", _skill_rubric("splunk-provision"), id="provision-obvious"),
    pytest.param("Generate Terraform dashboards for this service", _skill_rubric("splunk-provision"), id="provision-terraform", marks=_R),
    pytest.param("Create alert rules for my verified signals", _skill_rubric("splunk-provision"), id="provision-alerts", marks=_R),
    pytest.param("Build monitoring configuration from the inventory", _skill_rubric("splunk-provision"), id="provision-monitoring", marks=_R),
    pytest.param("Set up SignalFx detectors for my service", _skill_rubric("splunk-provision"), id="provision-detectors", marks=_R),
    pytest.param("Create a new database migration", _NONE_RUBRIC, id="provision-neg-database"),

    # ── splunk-observe (smoke: obvious only) ─────────────────────
    pytest.param("/splunk-observe", _skill_rubric("splunk-observe"), id="observe-obvious"),
    pytest.param("Make this service fully observable", _skill_rubric("splunk-observe"), id="observe-full", marks=_R),
    pytest.param("Add end-to-end monitoring to this project", _skill_rubric("splunk-observe"), id="observe-e2e", marks=_R),
    pytest.param("Instrument and verify this service", _skill_rubric("splunk-observe"), id="observe-instrument-verify", marks=_R),
    pytest.param("Just run the audit, I don't want instrumentation yet", _skill_rubric("splunk-audit"), id="observe-neg-single-phase", marks=_R),

    # ── Cross-skill negatives (smoke: 1) ───────────────────────
    pytest.param("What's the weather in San Francisco?", _NONE_RUBRIC, id="neg-weather"),
    pytest.param("Refactor this function to use async/await", _NONE_RUBRIC, id="neg-generic-coding", marks=_R),
    pytest.param("Write API documentation for these endpoints", _NONE_RUBRIC, id="neg-documentation", marks=_R),
    pytest.param("Squash the last 3 commits", _NONE_RUBRIC, id="neg-git-operations", marks=_R),
]


def _save_result(
    name: str,
    metric: GEval,
    model_id: str,
    actual_output: str,
    results_file: Path,
) -> None:
    record = {
        "metric": name,
        "model": model_id,
        "score": round(metric.score, 2),
        "threshold": metric.threshold,
        "status": "PASS" if metric.score >= metric.threshold else "FAIL",
        "reason": metric.reason,
        "output": actual_output[:300],
    }
    with open(results_file, "a") as f:
        f.write(json.dumps(record) + "\n")


@pytest.mark.trigger
@pytest.mark.parametrize("generator_model_id,judge_model_id", MODELS)
@pytest.mark.parametrize("input_text,rubric", TRIGGER_CASES)
def test_trigger(input_text, rubric, generator_model_id, judge_model_id, results_file):
    generator = _get_client(generator_model_id)
    judge = _get_client(judge_model_id)
    actual_output = generator.generate(input_text, system=SYSTEM_PROMPT)
    test_case = LLMTestCase(input=input_text, actual_output=actual_output)
    metric = GEval(
        name="TriggerCorrectness",
        criteria=rubric,
        evaluation_params=[
            LLMTestCaseParams.INPUT,
            LLMTestCaseParams.ACTUAL_OUTPUT,
        ],
        model=judge,
        threshold=0.5,
    )
    metric.measure(test_case)
    _save_result("TriggerCorrectness", metric, generator_model_id, actual_output, results_file)
    assert_test(test_case, [metric])


# ---------------------------------------------------------------------------
# Golden comparison test cases
# ---------------------------------------------------------------------------

_GOLDEN_TASK = (
    "Analyze this codebase for observability gaps and list the "
    "signals you would track."
)

_GOLDEN_RUBRICS: dict[str, str] = {
    "python/flask-basic": (
        "The response should identify SLIs for a Flask task API including "
        "HTTP request latency, HTTP request throughput, HTTP error rate, "
        "task creation rate, task completion rate, and active task count. "
        "It should produce signal tables (Spans, Metrics, Logs) with "
        "categories: OOB for HTTP auto-instrumentation, Custom for task "
        "business metrics, and Derived for latency histograms. Signal "
        "names should follow OTel conventions (dotted lowercase)."
    ),
    "node/express-basic": (
        "The response should identify SLIs for an Express task API "
        "including HTTP request latency, HTTP request throughput, HTTP "
        "error rate, task creation rate, and active task count. It should "
        "produce signal tables with OOB spans and metrics from "
        "@opentelemetry/instrumentation-express and "
        "@opentelemetry/instrumentation-http, plus Custom metrics for "
        "task business logic."
    ),
    "go/chi-basic": (
        "The response should identify SLIs for a Chi task API including "
        "HTTP request latency, HTTP request throughput, HTTP error rate, "
        "task creation rate, and active task count. It should produce "
        "signal tables with OOB spans from otelhttp for HTTP server "
        "auto-instrumentation, plus Custom metrics for task business "
        "logic."
    ),
    "go/kvstore": (
        "The response should identify SLIs for a Go key-value store "
        "including HTTP request latency, KV get latency, KV set "
        "throughput, KV delete throughput, search latency, cache hit "
        "rate, eviction rate, and active key count. It should produce "
        "OOB spans from otelhttp for HTTP, Custom spans for get/set/"
        "delete/search operations, Custom metrics for store gauges and "
        "counters, and log signals for persistence failures and "
        "evictions. Signal names should follow OTel conventions."
    ),
}

_GOLDEN_SMOKE = {"python/flask-basic"}

GOLDEN_CASES = [
    pytest.param(
        f"{_GOLDEN_TASK}\n\n<codebase path=\"{app_id}\">\n"
        f"{_load_source_context(EXAMPLES_DIR / app_id)}\n</codebase>",
        rubric,
        id=app_id,
        marks=() if app_id in _GOLDEN_SMOKE else (_R,),
    )
    for app_id, rubric in _GOLDEN_RUBRICS.items()
]


@pytest.mark.golden
@pytest.mark.parametrize("generator_model_id,judge_model_id", MODELS)
@pytest.mark.parametrize("input_text,rubric", GOLDEN_CASES)
def test_golden(input_text, rubric, generator_model_id, judge_model_id, results_file):
    generator = _get_client(generator_model_id)
    judge = _get_client(judge_model_id)
    actual_output = generator.generate(input_text, system=GOLDEN_SYSTEM_PROMPT)
    test_case = LLMTestCase(input=input_text, actual_output=actual_output)
    metric = GEval(
        name="GoldenComparison",
        criteria=rubric,
        evaluation_params=[
            LLMTestCaseParams.INPUT,
            LLMTestCaseParams.ACTUAL_OUTPUT,
        ],
        model=judge,
        threshold=0.3,
    )
    metric.measure(test_case)
    _save_result("GoldenComparison", metric, generator_model_id, actual_output, results_file)
    assert_test(test_case, [metric])
