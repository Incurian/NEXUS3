"""Tests for trace-viewer helpers."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

from nexus3.cli.arg_parser import parse_args
from nexus3.cli.trace import (
    DEFAULT_MAX_TOOL_LINES,
    _resolve_follow_active_session_dir,
    build_execution_entries,
    resolve_trace_session_binding,
    resolve_trace_session_dir,
)
from nexus3.session.storage import MessageRow
from nexus3.session.trace import write_active_trace_session


def test_resolve_trace_session_dir_uses_latest_when_no_target(tmp_path: Path) -> None:
    older = tmp_path / "older"
    newer = tmp_path / "newer"
    older.mkdir()
    newer.mkdir()
    (older / "session.db").write_text("", encoding="utf-8")
    (newer / "session.db").write_text("", encoding="utf-8")
    os.utime(older / "session.db", (10, 10))
    os.utime(newer / "session.db", (20, 20))

    resolved = resolve_trace_session_dir(tmp_path)

    assert resolved == newer.resolve()


def test_resolve_trace_session_dir_supports_prefix_lookup(tmp_path: Path) -> None:
    target = tmp_path / "2026-03-11_repl_abcd12"
    target.mkdir()
    (target / "session.db").write_text("", encoding="utf-8")

    resolved = resolve_trace_session_dir(tmp_path, "2026-03-11_repl")

    assert resolved == target.resolve()


def test_resolve_trace_session_dir_supports_latest_alias(tmp_path: Path) -> None:
    target = tmp_path / "2026-03-11_repl_abcd12"
    target.mkdir()
    (target / "session.db").write_text("", encoding="utf-8")

    resolved = resolve_trace_session_dir(tmp_path, "latest")

    assert resolved == target.resolve()


def test_resolve_trace_session_binding_prefers_active_pointer_when_target_omitted(
    tmp_path: Path,
) -> None:
    newest = tmp_path / "newest"
    active_parent = tmp_path / "main"
    active = active_parent / "2026-03-11_agent_active"
    newest.mkdir()
    active.mkdir(parents=True)
    (newest / "session.db").write_text("", encoding="utf-8")
    (active / "session.db").write_text("", encoding="utf-8")
    os.utime(newest / "session.db", (20, 20))

    write_active_trace_session(
        base_log_dir=tmp_path,
        session_dir=active,
        agent_id="main",
        server_instance_id="srv-1",
        server_pid=1234,
    )

    binding = resolve_trace_session_binding(tmp_path)

    assert binding.session_dir == active.resolve()
    assert binding.follow_active is True


def test_parse_args_supports_trace_latest_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["nexus3", "trace", "--latest", "--preset", "debug"],
    )

    args = parse_args()

    assert args.command == "trace"
    assert args.latest is True
    assert args.target is None
    assert args.preset == "debug"


def test_parse_args_supports_trace_max_tool_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["nexus3", "trace", "--max-tool-lines", "25"],
    )

    args = parse_args()

    assert args.command == "trace"
    assert args.max_tool_lines == 25


def test_resolve_follow_active_session_dir_keeps_current_without_pointer(tmp_path: Path) -> None:
    current = tmp_path / "current"
    current.mkdir()
    (current / "session.db").write_text("", encoding="utf-8")

    resolved = _resolve_follow_active_session_dir(
        base_log_dir=tmp_path,
        current_session_dir=current.resolve(),
    )

    assert resolved == current.resolve()


def test_resolve_follow_active_session_dir_switches_when_pointer_changes(tmp_path: Path) -> None:
    current = tmp_path / "current"
    active_parent = tmp_path / "main"
    active = active_parent / "2026-03-11_agent_active"
    current.mkdir()
    active.mkdir(parents=True)
    (current / "session.db").write_text("", encoding="utf-8")
    (active / "session.db").write_text("", encoding="utf-8")

    write_active_trace_session(
        base_log_dir=tmp_path,
        session_dir=active,
        agent_id="main",
        server_instance_id="srv-1",
        server_pid=1234,
    )

    resolved = _resolve_follow_active_session_dir(
        base_log_dir=tmp_path,
        current_session_dir=current.resolve(),
    )

    assert resolved == active.resolve()


def test_build_execution_entries_renders_typed_message_previews_and_tool_blocks() -> None:
    messages = [
        MessageRow(
            id=1,
            role="user",
            content="please inspect the repo",
            meta=None,
            name=None,
            tool_call_id=None,
            tool_calls=None,
            tokens=None,
            timestamp=100.0,
            in_context=True,
            summary_of=None,
        ),
        MessageRow(
            id=2,
            role="assistant",
            content="",
            meta=None,
            name=None,
            tool_call_id=None,
            tool_calls=[
                {
                    "id": "toolu_abc12345",
                    "name": "search_text",
                    "arguments": {"path": "README.md"},
                }
            ],
            tokens=None,
            timestamp=101.0,
            in_context=True,
            summary_of=None,
        ),
        MessageRow(
            id=3,
            role="tool",
            content="match line 1\nmatch line 2",
            meta=None,
            name="search_text",
            tool_call_id="toolu_abc12345",
            tool_calls=None,
            tokens=None,
            timestamp=102.0,
            in_context=True,
            summary_of=None,
        ),
    ]

    entries = build_execution_entries(messages)

    timestamp_100 = datetime.fromtimestamp(100.0).strftime("%H:%M:%S")
    timestamp_101 = datetime.fromtimestamp(101.0).strftime("%H:%M:%S")
    timestamp_102 = datetime.fromtimestamp(102.0).strftime("%H:%M:%S")

    assert entries[0].kind == "user"
    assert entries[0].header == f"[{timestamp_100}] USER"
    assert entries[0].body_lines == ("please inspect the repo",)
    assert entries[1].kind == "tool_call"
    assert entries[1].header == f"[{timestamp_101}] TOOL CALL [abc12345] search_text"
    assert '"path": "README.md"' in "\n".join(entries[1].body_lines)
    assert entries[2].kind == "tool_result"
    assert entries[2].header == f"[{timestamp_102}] TOOL RESULT [abc12345] search_text"
    assert entries[2].body_lines == ("match line 1", "match line 2")
    assert entries[2].truncation_note is None


def test_build_execution_entries_truncates_tool_result_bodies_by_default() -> None:
    tool_output = "\n".join(f"line {i}" for i in range(DEFAULT_MAX_TOOL_LINES + 5))
    messages = [
        MessageRow(
            id=1,
            role="tool",
            content=tool_output,
            meta=None,
            name="search_text",
            tool_call_id="toolu_abc12345",
            tool_calls=None,
            tokens=None,
            timestamp=102.0,
            in_context=True,
            summary_of=None,
        ),
    ]

    entries = build_execution_entries(messages)

    assert len(entries[0].body_lines) == DEFAULT_MAX_TOOL_LINES
    assert entries[0].truncation_note == (
        f"Tool result body truncated at {DEFAULT_MAX_TOOL_LINES} lines"
    )


def test_build_execution_entries_supports_unlimited_tool_bodies() -> None:
    tool_output = "\n".join(f"line {i}" for i in range(DEFAULT_MAX_TOOL_LINES + 5))
    messages = [
        MessageRow(
            id=1,
            role="tool",
            content=tool_output,
            meta=None,
            name="search_text",
            tool_call_id="toolu_abc12345",
            tool_calls=None,
            tokens=None,
            timestamp=102.0,
            in_context=True,
            summary_of=None,
        ),
    ]

    entries = build_execution_entries(messages, max_tool_lines=0)

    assert len(entries[0].body_lines) == DEFAULT_MAX_TOOL_LINES + 5
    assert entries[0].truncation_note is None


def test_build_execution_entries_reports_user_and_assistant_preview_truncation() -> None:
    long_text = "word " * 40
    messages = [
        MessageRow(
            id=1,
            role="user",
            content=long_text,
            meta=None,
            name=None,
            tool_call_id=None,
            tool_calls=None,
            tokens=None,
            timestamp=100.0,
            in_context=True,
            summary_of=None,
        ),
        MessageRow(
            id=2,
            role="assistant",
            content=long_text,
            meta=None,
            name=None,
            tool_call_id=None,
            tool_calls=None,
            tokens=None,
            timestamp=101.0,
            in_context=True,
            summary_of=None,
        ),
    ]

    entries = build_execution_entries(messages)

    assert entries[0].body_lines[0].endswith("...")
    assert entries[0].truncation_note == "User message preview truncated at 120 chars"
    assert entries[1].body_lines[0].endswith("...")
    assert entries[1].truncation_note == (
        "Assistant message preview truncated at 120 chars"
    )


def test_resolve_trace_session_dir_errors_on_ambiguous_prefix(tmp_path: Path) -> None:
    first = tmp_path / "2026-03-11_repl_one"
    second = tmp_path / "2026-03-11_repl_two"
    first.mkdir()
    second.mkdir()
    (first / "session.db").write_text("", encoding="utf-8")
    (second / "session.db").write_text("", encoding="utf-8")

    with pytest.raises(ValueError):
        resolve_trace_session_dir(tmp_path, "2026-03-11_repl")
