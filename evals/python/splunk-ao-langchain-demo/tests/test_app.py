import os
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


def test_callback_captures_synthetic_inputs_and_outputs() -> None:
    question = "Summarize the synthetic Seattle weather"
    result = run_demo(question)
    trace = result.trace_batches[0].model_dump(mode="json")["traces"][0]
    workflow = trace["spans"][0]
    tool, model = workflow["spans"]

    assert trace["input"] == question
    assert workflow["input"] == question
    assert trace["output"] == result.answer
    assert tool["input"] == '{"city": "Seattle"}'
    assert "synthetic" in tool["output"]
    assert question in model["input"][0]["content"]
    assert "sunny" in model["output"]["content"]


def test_unapproved_caller_text_reaches_raw_capture_in_baseline() -> None:
    marker = "UNAPPROVED_INPUT_SENTINEL"
    result = run_demo(marker)
    trace = result.trace_batches[0].model_dump(mode="json")["traces"][0]

    assert trace["input"] == marker
    assert marker in trace["spans"][0]["spans"][1]["input"][0]["content"]


def test_demo_requires_no_credentials_network_or_obstudio(monkeypatch) -> None:
    for name in (
        "OPENAI_API_KEY",
        "SPLUNK_ACCESS_TOKEN",
        "SPLUNK_AO_API_KEY",
        "SPLUNK_O11Y_ACCESS_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    for name in tuple(os.environ):
        if name.startswith("OBSTUDIO_"):
            monkeypatch.delenv(name, raising=False)

    def reject_network(*args, **kwargs):
        raise AssertionError("the local demo attempted network access")

    monkeypatch.setattr(socket, "create_connection", reject_network)
    for method in ("connect", "connect_ex", "send", "sendall", "sendto", "sendmsg"):
        if hasattr(socket.socket, method):
            monkeypatch.setattr(socket.socket, method, reject_network)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        with pytest.raises(AssertionError, match="attempted network access"):
            probe.connect(("127.0.0.1", 9))
        with pytest.raises(AssertionError, match="attempted network access"):
            probe.connect_ex(("127.0.0.1", 9))
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        with pytest.raises(AssertionError, match="attempted network access"):
            probe.sendto(b"probe", ("127.0.0.1", 9))
    result = run_demo("Use only local synthetic data")

    assert result.answer == "Seattle is sunny in the local demo."
    assert result.logger_terminated is True
    assert result.trace_batches
    assert not any(name.startswith("OBSTUDIO_") for name in os.environ)
