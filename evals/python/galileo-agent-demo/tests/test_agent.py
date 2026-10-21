import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

spec = importlib.util.spec_from_file_location("galileo_replay_agent", Path(__file__).resolve().parents[1] / "agent.py")
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.exporter = InMemorySpanExporter()
        self.provider = TracerProvider()
        self.provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        self.tracer = patch.object(agent, "tracer", self.provider.get_tracer("test"))
        self.tracer.start()
        self.addCleanup(self.tracer.stop)
        self.addCleanup(self.provider.shutdown)

    def test_model_selected_tool_result_returns_to_model(self):
        messages = [{"role": "user", "content": "Find docs"}]
        self.assertEqual(agent.run_agent(agent.ReplayModel(), messages), "Documentation for returns")
        spans = self.exporter.get_finished_spans()
        root = next(s for s in spans if s.attributes["gen_ai.operation.name"] == "invoke_agent")
        self.assertEqual(root.attributes["gen_ai.agent.name"], agent.AGENT_NAME)
        self.assertEqual(len(spans), 4)
        self.assertTrue(all(s.parent.span_id == root.context.span_id for s in spans if s is not root))
        self.assertEqual(messages[-2]["role"], "tool")

    def test_no_tool_has_no_invented_tool_span(self):
        class Model:
            def complete(self, **kwargs):
                return {"role": "assistant", "content": "hello"}

        self.assertEqual(agent.run_agent(Model(), []), "hello")
        self.assertEqual(len(self.exporter.get_finished_spans()), 2)

    def test_provider_failure_propagates_and_marks_agent(self):
        class Model:
            def complete(self, **kwargs):
                raise RuntimeError("synthetic failure")

        with self.assertRaises(RuntimeError):
            agent.run_agent(Model(), [])
        spans = self.exporter.get_finished_spans()
        self.assertEqual(len(spans), 2)
        self.assertTrue(all(s.status.status_code == StatusCode.ERROR for s in spans))
        self.assertEqual(spans[-1].attributes["error.type"], "RuntimeError")
