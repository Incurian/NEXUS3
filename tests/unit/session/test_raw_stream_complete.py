"""Tests for raw log stream_complete summary writing.

Verifies:
- RawWriter.write_stream_complete() writes correct JSONL entry
- RawLogCallbackAdapter forwards on_stream_complete()
- LogMultiplexer forwards on_stream_complete()
"""

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from nexus3.session.logging import RawLogCallbackAdapter
from nexus3.session.markdown import RawWriter


class TestRawWriterStreamComplete:
    """RawWriter writes stream_complete entries to raw.jsonl."""

    @pytest.fixture
    def raw_writer(self, tmp_path: Path) -> RawWriter:
        return RawWriter(tmp_path)

    def test_writes_stream_complete_entry(self, raw_writer: RawWriter) -> None:
        """write_stream_complete() writes a type=stream_complete entry."""
        summary = {
            "http_status": 200,
            "event_count": 5,
            "content_length": 42,
            "tool_call_count": 0,
            "received_done": True,
            "finish_reason": "stop",
            "duration_ms": 150,
        }
        raw_writer.write_stream_complete(summary, timestamp=1000.0)

        lines = raw_writer.raw_path.read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["type"] == "stream_complete"
        assert entry["timestamp"] == 1000.0
        assert entry["http_status"] == 200
        assert entry["event_count"] == 5
        assert entry["finish_reason"] == "stop"
        assert entry["duration_ms"] == 150

    def test_auto_timestamp(self, raw_writer: RawWriter) -> None:
        """Timestamp auto-generated if not provided."""
        raw_writer.write_stream_complete({"event_count": 0})
        entry = json.loads(raw_writer.raw_path.read_text().strip())
        assert "timestamp" in entry
        assert isinstance(entry["timestamp"], float)


class TestRawLogCallbackAdapterStreamComplete:
    """RawLogCallbackAdapter forwards on_stream_complete()."""

    def test_forwards_to_session_logger(self) -> None:
        """on_stream_complete() calls logger.log_raw_stream_complete()."""
        mock_logger = MagicMock()
        adapter = RawLogCallbackAdapter(mock_logger)
        summary = {"event_count": 3, "duration_ms": 100}
        adapter.on_stream_complete(summary)
        mock_logger.log_raw_stream_complete.assert_called_once_with(summary)


class TestLogMultiplexerStreamComplete:
    """LogMultiplexer forwards on_stream_complete() to current agent callback."""

    def test_forwards_to_current_callback(self) -> None:
        """on_stream_complete() is forwarded to the current agent's callback."""
        from nexus3.rpc.log_multiplexer import LogMultiplexer

        multiplexer = LogMultiplexer()
        callback = MagicMock()
        multiplexer.register("agent-1", callback)

        summary = {"event_count": 5}
        with multiplexer.agent_context("agent-1"):
            multiplexer.on_stream_complete(summary)
        callback.on_stream_complete.assert_called_once_with(summary)

    def test_no_callback_no_error(self) -> None:
        """on_stream_complete() with no current callback doesn't error."""
        from nexus3.rpc.log_multiplexer import LogMultiplexer

        multiplexer = LogMultiplexer()
        # Should not raise
        multiplexer.on_stream_complete({"event_count": 0})
