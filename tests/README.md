# Skill Evals

Two layers of evaluation for obstudio skills:

| Layer | Tool | Requires LLM? | When to run |
|-------|------|---------------|-------------|
| **Deterministic** | pytest | No | Every PR (`make pytest`) |
| **LLM-based** | deepeval (pytest) | Yes | After skill changes, optionally in CI |

Deterministic tests validate skill *output* (structure, naming, budgets)
using pure Python assertions -- no LLM calls.  LLM-based tests validate
skill *behavior* (correct activation, quality of generated analysis)
using an LLM-as-judge.

---

## Deterministic evals (pytest)

### Quick start

```sh
make pytest                                          # CI-safe: golden + performance
make eval-fixture APP=examples/python/flask-basic  # local: includes fixture tests
```

Or run pytest directly:

```sh
cd tests
uv run pytest                                      # all tests
uv run pytest test_semconv.py -v                   # single suite
uv run pytest -k "performance" -v                  # keyword filter
uv run pytest --app=../examples/python/flask-basic # fixture mode
```

Dependencies are managed by **uv** (lockfile: `pyproject.toml` +
`uv.lock`).

### Two modes

| Mode | When | What runs |
|------|------|-----------|
| **Golden-only** | CI, `make pytest` | Validates golden reference files for self-consistency |
| **Fixture** | Local, `make eval-fixture` | Validates an instrumented app against its golden reference |

Fixture-mode tests auto-skip when `--app` is not provided, so
`make pytest` is always safe for CI.

### Test suites

| File | What it validates |
|------|-------------------|
| `test_structural.py` | Golden properties (language, packages) and fixture SDK init / deps |
| `test_semconv.py` | Metric name format, span cardinality, high-cardinality attribute scan |
| `test_golden.py` | Signal sections present, unique names, valid categories, golden-vs-fixture comparison |
| `test_performance.py` | Skill and reference token budgets, combined context window limits |

Tests are parametrized across all golden directories (Python, Node, Go).
Token budgets are defined in `conftest.py` -- adjust them when a skill
legitimately grows.

### Configuration

**`pyproject.toml`** — pytest options:

```toml
[tool.pytest.ini_options]
testpaths = ["."]
python_files = ["test_*.py"]
addopts = "-v --tb=short"
```

**CLI options** (via `conftest.py`):

| Option | Default | Purpose |
|--------|---------|---------|
| `--app` | None | Path to an instrumented example app |
| `--pass-rate` | 0.90 | Minimum threshold for fixture comparison tests |

---

## LLM-based evals (deepeval)

These tests invoke an LLM and use an LLM-as-judge (GEval) to evaluate
the response.  They require AWS credentials for Bedrock.

| Marker | Source | What it validates |
|--------|--------|-------------------|
| `trigger` | `test_llm.py` | Correct skill activates for a given prompt (35 positive/negative cases) |
| `golden` | `test_llm.py` | Audit output for known apps matches expected SLI/signal structure |

### Prerequisites

- AWS credentials configured (`AWS_PROFILE` or `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`)
- Claude model access enabled in Amazon Bedrock (us-west-2)

### Running

```sh
make ab-test                                         # LLM A/B smoke tests

# or run pytest directly for finer control:
cd tests
uv run pytest test_llm.py -v                         # all LLM tests
uv run pytest test_llm.py -m trigger -v              # trigger tests only
uv run pytest test_llm.py -m golden -v               # golden comparison only
```

### Configuration

All test data is defined as `pytest.param` tables in `test_llm.py`:

- **`MODELS`** -- generator/judge model pairs. Tests run against every
  entry, enabling cross-model comparison. Add a new `pytest.param` row
  to evaluate an additional model.
- **`TRIGGER_CASES`** -- input prompt + rubric pairs for skill routing.
- **`GOLDEN_CASES`** -- input prompt + rubric pairs for audit quality.

Edit `BEDROCK_REGION` to change the AWS region.

---

## Architecture

```
tests/
├── conftest.py           # shared fixtures, helpers, constants, CLI options
├── test_structural.py    # structural compliance tests
├── test_semconv.py       # semantic convention tests
├── test_golden.py        # golden self-consistency tests
├── test_performance.py   # token budget tests
├── golden/
│   ├── python/flask-basic/inventory.md
│   ├── node/express-basic/inventory.md
│   └── go/chi-basic/inventory.md
├── test_llm.py           # LLM-based eval tests (deepeval + Bedrock)
├── pyproject.toml        # dependencies + pytest config
└── uv.lock               # locked dependency versions
```

Shared helpers (table parsing, property loading, token estimation) live
in `conftest.py`.  Test-specific helpers are private to each test file.

## Golden files

Each golden directory contains an `inventory.md` with these sections:

- **SLI Definitions** — expected Service Level Indicators
- **Spans** — expected span signals with Category, Component, and SLI mapping
- **Metrics** — expected metric signals with the same columns
- **Logs** — expected log signals
- **Expected Structural Properties** — language, framework, auto-instrumentation
  packages, signal counts, and component list

Categories are `OOB` (auto-instrumentation), `Custom` (hand-written), or
`Derived` (trace-derived metrics).

### Adding a new golden

1. Create the example app under `examples/<language>/<app-name>/`.
2. Run `/splunk-audit` to generate `.observe/inventory.md`.
3. Review for correctness.
4. Copy signal tables and structural properties into
   `tests/golden/<language>/<app-name>/inventory.md`.
5. Run `make pytest` — the new golden is auto-discovered by the
   parametrized `golden_dir` fixture in `conftest.py`.

## CI

The `skill-tests` job in `.github/workflows/ci.yml` installs `uv` and
runs `make pytest` (deterministic tests).  LLM-based A/B tests can also run
in CI if AWS credentials are configured -- add a step that runs
`make ab-test` with Bedrock access via IAM role or secrets.
