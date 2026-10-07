"""Independent offline evaluation entrypoint with its own Splunk AO route."""

import os

from splunk_ao import SplunkAOLogger
from splunk_ao.agent_streams import AgentStreams
from splunk_ao.projects import Projects


def run_evaluation() -> str:
    """Publish a synthetic evaluation trace, not a live FastAPI chat turn."""

    project_name = os.environ.get("SPLUNK_AO_EVAL_PROJECT", "ai-assistant-demo-evaluation")
    stream_name = os.environ.get("SPLUNK_AO_EVAL_STREAM", "offline-evaluations")
    project = Projects().get(name=project_name)
    if project is None:
        raise RuntimeError(f"Configure an existing evaluation project: {project_name}")
    streams = AgentStreams()
    stream = streams.get(name=stream_name, project_id=project.id)
    if stream is None:
        stream = streams.create(name=stream_name, project_id=project.id)

    logger = SplunkAOLogger(project=project_name, agent_stream_id=stream.id)
    try:
        logger.start_trace(input="synthetic evaluation case", name="offline_assistant_evaluation")
        logger.add_llm_span(
            input="synthetic question",
            output="synthetic answer",
            model="synthetic-eval-model",
            name="evaluation_answer",
            num_input_tokens=2,
            num_output_tokens=2,
        )
        logger.conclude(output="synthetic evaluation passed")
        logger.flush()
    finally:
        logger.terminate()
    return str(stream.id)


if __name__ == "__main__":
    run_evaluation()
