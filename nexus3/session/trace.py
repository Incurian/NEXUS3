"""Helpers for reconstructing persisted tool records from session storage."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from nexus3.session.storage import EventRow, MessageRow

TOOL_ID_DISPLAY_WIDTH = 8


def tool_display_id(tool_call_id: str, width: int = TOOL_ID_DISPLAY_WIDTH) -> str:
    """Return the visible short tool ID shown in REPL and trace output."""
    if len(tool_call_id) <= width:
        return tool_call_id
    return tool_call_id[-width:]


@dataclass
class ToolRecord:
    """Persisted tool call plus its associated result, if any."""

    tool_call_id: str
    name: str
    arguments: dict[str, Any]
    call_message_id: int
    call_timestamp: float
    result_message_id: int | None = None
    result_timestamp: float | None = None
    success: bool | None = None
    output: str = ""
    error: str = ""

    @property
    def display_id(self) -> str:
        return tool_display_id(self.tool_call_id)

    @property
    def status(self) -> str:
        if self.success is True:
            return "ok"
        if self.success is False:
            return "error"
        if self.result_message_id is not None:
            return "done"
        return "pending"

    @property
    def result_text(self) -> str:
        return self.error if self.error else self.output


def build_tool_records(messages: list[MessageRow], events: list[EventRow]) -> list[ToolRecord]:
    """Build ordered tool records from persisted messages and events."""
    records: list[ToolRecord] = []
    by_id: dict[str, ToolRecord] = {}

    for row in messages:
        if row.role == "assistant" and row.tool_calls:
            for tc in row.tool_calls:
                record = ToolRecord(
                    tool_call_id=tc["id"],
                    name=tc["name"],
                    arguments=tc.get("arguments", {}) or {},
                    call_message_id=row.id,
                    call_timestamp=row.timestamp,
                )
                records.append(record)
                by_id[record.tool_call_id] = record
        elif row.role == "tool" and row.tool_call_id:
            maybe_record = by_id.get(row.tool_call_id)
            if maybe_record is None:
                record = ToolRecord(
                    tool_call_id=row.tool_call_id,
                    name=row.name or "unknown",
                    arguments={},
                    call_message_id=row.id,
                    call_timestamp=row.timestamp,
                )
                records.append(record)
                by_id[record.tool_call_id] = record
            else:
                record = maybe_record

            if record.result_message_id is None:
                record.result_message_id = row.id
                record.result_timestamp = row.timestamp
                record.output = row.content

    completed_by_id: dict[str, EventRow] = {}
    for event in events:
        if event.event_type != "toolcompleted" or not event.data:
            continue
        tool_id = str(event.data.get("tool_id", "")).strip()
        if not tool_id:
            continue
        completed_by_id[tool_id] = event

    for record in records:
        maybe_event = completed_by_id.get(record.tool_call_id)
        if maybe_event is None or not maybe_event.data:
            continue
        event = maybe_event
        data = cast(dict[str, Any], event.data)

        record.result_timestamp = event.timestamp
        record.success = bool(data.get("success", False))
        record.output = str(data.get("output", "") or "")
        record.error = str(data.get("error", "") or "")

    return records


def select_recent_tool_records(records: list[ToolRecord], limit: int) -> list[ToolRecord]:
    """Return the most recent tool records, newest first."""
    bounded = records[-limit:] if limit > 0 else records
    return list(reversed(bounded))


def resolve_tool_record(
    records: list[ToolRecord],
    query: str,
) -> tuple[ToolRecord | None, str | None]:
    """Resolve a tool record by full ID, prefix, suffix, or visible short ID."""
    normalized = query.strip()
    if not normalized:
        return None, "Usage: /tool last | /tool <id>"

    if normalized == "last":
        if not records:
            return None, "No tool calls recorded for this session yet."
        return records[-1], None

    matches = [
        record
        for record in records
        if record.tool_call_id == normalized
        or record.tool_call_id.startswith(normalized)
        or record.tool_call_id.endswith(normalized)
        or record.display_id == normalized
    ]

    if not matches:
        return None, f"No tool call matches '{normalized}'."

    if len(matches) > 1:
        candidates = ", ".join(
            f"{record.display_id}:{record.name}"
            for record in select_recent_tool_records(matches, limit=5)
        )
        return None, f"Tool ID '{normalized}' is ambiguous. Matches: {candidates}"

    return matches[0], None


def format_tool_record_details(record: ToolRecord) -> str:
    """Format a full persisted tool record for editor display."""
    requested_at = datetime.fromtimestamp(record.call_timestamp).isoformat(
        sep=" ",
        timespec="seconds",
    )
    completed_at = (
        datetime.fromtimestamp(record.result_timestamp).isoformat(sep=" ", timespec="seconds")
        if record.result_timestamp is not None
        else "pending"
    )
    args_json = json.dumps(record.arguments, indent=2, sort_keys=True, ensure_ascii=False)

    lines = [
        f"Tool: {record.name}",
        f"Call ID: {record.tool_call_id}",
        f"Visible ID: {record.display_id}",
        f"Status: {record.status}",
        f"Requested At: {requested_at}",
        f"Completed At: {completed_at}",
        "",
        "Arguments:",
        "-" * 40,
        args_json,
        "",
        "Result:",
        "-" * 40,
        record.result_text or "(no result content recorded)",
    ]
    return "\n".join(lines)
