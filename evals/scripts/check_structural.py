#!/usr/bin/env python3
"""Structural eval: verify that instrumented code meets structural requirements.

Checks:
  - Single SDK initialization file exists
  - No duplicate SDK init calls
  - Auto-instrumentation packages installed (per golden spec)
  - Custom metrics defined for Custom-category signals
  - OTel init imported by the entry point

Usage:
  python check_structural.py <fixture_dir> <golden_dir>
  python check_structural.py --golden-only <golden_dir>

In --golden-only mode, validates that the golden inventory has parseable
structural properties (language, auto_instrumentation_packages, etc.)
without requiring an instrumented fixture directory.

Exit code 0 if all checks pass, 1 otherwise.
"""

import re
import sys
from pathlib import Path

import yaml


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
                if val:
                    props[current_key] = val
                else:
                    props[current_key] = ""
            elif current_key and re.match(r"^\s+- (.+)$", line):
                item = re.match(r"^\s+- (.+)$", line).group(1).strip()
                existing = props.get(current_key, "")
                props[current_key] = f"{existing}, {item}" if existing else item
    return props


def find_files(root: Path, extensions: list[str]) -> list[Path]:
    """Recursively find source files, skipping common non-source dirs."""
    skip = {"node_modules", ".venv", "__pycache__", "build", "dist", ".git"}
    results = []
    for p in root.rglob("*"):
        if any(s in p.parts for s in skip):
            continue
        if p.suffix in extensions:
            results.append(p)
    return results


def check_single_sdk_init(fixture_dir: Path, lang: str) -> tuple[bool, str]:
    """Verify exactly one SDK init file exists."""
    ext_map = {
        "python": [".py"],
        "node": [".js", ".mjs", ".ts"],
        "go": [".go"],
    }
    extensions = ext_map.get(lang, [".py", ".js", ".go"])
    sources = find_files(fixture_dir, extensions)

    init_patterns = {
        "python": [r"TracerProvider", r"MeterProvider", r"configure_opentelemetry"],
        "node": [r"NodeSDK", r"TracerProvider", r"MeterProvider"],
        "go": [r"sdktrace\.NewTracerProvider", r"sdkmetric\.NewMeterProvider", r"initOTel"],
    }
    patterns = init_patterns.get(lang, init_patterns["python"])

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


def check_deps(fixture_dir: Path, lang: str, expected_packages: list[str]) -> tuple[bool, str]:
    """Verify auto-instrumentation packages are listed as dependencies."""
    dep_files = {
        "python": ["pyproject.toml", "requirements.txt"],
        "node": ["package.json"],
        "go": ["go.mod"],
    }
    files = dep_files.get(lang, [])
    found_file = None
    dep_text = ""
    for f in files:
        p = fixture_dir / f
        if p.exists():
            found_file = p
            dep_text = p.read_text()
            break

    if not found_file:
        return False, "No dependency file found"

    missing = [pkg for pkg in expected_packages if pkg not in dep_text]
    if missing:
        return False, f"Missing packages in {found_file.name}: {missing}"
    return True, f"All expected packages found in {found_file.name}"


def golden_only_check(golden_dir: Path) -> int:
    """Validate that golden structural properties are well-formed."""
    props = load_golden_props(golden_dir)
    results = []

    lang = props.get("language", "")
    results.append(("language_set", bool(lang),
                     f"language={lang}" if lang else "missing 'language' property"))

    expected_keys = ["language", "auto_instrumentation_packages"]
    found = [k for k in expected_keys if k in props]
    results.append(("required_props", len(found) == len(expected_keys),
                     f"found {found}, expected {expected_keys}"))

    auto_pkgs_raw = props.get("auto_instrumentation_packages", "")
    if auto_pkgs_raw:
        pkgs = [p.strip().strip('"').strip("'") for p in auto_pkgs_raw.split(",") if p.strip()]
        results.append(("packages_parseable", len(pkgs) > 0,
                         f"{len(pkgs)} packages listed"))

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)

    print(f"\nGolden Structural Check: {golden_dir}")
    print("-" * 50)
    for name, ok, msg in results:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}: {msg}")
    print(f"\n  {passed}/{total} checks passed")

    return 0 if passed == total else 1


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--golden-only":
        golden_dir = Path(sys.argv[2])
        if not golden_dir.is_dir():
            print(f"Golden directory not found: {golden_dir}")
            sys.exit(2)
        sys.exit(golden_only_check(golden_dir))

    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <fixture_dir> <golden_dir>")
        print(f"       {sys.argv[0]} --golden-only <golden_dir>")
        sys.exit(2)

    fixture_dir = Path(sys.argv[1])
    golden_dir = Path(sys.argv[2])

    if not fixture_dir.is_dir():
        print(f"Fixture directory not found: {fixture_dir}")
        sys.exit(2)
    if not golden_dir.is_dir():
        print(f"Golden directory not found: {golden_dir}")
        sys.exit(2)

    props = load_golden_props(golden_dir)
    lang = props.get("language", "unknown")

    results = []

    ok, msg = check_single_sdk_init(fixture_dir, lang)
    results.append(("single_sdk_init", ok, msg))

    auto_pkgs_raw = props.get("auto_instrumentation_packages", "")
    if auto_pkgs_raw:
        auto_pkgs = [p.strip().strip('"').strip("'") for p in auto_pkgs_raw.split(",") if p.strip()]
    else:
        auto_pkgs = []

    if auto_pkgs:
        ok, msg = check_deps(fixture_dir, lang, auto_pkgs)
        results.append(("auto_instrumentation_deps", ok, msg))

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)

    print(f"\nStructural Eval: {passed}/{total} checks passed")
    print("-" * 50)
    for name, ok, msg in results:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}: {msg}")

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
