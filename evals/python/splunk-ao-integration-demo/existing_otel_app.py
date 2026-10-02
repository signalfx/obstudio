"""Independent entrypoint with caller-owned OTel and export-only Splunk AO."""

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from splunk_ao import otel


provider = TracerProvider()
processor = otel.add_splunk_ao_span_processor(provider)
trace.set_tracer_provider(provider)
tracer = provider.get_tracer("splunk-ao-integration-demo")


def answer_question(question: str) -> str:
    with tracer.start_as_current_span("invoke_workflow answer_question") as span:
        span.set_attribute("gen_ai.operation.name", "invoke_workflow")
        return "metadata-only answer"


def shutdown() -> None:
    provider.shutdown()
