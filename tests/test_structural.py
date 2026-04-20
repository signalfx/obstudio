"""Structural eval tests -- golden-only and fixture modes."""

import re
from pathlib import Path

import pytest

from conftest import load_golden_props


# ---------------------------------------------------------------------------
# Helpers (fixture-mode only)
# ---------------------------------------------------------------------------

_SKIP_DIRS = {"node_modules", ".venv", "__pycache__", "build", "dist", ".git"}


def _find_files(root: Path, extensions: list[str]) -> list[Path]:
    results = []
    for p in root.rglob("*"):
        if any(s in p.parts for s in _SKIP_DIRS):
            continue
        if p.suffix in extensions:
            results.append(p)
    return results


def _check_single_sdk_init(fixture_dir: Path, lang: str) -> tuple[bool, str]:
    ext_map = {
        "python": [".py"],
        "node": [".js", ".mjs", ".ts"],
        "go": [".go"],
    }
    init_patterns = {
        "python": [r"TracerProvider", r"MeterProvider", r"configure_opentelemetry"],
        "node": [r"NodeSDK", r"TracerProvider", r"MeterProvider"],
        "go": [r"sdktrace\.NewTracerProvider", r"sdkmetric\.NewMeterProvider", r"initOTel"],
    }
    extensions = ext_map.get(lang, [".py", ".js", ".go"])
    patterns = init_patterns.get(lang, init_patterns["python"])
    sources = _find_files(fixture_dir, extensions)

    init_files = []
    for src in sources:
        text = src.read_text(errors="replace")
        if any(re.search(p, text) for p in patterns):
            init_files.append(src)

    if len(init_files) == 0:
        return False, "No SDK initialization file found"
    if len(init_files) > 1:
        names = [str(f.relative_to(fixture_dir)) for f in init_files]
        return False, f"Multiple SDK init files found: {names}"
    return True, f"Single SDK init: {init_files[0].relative_to(fixture_dir)}"


def _check_deps(fixture_dir: Path, lang: str, expected: list[str]) -> tuple[bool, str]:
    dep_files = {
        "python": ["pyproject.toml", "requirements.txt"],
        "node": ["package.json"],
        "go": ["go.mod"],
    }
    for f in dep_files.get(lang, []):
        p = fixture_dir / f
        if p.exists():
            text = p.read_text()
            missing = [pkg for pkg in expected if pkg not in text]
            if missing:
                return False, f"Missing packages in {f}: {missing}"
            return True, f"All expected packages found in {f}"
    return False, "No dependency file found"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGoldenStructural:
    """Validate golden files have well-formed structural properties."""

    def test_language_set(self, golden_dir):
        props = load_golden_props(golden_dir)
        assert props.get("language"), f"Missing 'language' in {golden_dir}"

    def test_required_properties(self, golden_dir):
        props = load_golden_props(golden_dir)
        required = ["language", "auto_instrumentation_packages"]
        missing = [k for k in required if k not in props]
        assert not missing, f"Missing properties {missing} in {golden_dir}"

    def test_packages_parseable(self, golden_dir):
        props = load_golden_props(golden_dir)
        raw = props.get("auto_instrumentation_packages", "")
        assert raw, "auto_instrumentation_packages is empty"
        pkgs = [p.strip().strip("'\"") for p in raw.split(",") if p.strip()]
        assert len(pkgs) > 0, "No packages could be parsed"


class TestFixtureStructural:
    """Validate an instrumented app (requires --app)."""

    def test_single_sdk_init(self, app_dir, golden_dir):
        if app_dir is None:
            pytest.skip("No --app provided")
        props = load_golden_props(golden_dir)
        lang = props.get("language", "unknown")
        ok, msg = _check_single_sdk_init(app_dir, lang)
        assert ok, msg

    def test_auto_instrumentation_deps(self, app_dir, golden_dir):
        if app_dir is None:
            pytest.skip("No --app provided")
        props = load_golden_props(golden_dir)
        lang = props.get("language", "unknown")
        raw = props.get("auto_instrumentation_packages", "")
        if not raw:
            pytest.skip("No auto_instrumentation_packages in golden")
        pkgs = [p.strip().strip("'\"") for p in raw.split(",") if p.strip()]
        ok, msg = _check_deps(app_dir, lang, pkgs)
        assert ok, msg
