"""Tests for persisted session trace helpers."""

from __future__ import annotations

from nexus3.session.storage import EventRow, MessageRow
from nexus3.session.trace import (
    build_tool_records,
    format_tool_record_details,
    resolve_tool_record,
    tool_display_id,
)


def test_build_tool_records_prefers_toolcompleted_event_details() -> None:
    messages = [
        MessageRow(
            id=1,
            role="assistant",
            content="",
            meta=None,
            name=None,
            tool_call_id=None,
            tool_calls=[
                {
                    "id": "toolu_abc12345",
                    "name": "search_text",
                    "arguments": {"path": "x"},
                }
            ],
            tokens=None,
            timestamp=100.0,
            in_context=True,
            summary_of=None,
        ),
        MessageRow(
            id=2,
            role="tool",
            content="fallback output",
            meta=None,
            name="search_text",
            tool_call_id="toolu_abc12345",
            tool_calls=None,
            tokens=None,
            timestamp=101.0,
            in_context=True,
            summary_of=None,
        ),
    ]
    events = [
        EventRow(
            id=1,
            message_id=None,
            event_type="toolcompleted",
            data={
                "tool_id": "toolu_abc12345",
                "success": False,
                "error": "real error",
                "output": "",
            },
            timestamp=102.0,
        )
    ]

    records = build_tool_records(messages, events)

    assert len(records) == 1
    record = records[0]
    assert record.display_id == tool_display_id("toolu_abc12345")
    assert record.success is False
    assert record.error == "real error"
    assert record.output == ""
    assert record.result_timestamp == 102.0


def test_resolve_tool_record_matches_full_prefix_and_suffix() -> None:
    messages = [
        MessageRow(
            id=1,
            role="assistant",
            content="",
            meta=None,
            name=None,
            tool_call_id=None,
            tool_calls=[{"id": "toolu_abc12345", "name": "search_text", "arguments": {}}],
            tokens=None,
            timestamp=100.0,
            in_context=True,
            summary_of=None,
        )
    ]
    records = build_tool_records(messages, [])

    by_prefix, prefix_error = resolve_tool_record(records, "toolu_abc")
    by_suffix, suffix_error = resolve_tool_record(records, "abc12345")

    assert prefix_error is None
    assert suffix_error is None
    assert by_prefix is not None and by_prefix.tool_call_id == "toolu_abc12345"
    assert by_suffix is not None and by_suffix.tool_call_id == "toolu_abc12345"


def test_format_tool_record_details_includes_ids_status_and_result() -> None:
    messages = [
        MessageRow(
            id=1,
            role="assistant",
            content="",
            meta=None,
            name=None,
            tool_call_id=None,
            tool_calls=[{"id": "call_1", "name": "exec", "arguments": {"program": "echo"}}],
            tokens=None,
            timestamp=100.0,
            in_context=True,
            summary_of=None,
        ),
        MessageRow(
            id=2,
            role="tool",
            content="hello",
            meta=None,
            name="exec",
            tool_call_id="call_1",
            tool_calls=None,
            tokens=None,
            timestamp=101.0,
            in_context=True,
            summary_of=None,
        ),
    ]
    record = build_tool_records(messages, [])[0]

    details = format_tool_record_details(record)

    assert "Tool: exec" in details
    assert "Call ID: call_1" in details
    assert "Visible ID: call_1" in details
    assert "Status: done" in details
    assert '"program": "echo"' in details
    assert "hello" in details
