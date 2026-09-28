import socket
import sys
from pathlib import Path

import pytest

pytest.importorskip("langchain_core")
pytest.importorskip("splunk_ao")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import run_demo


def _span_tree(result) -> list[tuple[str, str, str | None]]:
    nodes: list[tuple[str, str, str | None]] = []

    def visit(span: dict, parent: str | None) -> None:
        name = span["name"]
        nodes.append((span["type"], name, parent))
        for child in span.get("spans", []):
            visit(child, name)

    for batch in result.trace_batches:
        for trace in batch.model_dump(mode="json")["traces"]:
            for span in trace["spans"]:
                visit(span, None)
    return nodes


def test_demo_emits_one_local_langchain_trace_tree() -> None:
    result = run_demo("Summarize the synthetic Seattle weather")

    assert result.answer == "Seattle is sunny in the local demo."
    assert len(result.trace_batches) == 1
    assert _span_tree(result) == [
        ("workflow", "support_agent", None),
        ("tool", "lookup_weather", "support_agent"),
        ("llm", "DemoLocalLLM", "support_agent"),
    ]


def test_demo_requires_no_credentials_or_network(monkeypatch) -> None:
    for name in (
        "OPENAI_API_KEY",
        "SPLUNK_ACCESS_TOKEN",
        "SPLUNK_AO_API_KEY",
        "SPLUNK_O11Y_ACCESS_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)

    def reject_network(*args, **kwargs):
        raise AssertionError("the local demo attempted network access")

    monkeypatch.setattr(socket, "create_connection", reject_network)
    result = run_demo("Use only local synthetic data")

    assert result.answer == "Seattle is sunny in the local demo."
    assert result.logger_terminated is True
    assert result.trace_batches
