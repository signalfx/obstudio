# Skill Evals

Two layers of evaluation for obstudio skills:

| Layer | Tool | Requires LLM? | When to run |
|-------|------|---------------|-------------|
| **Deterministic** | pytest | No | Every PR (`make eval`) |
| **LLM-based** | promptfoo | Yes | After skill changes, optionally in CI |

Deterministic tests validate skill *output* (structure, naming, budgets)
using pure Python assertions -- no LLM calls.  LLM-based tests validate
skill *behavior* (correct activation, quality of generated analysis)
using an LLM-as-judge.

---

## Deterministic evals (pytest)

### Quick start

```sh
make eval                                          # CI-safe: golden + performance
make eval-fixture APP=examples/python/flask-basic  # local: includes fixture tests
```

Or run pytest directly:

```sh
cd evals
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
| **Golden-only** | CI, `make eval` | Validates golden reference files for self-consistency |
| **Fixture** | Local, `make eval-fixture` | Validates an instrumented app against its golden reference |

Fixture-mode tests auto-skip when `--app` is not provided, so
`make eval` is always safe for CI.

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

## LLM-based evals (promptfoo)

These tests invoke an LLM and use an LLM-as-judge to evaluate the
response.  They require an API key.

| Tag | Config | What it validates |
|-----|--------|-------------------|
| `trigger` | `promptfoo.yaml` + `trigger-tests.yaml` | Correct skill activates for a given prompt (30+ positive/negative cases) |
| `golden` | `promptfoo.yaml` | Audit output for known apps matches expected SLI/signal structure |

### Prerequisites

- Node.js 20+
- AWS credentials configured (`AWS_PROFILE` or `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`)
- Claude model access enabled in Amazon Bedrock (us-east-1)

### Running

```sh
make eval-llm                                        # all LLM evals

# or run promptfoo directly for finer control:
cd evals
npx promptfoo eval --filter-tag trigger              # trigger tests only
npx promptfoo eval --filter-tag golden               # golden comparison only
npx promptfoo view                                   # open results in browser
```

### Configuration

`promptfoo.yaml` configures the provider (Claude Sonnet via Amazon
Bedrock at temperature 0), prompts, and test assertions.  Edit this file
to change models, regions, or adjust rubrics.

---

## Architecture

```
evals/
├── conftest.py           # shared fixtures, helpers, constants, CLI options
├── test_structural.py    # structural compliance tests
├── test_semconv.py       # semantic convention tests
├── test_golden.py        # golden self-consistency tests
├── test_performance.py   # token budget tests
├── golden/
│   ├── python/flask-basic/inventory.md
│   ├── node/express-basic/inventory.md
│   └── go/chi-basic/inventory.md
├── promptfoo.yaml        # LLM-based eval config
├── trigger-tests.yaml    # trigger test case catalog
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
   `evals/golden/<language>/<app-name>/inventory.md`.
5. Run `make eval` — the new golden is auto-discovered by the
   parametrized `golden_dir` fixture in `conftest.py`.

## CI

The `skill-evals` job in `.github/workflows/ci.yml` installs `uv` and
runs `make eval` (deterministic tests).  LLM-based evals can also run
in CI if AWS credentials are configured -- add a step that runs
`npx promptfoo eval` with Bedrock access via IAM role or secrets.
