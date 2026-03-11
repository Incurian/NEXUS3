"""Tests for trace-viewer helpers."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

from nexus3.cli.arg_parser import parse_args
from nexus3.cli.trace import build_execution_entries, resolve_trace_session_dir
from nexus3.session.storage import MessageRow


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


def test_build_execution_entries_renders_message_previews_and_full_tool_blocks() -> None:
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

    assert entries[0].lines == (f"[{timestamp_100}] USER: please inspect the repo",)
    assert entries[1].lines[0] == f"[{timestamp_101}] TOOL CALL [abc12345] search_text"
    assert '"path": "README.md"' in "\n".join(entries[1].lines)
    assert entries[2].lines[0] == f"[{timestamp_102}] TOOL RESULT [abc12345] search_text"
    assert entries[2].lines[1:] == ("match line 1", "match line 2")


def test_resolve_trace_session_dir_errors_on_ambiguous_prefix(tmp_path: Path) -> None:
    first = tmp_path / "2026-03-11_repl_one"
    second = tmp_path / "2026-03-11_repl_two"
    first.mkdir()
    second.mkdir()
    (first / "session.db").write_text("", encoding="utf-8")
    (second / "session.db").write_text("", encoding="utf-8")

    with pytest.raises(ValueError):
        resolve_trace_session_dir(tmp_path, "2026-03-11_repl")
