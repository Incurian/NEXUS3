"""Tests for persisted session trace helpers."""

from __future__ import annotations

from pathlib import Path

from nexus3.session.storage import EventRow, MessageRow, SessionStorage
from nexus3.session.trace import (
    active_agent_sessions_path,
    active_trace_session_path,
    build_tool_records,
    clear_active_trace_session,
    format_tool_record_details,
    read_active_agent_sessions,
    read_active_trace_session,
    read_session_agent_metadata,
    remove_active_agent_session,
    resolve_tool_record,
    tool_display_id,
    write_active_agent_session,
    write_active_trace_session,
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


def test_active_trace_session_round_trips_and_clears_by_owner(tmp_path: Path) -> None:
    base_log_dir = tmp_path / "logs"
    session_dir = base_log_dir / "main" / "2026-03-11_agent_abc123"
    session_dir.mkdir(parents=True)
    (session_dir / "session.db").write_text("", encoding="utf-8")

    written = write_active_trace_session(
        base_log_dir=base_log_dir,
        session_dir=session_dir,
        agent_id="main",
        server_instance_id="srv-1",
        server_pid=1234,
    )
    loaded = read_active_trace_session(base_log_dir)

    assert written.session_dir == session_dir.resolve()
    assert loaded is not None
    assert loaded.agent_id == "main"
    assert loaded.server_instance_id == "srv-1"
    assert loaded.session_dir == session_dir.resolve()

    assert (
        clear_active_trace_session(
            base_log_dir=base_log_dir,
            server_instance_id="other",
        )
        is False
    )
    assert active_trace_session_path(base_log_dir).exists()
    assert (
        clear_active_trace_session(
            base_log_dir=base_log_dir,
            server_instance_id="srv-1",
        )
        is True
    )
    assert not active_trace_session_path(base_log_dir).exists()


def test_read_active_trace_session_ignores_malformed_or_outside_pointer(tmp_path: Path) -> None:
    base_log_dir = tmp_path / "logs"
    base_log_dir.mkdir()
    pointer_path = active_trace_session_path(base_log_dir)

    pointer_path.write_text("{not json", encoding="utf-8")
    assert read_active_trace_session(base_log_dir) is None

    pointer_path.write_text(
        (
            '{"session_id":"x","session_dir":"'
            + str((tmp_path / "outside").resolve())
            + '","agent_id":"main","server_pid":1234,'
            '"server_instance_id":"srv-1","updated_at":1.0}'
        ),
        encoding="utf-8",
    )
    assert read_active_trace_session(base_log_dir) is None


def test_active_agent_session_registry_round_trips_and_removes(tmp_path: Path) -> None:
    base_log_dir = tmp_path / "logs"
    first = base_log_dir / "worker-1" / "2026-03-11_agent_a"
    second = base_log_dir / "worker-2" / "2026-03-11_agent_b"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    (first / "session.db").write_text("", encoding="utf-8")
    (second / "session.db").write_text("", encoding="utf-8")

    write_active_agent_session(
        base_log_dir=base_log_dir,
        session_dir=first,
        agent_id="worker-1",
        parent_agent_id="main",
        server_pid=1111,
    )
    write_active_agent_session(
        base_log_dir=base_log_dir,
        session_dir=second,
        agent_id="worker-2",
        parent_agent_id="main",
        server_pid=1111,
    )

    loaded = read_active_agent_sessions(base_log_dir)

    assert [session.agent_id for session in loaded] == ["worker-1", "worker-2"]
    assert loaded[0].parent_agent_id == "main"
    assert loaded[1].server_pid == 1111

    assert remove_active_agent_session(base_log_dir=base_log_dir, session_dir=first) is True
    remaining = read_active_agent_sessions(base_log_dir)
    assert [session.agent_id for session in remaining] == ["worker-2"]
    assert remove_active_agent_session(base_log_dir=base_log_dir, session_dir=first) is False

    assert remove_active_agent_session(base_log_dir=base_log_dir, session_dir=second) is True
    assert not active_agent_sessions_path(base_log_dir).exists()


def test_read_session_agent_metadata_returns_persisted_agent_identity(tmp_path: Path) -> None:
    session_dir = tmp_path / "worker-1" / "2026-03-11_agent_a"
    session_dir.mkdir(parents=True)
    storage = SessionStorage(session_dir / "session.db")
    try:
        storage.set_metadata("agent_id", "worker-1")
        storage.set_metadata("parent_agent_id", "main")
    finally:
        storage.close()

    agent_id, parent_agent_id = read_session_agent_metadata(session_dir)

    assert agent_id == "worker-1"
    assert parent_agent_id == "main"
