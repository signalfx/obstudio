from __future__ import annotations

import time
from collections.abc import Iterable

import click

from telemetry import tracer


def process_task(task_type: str, delay_seconds: float) -> None:
    with tracer.start_as_current_span(
        "task process",
        attributes={"task.type": task_type},
    ):
        time.sleep(delay_seconds)


def run_batch(task_types: Iterable[str], delay_seconds: float = 0.0) -> None:
    # Intentionally wrong: a long-running command or scheduler keeps this span
    # current, making every independent task a child in one large trace.
    with tracer.start_as_current_span("click session"):
        for task_type in task_types:
            process_task(task_type, delay_seconds)


@click.command()
@click.option("--task", "task_types", multiple=True, required=True)
@click.option("--delay-seconds", default=0.0, type=float)
def cli(task_types: tuple[str, ...], delay_seconds: float) -> None:
    run_batch(task_types, delay_seconds)


if __name__ == "__main__":
    cli()
