"""Local LangChain app instrumented through Splunk AO's supported callback."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models.fake import FakeListLLM
from langchain_core.runnables import RunnableConfig, RunnableLambda
from langchain_core.tools import tool
from splunk_ao import SplunkAOLogger
from splunk_ao.handlers.langchain import SplunkAOCallback


class DemoLocalLLM(FakeListLLM):
    """Deterministic local model that never calls a model provider."""


@tool
def lookup_weather(city: str) -> str:
    """Return synthetic weather for the requested city."""

    return json.dumps({"city": city, "condition": "sunny", "source": "synthetic"})


@dataclass(frozen=True)
class DemoResult:
    answer: str
    trace_batches: tuple[Any, ...]
    logger_terminated: bool


def _support_turn(question: str, config: RunnableConfig) -> str:
    weather = lookup_weather.invoke({"city": "Seattle"}, config=config)
    model = DemoLocalLLM(responses=["Seattle is sunny in the local demo."])
    return model.invoke(f"{question}\nSynthetic tool result: {weather}", config=config)


def run_demo(question: str = "What is the synthetic weather?") -> DemoResult:
    """Run one callback-owned LangChain trace without credentials or network."""

    trace_batches: list[Any] = []
    logger = SplunkAOLogger(
        project="local-framework-demo",
        agent_stream="langchain-callback",
        ingestion_hook=trace_batches.append,
    )
    callback = SplunkAOCallback(
        splunk_ao_logger=logger,
        start_new_trace=True,
        flush_on_chain_end=True,
    )
    chain = RunnableLambda(_support_turn).with_config(run_name="support_agent")

    try:
        answer = chain.invoke(question, config={"callbacks": [callback]})
    finally:
        logger.terminate()

    return DemoResult(
        answer=answer,
        trace_batches=tuple(trace_batches),
        logger_terminated=bool(getattr(logger, "_terminated", False)),
    )


if __name__ == "__main__":
    demo = run_demo()
    print(json.dumps({"answer": demo.answer, "trace_batches": len(demo.trace_batches)}))
