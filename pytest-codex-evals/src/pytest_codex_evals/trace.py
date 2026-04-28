from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class CommandEvent:
    command: str
    status: str = ""


@dataclass
class TraceUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class TraceSummary:
    def __init__(self, events: list[dict[str, Any]], raw_text: str) -> None:
        self.events = events
        self.raw_text = raw_text
        self.commands = extract_commands(events)
        self.usage = extract_usage(events)


def parse_trace(path: Path) -> TraceSummary:
    raw = path.read_text(encoding="utf-8", errors="replace")
    events: list[dict[str, Any]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        events.append(json.loads(line))
    return TraceSummary(events, raw)


def extract_commands(events: list[dict[str, Any]]) -> list[CommandEvent]:
    commands: list[CommandEvent] = []
    for event in events:
        item = event.get("item")
        if item is None and isinstance(event.get("payload"), dict):
            item = event["payload"].get("item")
        if not isinstance(item, dict):
            continue
        if item.get("type") != "command_execution":
            continue
        command = item.get("command")
        if isinstance(command, str):
            commands.append(CommandEvent(command=command, status=str(item.get("status", ""))))
    return commands


def extract_usage(events: list[dict[str, Any]]) -> TraceUsage:
    total = TraceUsage()
    for event in events:
        usage = find_usage(event)
        if not usage:
            continue
        total.input_tokens += int(usage.get("input_tokens") or 0)
        total.output_tokens += int(usage.get("output_tokens") or 0)
        total.total_tokens += int(usage.get("total_tokens") or 0)
    if total.total_tokens == 0:
        total.total_tokens = total.input_tokens + total.output_tokens
    return total


def find_usage(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        usage = value.get("usage")
        if isinstance(usage, dict):
            return usage
        for child in value.values():
            found = find_usage(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_usage(child)
            if found:
                return found
    return None
