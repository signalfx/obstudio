from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


def load_schema(name: str) -> dict:
    with schema_path(name) as path:
        return json.loads(path.read_text(encoding="utf-8"))


def schema_validator(name: str) -> Draft202012Validator:
    schema = load_schema(name)
    common = load_schema("common.schema.json")
    registry = Registry().with_resources(
        [
            ("common.schema.json", Resource.from_contents(common)),
            (common.get("$id", "common.schema.json"), Resource.from_contents(common)),
        ]
    )
    return Draft202012Validator(schema, registry=registry)


@contextmanager
def schema_path(name: str) -> Iterator[Path]:
    traversable = resources.files("pytest_codex_evals").joinpath("schemas", name)
    with resources.as_file(traversable) as path:
        yield path
