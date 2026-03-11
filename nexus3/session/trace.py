"""Helpers for persisted tool records and trace-session coordination."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import time
from typing import Any, cast

from nexus3.core.secure_io import secure_mkdir, secure_write_atomic
from nexus3.session.storage import EventRow, MessageRow, SessionStorage

TOOL_ID_DISPLAY_WIDTH = 8
ACTIVE_TRACE_SESSION_FILENAME = ".active-session.json"
ACTIVE_AGENT_SESSIONS_FILENAME = ".active-agent-sessions.json"


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


@dataclass(frozen=True)
class ActiveTraceSession:
    """The current REPL-selected session published in a shared log root."""

    session_id: str
    session_dir: Path
    agent_id: str
    server_pid: int
    server_instance_id: str
    updated_at: float

    def to_payload(self) -> dict[str, object]:
        """Convert to JSON payload for the shared active-session pointer file."""
        return {
            "version": 1,
            "session_id": self.session_id,
            "session_dir": str(self.session_dir),
            "agent_id": self.agent_id,
            "server_pid": self.server_pid,
            "server_instance_id": self.server_instance_id,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, object],
        *,
        base_log_dir: Path,
    ) -> ActiveTraceSession | None:
        """Validate and construct an active-session pointer payload."""
        try:
            session_id_value = payload["session_id"]
            session_dir_value = payload["session_dir"]
            agent_id_value = payload["agent_id"]
            server_pid_value = payload["server_pid"]
            server_instance_id_value = payload["server_instance_id"]
            updated_at_value = payload["updated_at"]
        except KeyError:
            return None

        if not isinstance(session_id_value, str):
            return None
        if not isinstance(session_dir_value, str):
            return None
        if not isinstance(agent_id_value, str):
            return None
        if not isinstance(server_instance_id_value, str):
            return None
        if not isinstance(server_pid_value, int):
            return None
        if not isinstance(updated_at_value, int | float):
            return None

        session_id = session_id_value
        session_dir = Path(session_dir_value).expanduser().resolve()
        agent_id = agent_id_value
        server_pid = server_pid_value
        server_instance_id = server_instance_id_value
        updated_at = float(updated_at_value)

        log_root = base_log_dir.expanduser().resolve()
        try:
            if not session_dir.is_relative_to(log_root):
                return None
        except ValueError:
            return None

        if not session_dir.is_dir() or not (session_dir / "session.db").exists():
            return None

        if not session_id or not agent_id or not server_instance_id or server_pid <= 0:
            return None

        return cls(
            session_id=session_id,
            session_dir=session_dir,
            agent_id=agent_id,
            server_pid=server_pid,
            server_instance_id=server_instance_id,
            updated_at=updated_at,
        )


@dataclass(frozen=True)
class ActiveAgentSession:
    """A live pool agent session registered in a shared log root."""

    agent_id: str
    session_id: str
    session_dir: Path
    parent_agent_id: str | None
    server_pid: int
    updated_at: float

    def to_payload(self) -> dict[str, object]:
        """Convert to JSON payload for the shared active-agent registry."""
        return {
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "session_dir": str(self.session_dir),
            "parent_agent_id": self.parent_agent_id,
            "server_pid": self.server_pid,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, object],
        *,
        base_log_dir: Path,
    ) -> ActiveAgentSession | None:
        """Validate and construct an active-agent registry entry."""
        try:
            agent_id_value = payload["agent_id"]
            session_id_value = payload["session_id"]
            session_dir_value = payload["session_dir"]
            parent_agent_id_value = payload.get("parent_agent_id")
            server_pid_value = payload["server_pid"]
            updated_at_value = payload["updated_at"]
        except KeyError:
            return None

        if not isinstance(agent_id_value, str):
            return None
        if not isinstance(session_id_value, str):
            return None
        if not isinstance(session_dir_value, str):
            return None
        if parent_agent_id_value is not None and not isinstance(parent_agent_id_value, str):
            return None
        if not isinstance(server_pid_value, int):
            return None
        if not isinstance(updated_at_value, int | float):
            return None

        session_dir = Path(session_dir_value).expanduser().resolve()
        log_root = base_log_dir.expanduser().resolve()
        try:
            if not session_dir.is_relative_to(log_root):
                return None
        except ValueError:
            return None

        if not session_dir.is_dir() or not (session_dir / "session.db").exists():
            return None

        if not agent_id_value or not session_id_value or server_pid_value <= 0:
            return None

        return cls(
            agent_id=agent_id_value,
            session_id=session_id_value,
            session_dir=session_dir,
            parent_agent_id=parent_agent_id_value,
            server_pid=server_pid_value,
            updated_at=float(updated_at_value),
        )


def active_trace_session_path(base_log_dir: Path) -> Path:
    """Return the shared active-session pointer path for a log root."""
    return base_log_dir.expanduser().resolve() / ACTIVE_TRACE_SESSION_FILENAME


def active_agent_sessions_path(base_log_dir: Path) -> Path:
    """Return the shared active-agent registry path for a log root."""
    return base_log_dir.expanduser().resolve() / ACTIVE_AGENT_SESSIONS_FILENAME


def write_active_trace_session(
    *,
    base_log_dir: Path,
    session_dir: Path,
    agent_id: str,
    server_instance_id: str,
    server_pid: int,
) -> ActiveTraceSession:
    """Write the shared active-session pointer for the current REPL session."""
    log_root = base_log_dir.expanduser().resolve()
    secure_mkdir(log_root)

    active_session = ActiveTraceSession(
        session_id=session_dir.resolve().name,
        session_dir=session_dir.resolve(),
        agent_id=agent_id,
        server_pid=server_pid,
        server_instance_id=server_instance_id,
        updated_at=time(),
    )

    pointer_path = active_trace_session_path(log_root)
    secure_write_atomic(
        pointer_path,
        json.dumps(active_session.to_payload(), sort_keys=True, ensure_ascii=False),
    )
    return active_session


def read_active_trace_session(base_log_dir: Path) -> ActiveTraceSession | None:
    """Read the shared active-session pointer for a log root."""
    pointer_path = active_trace_session_path(base_log_dir)
    if not pointer_path.exists():
        return None

    try:
        raw = pointer_path.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None

    return ActiveTraceSession.from_payload(payload, base_log_dir=base_log_dir)


def clear_active_trace_session(
    *,
    base_log_dir: Path,
    server_instance_id: str | None = None,
) -> bool:
    """Clear the shared active-session pointer if it exists and ownership matches."""
    pointer_path = active_trace_session_path(base_log_dir)
    if not pointer_path.exists():
        return False

    if server_instance_id is not None:
        active_session = read_active_trace_session(base_log_dir)
        if active_session is None:
            try:
                pointer_path.unlink()
            except FileNotFoundError:
                return False
            return True
        if active_session.server_instance_id != server_instance_id:
            return False

    try:
        pointer_path.unlink()
        return True
    except FileNotFoundError:
        return False


def read_active_agent_sessions(base_log_dir: Path) -> list[ActiveAgentSession]:
    """Read the shared active-agent session registry for a log root."""
    registry_path = active_agent_sessions_path(base_log_dir)
    if not registry_path.exists():
        return []

    try:
        raw = registry_path.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(payload, list):
        return []

    sessions: list[ActiveAgentSession] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        session = ActiveAgentSession.from_payload(item, base_log_dir=base_log_dir)
        if session is not None:
            sessions.append(session)
    return sessions


def write_active_agent_session(
    *,
    base_log_dir: Path,
    session_dir: Path,
    agent_id: str,
    parent_agent_id: str | None,
    server_pid: int,
) -> ActiveAgentSession:
    """Register or refresh a live agent session in the shared log-root registry."""
    log_root = base_log_dir.expanduser().resolve()
    secure_mkdir(log_root)

    active_session = ActiveAgentSession(
        agent_id=agent_id,
        session_id=session_dir.resolve().name,
        session_dir=session_dir.resolve(),
        parent_agent_id=parent_agent_id,
        server_pid=server_pid,
        updated_at=time(),
    )

    existing = read_active_agent_sessions(log_root)
    updated = [
        session
        for session in existing
        if session.session_dir != active_session.session_dir
    ]
    updated.append(active_session)
    updated.sort(key=lambda session: session.updated_at)

    secure_write_atomic(
        active_agent_sessions_path(log_root),
        json.dumps(
            [session.to_payload() for session in updated],
            sort_keys=True,
            ensure_ascii=False,
        ),
    )
    return active_session


def remove_active_agent_session(
    *,
    base_log_dir: Path,
    session_dir: Path,
) -> bool:
    """Remove a live agent session from the shared active-agent registry."""
    log_root = base_log_dir.expanduser().resolve()
    registry_path = active_agent_sessions_path(log_root)
    if not registry_path.exists():
        return False

    existing = read_active_agent_sessions(log_root)
    updated = [
        session
        for session in existing
        if session.session_dir != session_dir.expanduser().resolve()
    ]

    if len(updated) == len(existing):
        return False

    if updated:
        secure_write_atomic(
            registry_path,
            json.dumps(
                [session.to_payload() for session in updated],
                sort_keys=True,
                ensure_ascii=False,
            ),
        )
    else:
        registry_path.unlink(missing_ok=True)
    return True


def read_session_agent_metadata(session_dir: Path) -> tuple[str | None, str | None]:
    """Read persisted agent identity metadata from a session directory."""
    session_db = session_dir / "session.db"
    if not session_db.exists():
        return None, None

    storage = SessionStorage(session_db)
    try:
        agent_id = storage.get_metadata("agent_id")
        parent_agent_id = storage.get_metadata("parent_agent_id")
        return agent_id, parent_agent_id
    finally:
        storage.close()


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
