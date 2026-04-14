"""Shared fixtures and helpers for skill evals."""

import re
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
EVALS_DIR = REPO_ROOT / "evals"
GOLDEN_DIR = EVALS_DIR / "golden"
SKILLS_DIR = REPO_ROOT / "skills"
REFS_DIR = SKILLS_DIR / "references"
EXAMPLES_DIR = REPO_ROOT / "examples"

GOLDEN_SUITES = sorted(
    [p.parent for p in GOLDEN_DIR.rglob("inventory.md")],
    key=lambda p: str(p),
)

GOLDEN_IDS = [
    str(p.relative_to(GOLDEN_DIR)) for p in GOLDEN_SUITES
]


# ---------------------------------------------------------------------------
# Token budget constants
# ---------------------------------------------------------------------------

CHARS_PER_TOKEN = 4

SKILL_TOKEN_BUDGETS = {
    "splunk-audit": 4000,
    "splunk-instrument": 2500,
    "splunk-verify": 3500,
    "splunk-provision": 2500,
    "splunk-observe": 1500,
}

REFERENCE_TOKEN_BUDGETS = {
    "observability-template.md": 2000,
    "signal-mapping-guide.md": 3000,
    "fault-domain-patterns.md": 2500,
}

LANGUAGE_REF_BUDGET = 3000
MAX_SINGLE_SKILL_CONTEXT = 10000


def estimate_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN


# ---------------------------------------------------------------------------
# Markdown table parsing (shared by semconv and golden tests)
# ---------------------------------------------------------------------------

def parse_md_table(lines: list[str], start_idx: int) -> list[dict]:
    """Parse a markdown table starting at the header line index."""
    if start_idx >= len(lines):
        return []

    header_line = lines[start_idx]
    headers = [h.strip() for h in header_line.split("|") if h.strip()]
    rows = []
    i = start_idx + 1

    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("|---"):
            i += 1
            continue
        if not line.strip() or not line.strip().startswith("|"):
            break
        if line.strip().startswith("##"):
            break
        cols = [c.strip() for c in line.split("|") if c.strip()]
        if len(cols) >= 2:
            row = {}
            for j, h in enumerate(headers):
                if j < len(cols):
                    row[h] = cols[j]
            rows.append(row)
        i += 1

    return rows


def parse_signal_tables(text: str) -> dict[str, list[dict]]:
    """Extract signal rows from Spans, Metrics, and Logs tables."""
    lines = text.splitlines()
    tables: dict[str, list[dict]] = {"spans": [], "metrics": [], "logs": []}

    current_section = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "## Spans":
            current_section = "spans"
        elif stripped == "## Metrics":
            current_section = "metrics"
        elif stripped == "## Logs":
            current_section = "logs"
        elif stripped.startswith("## ") and current_section:
            current_section = None

        if current_section and "Signal Name" in line and "|" in line:
            tables[current_section] = parse_md_table(lines, i)
            current_section = None

    return tables


def all_signals(tables: dict[str, list[dict]]) -> list[dict]:
    """Flatten all signal tables into a single list."""
    result = []
    for rows in tables.values():
        result.extend(rows)
    return result


def extract_signal_names(signals: list[dict]) -> set[str]:
    return {
        s.get("Signal Name", "").strip("`")
        for s in signals
        if s.get("Signal Name", "").strip("`")
    }


# ---------------------------------------------------------------------------
# Golden structural property parsing
# ---------------------------------------------------------------------------

def load_golden_props(golden_dir: Path) -> dict:
    """Parse the Expected Structural Properties block from golden inventory."""
    inventory = golden_dir / "inventory.md"
    text = inventory.read_text()
    props = {}
    in_props = False
    current_key = None
    for line in text.splitlines():
        if line.strip() == "## Expected Structural Properties":
            in_props = True
            continue
        if in_props:
            if line.startswith("##"):
                break
            m = re.match(r"^- (\w[\w_]*):\s*(.*)$", line.strip())
            if m:
                current_key = m.group(1)
                val = m.group(2).strip()
                props[current_key] = val if val else ""
            elif current_key and re.match(r"^\s+- (.+)$", line):
                item = re.match(r"^\s+- (.+)$", line).group(1).strip()
                existing = props.get(current_key, "")
                props[current_key] = f"{existing}, {item}" if existing else item
    return props


# ---------------------------------------------------------------------------
# Pytest hooks and fixtures
# ---------------------------------------------------------------------------

def pytest_addoption(parser):
    parser.addoption(
        "--app",
        default=None,
        help="Path to an instrumented example app (for fixture-mode tests)",
    )
    parser.addoption(
        "--pass-rate",
        type=float,
        default=0.90,
        help="Minimum pass rate threshold (default: 0.90)",
    )


@pytest.fixture(scope="session")
def results_file(tmp_path_factory):
    """JSONL file for eval results, one per session."""
    d = tmp_path_factory.mktemp("eval-results")
    path = d / f"eval-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    return path


def pytest_terminal_summary(terminalreporter):
    """Print the results file path in the pytest summary block."""
    tmp_root = terminalreporter.config._tmp_path_factory.getbasetemp()
    results = sorted(tmp_root.rglob("eval-*.jsonl"))
    if results:
        terminalreporter.write_sep("=", "eval results")
        for r in results:
            terminalreporter.write_line(f"  {r}")


@pytest.fixture
def app_dir(request):
    """Instrumented example app directory (None if not provided)."""
    val = request.config.getoption("--app")
    if val is None:
        return None
    p = Path(val)
    if not p.is_absolute():
        p = REPO_ROOT / p
    if not p.is_dir():
        pytest.skip(f"App directory not found: {p}")
    return p


@pytest.fixture(params=GOLDEN_SUITES, ids=GOLDEN_IDS)
def golden_dir(request):
    """Parametrized fixture yielding each golden directory."""
    return request.param


@pytest.fixture
def golden_inventory(golden_dir):
    """Path to inventory.md inside the golden directory."""
    inv = golden_dir / "inventory.md"
    assert inv.exists(), f"Golden inventory not found: {inv}"
    return inv
