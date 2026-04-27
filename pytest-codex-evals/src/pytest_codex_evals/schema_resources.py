from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path


def load_schema(name: str) -> dict:
    with schema_path(name) as path:
        return json.loads(path.read_text(encoding="utf-8"))


@contextmanager
def schema_path(name: str) -> Iterator[Path]:
    traversable = resources.files("pytest_codex_evals").joinpath("schemas", name)
    with resources.as_file(traversable) as path:
        yield path
