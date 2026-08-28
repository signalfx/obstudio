from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal


UsageProvider = Literal["codex", "claude", "unknown"]
UsageSource = Literal["cumulative", "incremental", "unknown"]
_EFFECTIVE_TOTAL_UNSET = object()


def _unset_effective_total() -> Any:
    return _EFFECTIVE_TOTAL_UNSET


@dataclass(frozen=True)
class _InvalidJSONInteger:
    """Retain an unparseable JSON integer without treating it as token usage."""

    raw: str


@dataclass
class CommandEvent:
    command: str
    status: str = ""


@dataclass
class TraceUsage:
    provider: UsageProvider = "unknown"
    source: UsageSource = "unknown"
    observed: bool = False
    usage_record_count: int = 0
    selected_record_count: int = 0
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_output_tokens: int | None = None
    provider_total_tokens: int | None = None
    derived_total_tokens: int | None = None
    effective_total_tokens: int | None = field(default_factory=_unset_effective_total)
    _effective_total_explicit: bool = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        self._effective_total_explicit = (
            self.effective_total_tokens is not _EFFECTIVE_TOTAL_UNSET
        )
        if not self._effective_total_explicit:
            self.effective_total_tokens = self.provider_total_tokens
            if self.effective_total_tokens is None:
                self.effective_total_tokens = self.derived_total_tokens

    @property
    def recognized(self) -> bool:
        return self.effective_total_tokens is not None or any(
            getattr(self, field) is not None for field in token_fields()
        )

    @property
    def total_tokens(self) -> int | None:
        if self._effective_total_explicit:
            return self.effective_total_tokens
        if self.provider_total_tokens is not None:
            return self.provider_total_tokens
        return self.derived_total_tokens


@dataclass(frozen=True)
class _UsageRecord:
    usage: dict[str, Any]
    source: UsageSource
    priority: int


class TraceSummary:
    def __init__(
        self,
        events: list[dict[str, Any]],
        raw_text: str,
        *,
        provider: UsageProvider = "unknown",
    ) -> None:
        self.events = events
        self.raw_text = raw_text
        self.commands = extract_commands(events)
        self.usage = extract_usage(events, provider=provider)


def parse_trace(path: Path, *, provider: UsageProvider = "codex") -> TraceSummary:
    raw = path.read_text(encoding="utf-8", errors="replace")
    return TraceSummary(parse_events(raw), raw, provider=provider)


def parse_events(raw: str) -> list[dict[str, Any]]:
    if not raw.strip():
        return []
    try:
        parsed = json.loads(raw, parse_int=_parse_json_integer)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return [parsed]
    if isinstance(parsed, list):
        return [event for event in parsed if isinstance(event, dict)]

    events: list[dict[str, Any]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line, parse_int=_parse_json_integer)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _parse_json_integer(raw: str) -> int | _InvalidJSONInteger:
    try:
        return int(raw)
    except ValueError:
        return _InvalidJSONInteger(raw)


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


def extract_usage(
    events: list[dict[str, Any]],
    *,
    provider: UsageProvider = "unknown",
) -> TraceUsage:
    records = usage_records(events, provider)
    if not records:
        return TraceUsage(provider=provider)

    cumulative = [record for record in records if record.source == "cumulative"]
    recognized_cumulative = [
        record for record in cumulative if normalize_usage(record.usage, provider).recognized
    ]
    if recognized_cumulative:
        highest_priority = max(record.priority for record in recognized_cumulative)
        selected = next(
            record
            for record in reversed(recognized_cumulative)
            if record.priority == highest_priority
        )
        usage = normalize_usage(selected.usage, provider)
        return replace(
            usage,
            source="cumulative",
            usage_record_count=len(records),
            selected_record_count=1,
        )

    incremental = [record for record in records if record.source == "incremental"]
    if any(normalize_usage(record.usage, provider).recognized for record in incremental):
        return combine_incremental_usage(incremental, provider, len(records))

    return TraceUsage(
        provider=provider,
        source=cumulative[-1].source if cumulative else records[-1].source,
        observed=True,
        usage_record_count=len(records),
        selected_record_count=1,
    )


def usage_records(
    events: list[dict[str, Any]], provider: UsageProvider
) -> list[_UsageRecord]:
    if provider == "codex":
        return codex_usage_records(events)
    if provider == "claude":
        return claude_usage_records(events)
    return unknown_usage_records(events)


def codex_usage_records(events: list[dict[str, Any]]) -> list[_UsageRecord]:
    records: list[_UsageRecord] = []
    for event in events:
        payload = event.get("payload")
        if isinstance(payload, dict) and payload.get("type") == "token_count":
            info = payload.get("info")
            if isinstance(info, dict):
                total = info.get("total_token_usage")
                if "total_token_usage" in info:
                    records.append(
                        _UsageRecord(usage_mapping(total), "cumulative", 30)
                    )
                if "last_token_usage" in info:
                    records.append(
                        _UsageRecord(
                            usage_mapping(info["last_token_usage"]),
                            "incremental",
                            10,
                        )
                    )

        if "usage" not in event:
            continue
        direct = usage_mapping(event["usage"])
        event_type = normalized_event_type(event.get("type"))
        if event_type in {"turn.completed", "turn.complete", "task.complete"}:
            records.append(_UsageRecord(direct, "cumulative", 20))
        else:
            records.append(_UsageRecord(direct, "incremental", 10))
    return records


def claude_usage_records(events: list[dict[str, Any]]) -> list[_UsageRecord]:
    records: list[_UsageRecord] = []
    for event in events:
        event_type = normalized_event_type(event.get("type"))
        if "usage" in event:
            direct = usage_mapping(event["usage"])
            source: UsageSource = "cumulative" if event_type == "result" else "incremental"
            priority = 30 if source == "cumulative" else 10
            records.append(_UsageRecord(direct, source, priority))

        message = event.get("message")
        if isinstance(message, dict) and "usage" in message:
            records.append(
                _UsageRecord(usage_mapping(message["usage"]), "incremental", 10)
            )
    return records


def unknown_usage_records(events: list[dict[str, Any]]) -> list[_UsageRecord]:
    records: list[_UsageRecord] = []
    for event in events:
        found = find_usage(event)
        if found is not None:
            records.append(_UsageRecord(found, "incremental", 10))
    return records


def normalized_event_type(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().lower().replace("/", ".").replace("_", ".")


def usage_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def combine_incremental_usage(
    records: list[_UsageRecord],
    provider: UsageProvider,
    record_count: int,
) -> TraceUsage:
    usages = [normalize_usage(record.usage, provider) for record in records]
    recognized = [usage for usage in usages if usage.recognized]
    combined = TraceUsage(
        provider=provider,
        source="incremental",
        observed=True,
        usage_record_count=record_count,
        selected_record_count=len(recognized),
        effective_total_tokens=None,
    )
    for field in token_fields():
        values = [getattr(usage, field) for usage in recognized]
        if values and all(value is not None for value in values):
            setattr(combined, field, sum(int(value) for value in values if value is not None))
    effective_totals = [usage.total_tokens for usage in recognized]
    if (
        len(recognized) == len(records)
        and effective_totals
        and all(value is not None for value in effective_totals)
    ):
        combined.effective_total_tokens = sum(
            int(value) for value in effective_totals if value is not None
        )
    return combined


def normalize_usage(
    usage: dict[str, Any], provider: UsageProvider
) -> TraceUsage:
    if provider == "claude":
        return normalize_claude_usage(usage)
    if provider == "codex":
        return normalize_codex_usage(usage)
    return normalize_unknown_usage(usage)


def normalize_codex_usage(usage: dict[str, Any]) -> TraceUsage:
    input_tokens = first_int(
        int_field(usage, "input_tokens"),
        int_field(usage, "prompt_tokens"),
    )
    cached_input_tokens = first_int(
        int_field(usage, "cached_input_tokens"),
        int_field(usage, "cached_tokens"),
        nested_int(usage, "input_tokens_details", "cached_tokens"),
        nested_int(usage, "prompt_tokens_details", "cached_tokens"),
    )
    cache_creation_input_tokens = first_int(
        int_field(usage, "cache_write_input_tokens"),
        int_field(usage, "cache_creation_input_tokens"),
        int_field(usage, "cache_write_tokens"),
        nested_int(usage, "input_tokens_details", "cache_write_tokens"),
        nested_int(usage, "prompt_tokens_details", "cache_write_tokens"),
    )
    if input_tokens is None:
        input_tokens = additive_input_total(
            int_field(usage, "uncached_input_tokens"),
            cached_input_tokens,
            cache_creation_input_tokens,
        )
    output_tokens = first_int(
        int_field(usage, "output_tokens"),
        int_field(usage, "completion_tokens"),
    )
    return normalized_usage(
        provider="codex",
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        cache_creation_input_tokens=cache_creation_input_tokens,
        output_tokens=output_tokens,
        reasoning_output_tokens=reasoning_tokens(usage),
        provider_total_tokens=int_field(usage, "total_tokens"),
    )


def normalize_claude_usage(usage: dict[str, Any]) -> TraceUsage:
    uncached_input_tokens = int_field(usage, "input_tokens")
    cached_input_tokens = int_field(usage, "cache_read_input_tokens")
    cache_creation_input_tokens = first_int(
        int_field(usage, "cache_creation_input_tokens"),
        complete_cache_creation_breakdown(usage),
    )
    return normalized_usage(
        provider="claude",
        input_tokens=additive_input_total(
            uncached_input_tokens,
            cached_input_tokens,
            cache_creation_input_tokens,
        ),
        cached_input_tokens=cached_input_tokens,
        cache_creation_input_tokens=cache_creation_input_tokens,
        output_tokens=int_field(usage, "output_tokens"),
        reasoning_output_tokens=reasoning_tokens(usage),
        provider_total_tokens=int_field(usage, "total_tokens"),
    )


def normalize_unknown_usage(usage: dict[str, Any]) -> TraceUsage:
    return normalized_usage(
        provider="unknown",
        input_tokens=first_int(
            int_field(usage, "input_tokens"),
            int_field(usage, "prompt_tokens"),
        ),
        cached_input_tokens=first_int(
            int_field(usage, "cached_input_tokens"),
            int_field(usage, "cache_read_input_tokens"),
        ),
        cache_creation_input_tokens=first_int(
            int_field(usage, "cache_creation_input_tokens"),
            int_field(usage, "cache_write_input_tokens"),
        ),
        output_tokens=first_int(
            int_field(usage, "output_tokens"),
            int_field(usage, "completion_tokens"),
        ),
        reasoning_output_tokens=reasoning_tokens(usage),
        provider_total_tokens=int_field(usage, "total_tokens"),
    )


def normalized_usage(
    *,
    provider: UsageProvider,
    input_tokens: int | None,
    cached_input_tokens: int | None,
    cache_creation_input_tokens: int | None,
    output_tokens: int | None,
    reasoning_output_tokens: int | None,
    provider_total_tokens: int | None,
) -> TraceUsage:
    derived_total_tokens = None
    if input_tokens is not None and output_tokens is not None:
        derived_total_tokens = input_tokens + output_tokens
    effective_total_tokens = provider_total_tokens
    if effective_total_tokens is None:
        effective_total_tokens = derived_total_tokens
    return TraceUsage(
        provider=provider,
        observed=True,
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        cache_creation_input_tokens=cache_creation_input_tokens,
        output_tokens=output_tokens,
        reasoning_output_tokens=reasoning_output_tokens,
        provider_total_tokens=provider_total_tokens,
        derived_total_tokens=derived_total_tokens,
        effective_total_tokens=effective_total_tokens,
    )


def reasoning_tokens(usage: dict[str, Any]) -> int | None:
    return first_int(
        int_field(usage, "reasoning_output_tokens"),
        int_field(usage, "thinking_tokens"),
        nested_int(usage, "output_tokens_details", "reasoning_tokens"),
        nested_int(usage, "output_tokens_details", "thinking_tokens"),
        nested_int(usage, "completion_tokens_details", "reasoning_tokens"),
        nested_int(usage, "completion_tokens_details", "thinking_tokens"),
    )


def additive_input_total(*values: int | None) -> int | None:
    if not values or any(value is None for value in values):
        return None
    return sum(int(value) for value in values if value is not None)


def complete_cache_creation_breakdown(usage: dict[str, Any]) -> int | None:
    cache_creation = usage.get("cache_creation")
    if not isinstance(cache_creation, dict):
        return None
    one_hour = int_field(cache_creation, "ephemeral_1h_input_tokens")
    five_minutes = int_field(cache_creation, "ephemeral_5m_input_tokens")
    if one_hour is None or five_minutes is None:
        return None
    return one_hour + five_minutes


def find_usage(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        usage = value.get("usage")
        if isinstance(usage, dict):
            return usage
        for child in value.values():
            found = find_usage(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_usage(child)
            if found is not None:
                return found
    return None


def int_field(value: Any, key: str) -> int | None:
    if not isinstance(value, dict) or key not in value:
        return None
    raw = value[key]
    if isinstance(raw, _InvalidJSONInteger) or isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, int):
        return raw if raw >= 0 else None
    if isinstance(raw, str):
        normalized = raw.strip()
        if not normalized.isascii() or not normalized.isdigit():
            return None
        try:
            return int(normalized)
        except ValueError:
            return None
    return None


def nested_int(value: Any, parent_key: str, key: str) -> int | None:
    if not isinstance(value, dict):
        return None
    nested = value.get(parent_key)
    if not isinstance(nested, dict):
        return None
    return int_field(nested, key)


def first_int(*values: int | None) -> int | None:
    for value in values:
        if value is not None:
            return value
    return None


def token_fields() -> tuple[str, ...]:
    return (
        "input_tokens",
        "cached_input_tokens",
        "cache_creation_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "provider_total_tokens",
        "derived_total_tokens",
    )
