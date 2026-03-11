"""Non-interactive live trace viewer for persisted NEXUS3 session logs."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from nexus3.cli.trace_palette import TRACE_BODY_STYLES, TRACE_HEADER_STYLES
from nexus3.display import get_console
from nexus3.display.safe_sink import SafeSink
from nexus3.session.storage import MessageRow, SessionStorage
from nexus3.session.trace import (
    ActiveAgentSession,
    read_active_agent_sessions,
    read_active_trace_session,
    read_session_agent_metadata,
    tool_display_id,
)

TRACE_PRESETS = ("execution", "debug")
TRACE_SCOPES = ("active", "subagents")
DEFAULT_MAX_TOOL_LINES = 50
_TRACE_HEADER_STYLES = TRACE_HEADER_STYLES
_TRACE_BODY_STYLES = TRACE_BODY_STYLES


@dataclass(frozen=True)
class ExecutionTraceEntry:
    """A rendered execution trace entry derived from persisted session messages."""

    source_message_id: int
    timestamp: float
    kind: str
    header: str
    body_lines: tuple[str, ...] = ()
    truncation_note: str | None = None


@dataclass(frozen=True)
class TraceSessionBinding:
    """Resolved trace session plus whether default active-follow is enabled."""

    session_dir: Path
    follow_active: bool


@dataclass(frozen=True)
class SubagentTraceBinding:
    """Resolved parent session plus active-follow semantics for subagent scope."""

    parent_session_dir: Path
    parent_agent_id: str
    follow_active: bool
    server_pid: int | None = None


def _resolve_latest_trace_session_dir(base_log_dir: Path) -> Path:
    """Resolve the newest traceable session directory under the selected log root."""
    log_root = base_log_dir.expanduser().resolve()

    session_dbs = sorted(
        (
            path.resolve()
            for path in log_root.rglob("session.db")
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    candidates: list[Path] = []
    for session_db in session_dbs:
        session_dir = session_db.parent
        if session_dir not in candidates:
            candidates.append(session_dir)

    if not candidates:
        raise FileNotFoundError(f"No session.db files found under {base_log_dir}")

    return candidates[0]


def resolve_trace_session_binding(
    base_log_dir: Path,
    target: str | None = None,
) -> TraceSessionBinding:
    """Resolve a trace target and whether follow-active retargeting should run."""
    if target == "latest":
        target = None

    log_root = base_log_dir.expanduser().resolve()

    if target:
        candidate = Path(target).expanduser()
        if candidate.is_file() and candidate.name == "session.db":
            return TraceSessionBinding(session_dir=candidate.parent.resolve(), follow_active=False)
        if candidate.is_dir() and (candidate / "session.db").exists():
            return TraceSessionBinding(session_dir=candidate.resolve(), follow_active=False)

        session_dbs = sorted(
            (
                path.resolve()
                for path in log_root.rglob("session.db")
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        candidates: list[Path] = []
        for session_db in session_dbs:
            session_dir = session_db.parent
            if session_dir not in candidates:
                candidates.append(session_dir)

        if not candidates:
            raise FileNotFoundError(f"No session.db files found under {base_log_dir}")

        matches = [path for path in candidates if path.name.startswith(target)]
        if len(matches) == 1:
            return TraceSessionBinding(session_dir=matches[0], follow_active=False)
        if not matches:
            raise FileNotFoundError(
                f"No session directory matches '{target}' under {base_log_dir}"
            )

        names = ", ".join(path.name for path in matches[:5])
        raise ValueError(f"Ambiguous session target '{target}'. Matches: {names}")

    active_session = read_active_trace_session(log_root)
    if active_session is not None:
        return TraceSessionBinding(
            session_dir=active_session.session_dir,
            follow_active=True,
        )

    return TraceSessionBinding(
        session_dir=_resolve_latest_trace_session_dir(log_root),
        follow_active=True,
    )


def resolve_trace_session_dir(base_log_dir: Path, target: str | None = None) -> Path:
    """Resolve a trace target to a session directory containing `session.db`."""
    return resolve_trace_session_binding(base_log_dir, target).session_dir


def _resolve_session_agent_id(session_dir: Path) -> str:
    """Resolve the owning agent ID for a persisted session directory."""
    agent_id, _ = read_session_agent_metadata(session_dir)
    if agent_id:
        return agent_id
    return session_dir.parent.name


def resolve_subagent_trace_binding(
    base_log_dir: Path,
    target: str | None = None,
) -> SubagentTraceBinding:
    """Resolve the parent session/agent binding for subagent trace scope."""
    if target == "latest":
        target = None

    if target:
        session_dir = resolve_trace_session_dir(base_log_dir, target)
        parent_agent_id = _resolve_session_agent_id(session_dir)
        active_session = read_active_trace_session(base_log_dir)
        server_pid = (
            active_session.server_pid
            if active_session is not None and active_session.session_dir == session_dir.resolve()
            else None
        )
        return SubagentTraceBinding(
            parent_session_dir=session_dir.resolve(),
            parent_agent_id=parent_agent_id,
            follow_active=False,
            server_pid=server_pid,
        )

    active_session = read_active_trace_session(base_log_dir)
    if active_session is not None:
        return SubagentTraceBinding(
            parent_session_dir=active_session.session_dir,
            parent_agent_id=active_session.agent_id,
            follow_active=True,
            server_pid=active_session.server_pid,
        )

    session_dir = _resolve_latest_trace_session_dir(base_log_dir)
    return SubagentTraceBinding(
        parent_session_dir=session_dir,
        parent_agent_id=_resolve_session_agent_id(session_dir),
        follow_active=True,
        server_pid=None,
    )


def _truncate_tool_body(
    lines: tuple[str, ...],
    *,
    max_tool_lines: int,
    label: str,
) -> tuple[tuple[str, ...], str | None]:
    """Apply execution-trace truncation to tool-call/result bodies."""
    if max_tool_lines == 0 or len(lines) <= max_tool_lines:
        return lines, None
    return lines[:max_tool_lines], f"{label} truncated at {max_tool_lines} lines"


def build_execution_entries(
    messages: list[MessageRow],
    *,
    max_tool_lines: int = DEFAULT_MAX_TOOL_LINES,
) -> list[ExecutionTraceEntry]:
    """Build execution-trace entries from persisted session messages."""
    entries: list[ExecutionTraceEntry] = []
    for row in messages:
        timestamp = _format_timestamp(row.timestamp)
        if row.role == "user":
            preview, truncated = _preview_text(row.content)
            entries.append(
                ExecutionTraceEntry(
                    source_message_id=row.id,
                    timestamp=row.timestamp,
                    kind="user",
                    header=f"[{timestamp}] USER",
                    body_lines=(preview,),
                    truncation_note=(
                        "User message preview truncated at 120 chars"
                        if truncated
                        else None
                    ),
                )
            )
            continue

        if row.role == "assistant":
            if row.content.strip():
                preview, truncated = _preview_text(row.content)
                entries.append(
                    ExecutionTraceEntry(
                        source_message_id=row.id,
                        timestamp=row.timestamp,
                        kind="assistant",
                        header=f"[{timestamp}] ASSISTANT",
                        body_lines=(preview,),
                        truncation_note=(
                            "Assistant message preview truncated at 120 chars"
                            if truncated
                            else None
                        ),
                    )
                )
            if row.tool_calls:
                for tool_call in row.tool_calls:
                    args_json = json.dumps(
                        tool_call.get("arguments", {}) or {},
                        indent=2,
                        sort_keys=True,
                        ensure_ascii=False,
                    )
                    args_lines = tuple(args_json.splitlines()) or ("{}",)
                    args_lines, truncation_note = _truncate_tool_body(
                        args_lines,
                        max_tool_lines=max_tool_lines,
                        label="Tool call body",
                    )
                    entries.append(
                        ExecutionTraceEntry(
                            source_message_id=row.id,
                            timestamp=row.timestamp,
                            kind="tool_call",
                            header=(
                                f"[{timestamp}] TOOL CALL "
                                f"[{tool_display_id(tool_call['id'])}] {tool_call['name']}"
                            ),
                            body_lines=args_lines,
                            truncation_note=truncation_note,
                        )
                    )
            continue

        if row.role == "tool" and row.tool_call_id:
            body_lines = tuple(row.content.splitlines()) or ("(empty result)",)
            body_lines, truncation_note = _truncate_tool_body(
                body_lines,
                max_tool_lines=max_tool_lines,
                label="Tool result body",
            )
            name = row.name or "unknown"
            entries.append(
                ExecutionTraceEntry(
                    source_message_id=row.id,
                    timestamp=row.timestamp,
                    kind="tool_result",
                    header=(
                        f"[{timestamp}] TOOL RESULT "
                        f"[{tool_display_id(row.tool_call_id)}] {name}"
                    ),
                    body_lines=body_lines,
                    truncation_note=truncation_note,
                )
            )

    return entries


async def run_trace(
    *,
    log_dir: Path,
    target: str | None,
    preset: str,
    scope: str,
    follow: bool,
    history: int,
    poll_interval: float,
    max_tool_lines: int,
) -> int:
    """Run the trace viewer."""
    if preset not in TRACE_PRESETS:
        raise ValueError(f"Unknown trace preset: {preset}")
    if scope not in TRACE_SCOPES:
        raise ValueError(f"Unknown trace scope: {scope}")

    console = get_console()
    safe_sink = SafeSink(console)

    try:
        active_binding = (
            resolve_trace_session_binding(log_dir, target)
            if scope == "active"
            else None
        )
        subagent_binding = (
            resolve_subagent_trace_binding(log_dir, target)
            if scope == "subagents"
            else None
        )
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Error:[/] {safe_sink.sanitize_print_value(e)}")
        return 1

    if max_tool_lines < 0:
        console.print("[red]Error:[/] --max-tool-lines must be >= 0")
        return 1

    console.print("[bold]NEXUS3 Trace[/]")
    console.print(f"[dim]Preset:[/] {safe_sink.sanitize_print_value(preset)}")
    console.print(f"[dim]Scope:[/] {safe_sink.sanitize_print_value(scope)}")
    if scope == "active":
        assert active_binding is not None
        if active_binding.follow_active:
            console.print(
                "[dim]Session:[/] following active session in selected log root "
                f"(currently {safe_sink.sanitize_print_value(active_binding.session_dir)})"
            )
        else:
            console.print(
                f"[dim]Session:[/] {safe_sink.sanitize_print_value(active_binding.session_dir)}"
            )
    else:
        assert subagent_binding is not None
        if subagent_binding.follow_active:
            console.print(
                "[dim]Parent Session:[/] following active session for subagent scope "
                f"(currently {safe_sink.sanitize_print_value(subagent_binding.parent_session_dir)})"
            )
        else:
            console.print(
                "[dim]Parent Session:[/] "
                f"{safe_sink.sanitize_print_value(subagent_binding.parent_session_dir)}"
            )
        console.print(
            "[dim]Parent Agent:[/] "
            f"{safe_sink.sanitize_print_value(subagent_binding.parent_agent_id)}"
        )
    console.print("")

    try:
        if scope == "active" and preset == "execution":
            assert active_binding is not None
            await _run_execution_trace(
                session_dir=active_binding.session_dir,
                follow=follow,
                history=history,
                poll_interval=poll_interval,
                safe_sink=safe_sink,
                max_tool_lines=max_tool_lines,
                base_log_dir=log_dir,
                follow_active=active_binding.follow_active,
            )
        elif scope == "active":
            assert active_binding is not None
            await _run_debug_trace(
                session_dir=active_binding.session_dir,
                follow=follow,
                history=history,
                poll_interval=poll_interval,
                safe_sink=safe_sink,
                base_log_dir=log_dir,
                follow_active=active_binding.follow_active,
            )
        elif preset == "execution":
            assert subagent_binding is not None
            await _run_subagent_execution_trace(
                binding=subagent_binding,
                follow=follow,
                history=history,
                poll_interval=poll_interval,
                safe_sink=safe_sink,
                max_tool_lines=max_tool_lines,
                base_log_dir=log_dir,
            )
        else:
            assert subagent_binding is not None
            await _run_subagent_debug_trace(
                binding=subagent_binding,
                follow=follow,
                history=history,
                poll_interval=poll_interval,
                safe_sink=safe_sink,
                base_log_dir=log_dir,
            )
    except KeyboardInterrupt:
        console.print("")
        console.print("[dim]Trace stopped.[/]")

    return 0


async def _run_execution_trace(
    *,
    session_dir: Path,
    follow: bool,
    history: int,
    poll_interval: float,
    safe_sink: SafeSink,
    max_tool_lines: int,
    base_log_dir: Path,
    follow_active: bool,
) -> None:
    current_session_dir = session_dir
    storage: SessionStorage | None = None

    try:
        while True:
            if storage is None:
                storage = SessionStorage(current_session_dir / "session.db")
                entries = build_execution_entries(
                    storage.get_messages(in_context_only=False),
                    max_tool_lines=max_tool_lines,
                )
                for entry in entries[-history:]:
                    _print_trace_entry(safe_sink, entry)
                last_message_id = max((entry.source_message_id for entry in entries), default=0)
                if not follow:
                    return

            await asyncio.sleep(poll_interval)
            if follow_active:
                updated_session_dir = _resolve_follow_active_session_dir(
                    base_log_dir=base_log_dir,
                    current_session_dir=current_session_dir,
                )
                if updated_session_dir != current_session_dir:
                    if storage is not None:
                        storage.close()
                        storage = None
                    current_session_dir = updated_session_dir
                    _print_trace_session_switch_notice(safe_sink, current_session_dir)
                    continue

            assert storage is not None
            try:
                messages = storage.get_messages(in_context_only=False)
            except Exception:
                continue

            new_rows = [row for row in messages if row.id > last_message_id]
            if not new_rows:
                continue

            new_entries = build_execution_entries(
                new_rows,
                max_tool_lines=max_tool_lines,
            )
            for entry in new_entries:
                _print_trace_entry(safe_sink, entry)

            last_message_id = max(row.id for row in new_rows)
    finally:
        if storage is not None:
            storage.close()


async def _run_debug_trace(
    *,
    session_dir: Path,
    follow: bool,
    history: int,
    poll_interval: float,
    safe_sink: SafeSink,
    base_log_dir: Path,
    follow_active: bool,
) -> None:
    current_session_dir = session_dir
    verbose_path = current_session_dir / "verbose.md"
    position = _print_debug_trace_snapshot(safe_sink, verbose_path, history)

    if not follow:
        return

    while True:
        await asyncio.sleep(poll_interval)
        if follow_active:
            updated_session_dir = _resolve_follow_active_session_dir(
                base_log_dir=base_log_dir,
                current_session_dir=current_session_dir,
            )
            if updated_session_dir != current_session_dir:
                current_session_dir = updated_session_dir
                verbose_path = current_session_dir / "verbose.md"
                position = 0
                _print_trace_session_switch_notice(safe_sink, current_session_dir)
                position = _print_debug_trace_snapshot(safe_sink, verbose_path, history)
                continue

        if not verbose_path.exists():
            continue

        current_size = verbose_path.stat().st_size
        if current_size < position:
            position = 0
        if current_size == position:
            continue

        with verbose_path.open("r", encoding="utf-8") as f:
            f.seek(position)
            chunk = f.read()
            position = f.tell()

        if chunk:
            safe_sink.write_untrusted(chunk)


def _select_active_subagent_sessions(
    *,
    base_log_dir: Path,
    parent_agent_id: str,
    server_pid: int | None,
) -> list[ActiveAgentSession]:
    """Return active child-agent sessions for a given parent agent."""
    sessions = [
        session
        for session in read_active_agent_sessions(base_log_dir)
        if session.parent_agent_id == parent_agent_id
        and (server_pid is None or session.server_pid == server_pid)
    ]
    sessions.sort(key=lambda session: (session.updated_at, session.agent_id))
    return sessions


def _resolve_follow_active_subagent_binding(
    *,
    base_log_dir: Path,
    current_binding: SubagentTraceBinding,
) -> SubagentTraceBinding:
    """Resolve the current subagent-scope parent binding during follow mode."""
    active_session = read_active_trace_session(base_log_dir)
    if active_session is None:
        return current_binding
    return SubagentTraceBinding(
        parent_session_dir=active_session.session_dir,
        parent_agent_id=active_session.agent_id,
        follow_active=True,
        server_pid=active_session.server_pid,
    )


async def _run_subagent_execution_trace(
    *,
    binding: SubagentTraceBinding,
    follow: bool,
    history: int,
    poll_interval: float,
    safe_sink: SafeSink,
    max_tool_lines: int,
    base_log_dir: Path,
) -> None:
    current_binding = binding
    storages: dict[Path, SessionStorage] = {}
    last_message_ids: dict[Path, int] = {}
    labels: dict[Path, str] = {}
    waiting_notice_printed = False

    try:
        while True:
            sessions = _select_active_subagent_sessions(
                base_log_dir=base_log_dir,
                parent_agent_id=current_binding.parent_agent_id,
                server_pid=current_binding.server_pid,
            )

            current_dirs = {session.session_dir for session in sessions}
            tracked_dirs = set(storages)

            for removed_dir in tracked_dirs - current_dirs:
                label = labels.get(removed_dir, removed_dir.name)
                storages[removed_dir].close()
                del storages[removed_dir]
                last_message_ids.pop(removed_dir, None)
                labels.pop(removed_dir, None)
                _print_subagent_detached_notice(safe_sink, label)

            if not sessions and not waiting_notice_printed:
                _print_subagent_waiting_notice(safe_sink, current_binding.parent_agent_id)
                waiting_notice_printed = True
            if sessions:
                waiting_notice_printed = False

            for session in sessions:
                label = session.agent_id
                labels[session.session_dir] = label
                if session.session_dir not in storages:
                    storage = SessionStorage(session.session_dir / "session.db")
                    storages[session.session_dir] = storage
                    _print_subagent_attached_notice(safe_sink, label, session.session_dir)
                    entries = build_execution_entries(
                        storage.get_messages(in_context_only=False),
                        max_tool_lines=max_tool_lines,
                    )
                    for entry in entries[-history:]:
                        _print_trace_entry(safe_sink, entry, label=label)
                    last_message_ids[session.session_dir] = max(
                        (entry.source_message_id for entry in entries),
                        default=0,
                    )
                else:
                    storage = storages[session.session_dir]

                if follow:
                    try:
                        messages = storage.get_messages(in_context_only=False)
                    except Exception:
                        continue
                    new_rows = [
                        row
                        for row in messages
                        if row.id > last_message_ids.get(session.session_dir, 0)
                    ]
                    if not new_rows:
                        continue
                    new_entries = build_execution_entries(
                        new_rows,
                        max_tool_lines=max_tool_lines,
                    )
                    for entry in new_entries:
                        _print_trace_entry(safe_sink, entry, label=label)
                    last_message_ids[session.session_dir] = max(
                        row.id for row in new_rows
                    )

            if not follow:
                return

            await asyncio.sleep(poll_interval)
            if current_binding.follow_active:
                updated_binding = _resolve_follow_active_subagent_binding(
                    base_log_dir=base_log_dir,
                    current_binding=current_binding,
                )
                if updated_binding != current_binding:
                    for storage in storages.values():
                        storage.close()
                    storages.clear()
                    last_message_ids.clear()
                    labels.clear()
                    waiting_notice_printed = False
                    current_binding = updated_binding
                    _print_subagent_parent_switch_notice(
                        safe_sink,
                        current_binding.parent_agent_id,
                        current_binding.parent_session_dir,
                    )
    finally:
        for storage in storages.values():
            storage.close()


async def _run_subagent_debug_trace(
    *,
    binding: SubagentTraceBinding,
    follow: bool,
    history: int,
    poll_interval: float,
    safe_sink: SafeSink,
    base_log_dir: Path,
) -> None:
    current_binding = binding
    positions: dict[Path, int] = {}
    labels: dict[Path, str] = {}
    waiting_notice_printed = False

    while True:
        sessions = _select_active_subagent_sessions(
            base_log_dir=base_log_dir,
            parent_agent_id=current_binding.parent_agent_id,
            server_pid=current_binding.server_pid,
        )

        current_dirs = {session.session_dir for session in sessions}
        tracked_dirs = set(positions)

        for removed_dir in tracked_dirs - current_dirs:
            label = labels.get(removed_dir, removed_dir.name)
            positions.pop(removed_dir, None)
            labels.pop(removed_dir, None)
            _print_subagent_detached_notice(safe_sink, label)

        if not sessions and not waiting_notice_printed:
            _print_subagent_waiting_notice(safe_sink, current_binding.parent_agent_id)
            waiting_notice_printed = True
        if sessions:
            waiting_notice_printed = False

        for session in sessions:
            label = session.agent_id
            labels[session.session_dir] = label
            verbose_path = session.session_dir / "verbose.md"
            if session.session_dir not in positions:
                _print_subagent_attached_notice(safe_sink, label, session.session_dir)
                positions[session.session_dir] = _print_prefixed_debug_trace_snapshot(
                    safe_sink,
                    verbose_path,
                    history,
                    label,
                )
                continue

            if not follow or not verbose_path.exists():
                continue

            current_size = verbose_path.stat().st_size
            position = positions[session.session_dir]
            if current_size < position:
                position = 0
            if current_size == position:
                positions[session.session_dir] = position
                continue

            with verbose_path.open("r", encoding="utf-8") as f:
                f.seek(position)
                chunk = f.read()
                position = f.tell()

            positions[session.session_dir] = position
            if chunk:
                for line in chunk.splitlines():
                    safe_sink.print_untrusted(f"[{label}] {line}")

        if not follow:
            return

        await asyncio.sleep(poll_interval)
        if current_binding.follow_active:
            updated_binding = _resolve_follow_active_subagent_binding(
                base_log_dir=base_log_dir,
                current_binding=current_binding,
            )
            if updated_binding != current_binding:
                positions.clear()
                labels.clear()
                waiting_notice_printed = False
                current_binding = updated_binding
                _print_subagent_parent_switch_notice(
                    safe_sink,
                    current_binding.parent_agent_id,
                    current_binding.parent_session_dir,
                )


def _print_trace_entry(
    safe_sink: SafeSink,
    entry: ExecutionTraceEntry,
    *,
    label: str | None = None,
) -> None:
    header = f"[{label}] {entry.header}" if label else entry.header
    safe_sink.print_untrusted(header, style=_TRACE_HEADER_STYLES.get(entry.kind, "bold"))
    for line in entry.body_lines:
        safe_sink.print_untrusted(f"  {line}", style=_TRACE_BODY_STYLES.get(entry.kind))
    if entry.truncation_note:
        safe_sink.print_untrusted(f"  {entry.truncation_note}", style="dim")
    safe_sink.print_trusted("")


def _print_trace_session_switch_notice(safe_sink: SafeSink, session_dir: Path) -> None:
    """Print a visible notice when trace retargets to a different active session."""
    safe_sink.print_untrusted(
        f"Switched trace to active session: {session_dir}",
        style="dim",
    )
    safe_sink.print_trusted("")


def _print_subagent_parent_switch_notice(
    safe_sink: SafeSink,
    parent_agent_id: str,
    parent_session_dir: Path,
) -> None:
    """Print a visible notice when subagent trace retargets to a new parent session."""
    safe_sink.print_untrusted(
        f"Switched subagent trace to parent {parent_agent_id}: {parent_session_dir}",
        style="dim",
    )
    safe_sink.print_trusted("")


def _print_subagent_attached_notice(safe_sink: SafeSink, label: str, session_dir: Path) -> None:
    """Print a visible notice when a subagent trace stream is attached."""
    safe_sink.print_untrusted(
        f"Attached subagent trace: {label} ({session_dir})",
        style="dim",
    )
    safe_sink.print_trusted("")


def _print_subagent_detached_notice(safe_sink: SafeSink, label: str) -> None:
    """Print a visible notice when a subagent trace stream disappears."""
    safe_sink.print_untrusted(f"Detached subagent trace: {label}", style="dim")
    safe_sink.print_trusted("")


def _print_subagent_waiting_notice(safe_sink: SafeSink, parent_agent_id: str) -> None:
    """Print a waiting notice when no active subagents are currently running."""
    safe_sink.print_untrusted(
        f"No active subagents for parent agent '{parent_agent_id}' yet.",
        style="dim",
    )
    safe_sink.print_trusted("")


def _print_debug_trace_snapshot(
    safe_sink: SafeSink,
    verbose_path: Path,
    history: int,
) -> int:
    """Print the initial debug-trace snapshot and return the next file offset."""
    if verbose_path.exists():
        lines = verbose_path.read_text(encoding="utf-8").splitlines()
        for line in lines[-history:]:
            safe_sink.print_untrusted(line)
        return verbose_path.stat().st_size

    safe_sink.print_untrusted(
        "verbose.md not present yet. Start the REPL with -v or -V for debug trace output."
    )
    return 0


def _print_prefixed_debug_trace_snapshot(
    safe_sink: SafeSink,
    verbose_path: Path,
    history: int,
    label: str,
) -> int:
    """Print a labeled debug snapshot for one multiplexed subagent stream."""
    if verbose_path.exists():
        lines = verbose_path.read_text(encoding="utf-8").splitlines()
        for line in lines[-history:]:
            safe_sink.print_untrusted(f"[{label}] {line}")
        return verbose_path.stat().st_size

    safe_sink.print_untrusted(
        f"[{label}] verbose.md not present yet. Start the REPL with -v or -V "
        "for debug trace output."
    )
    return 0


def _resolve_follow_active_session_dir(
    *,
    base_log_dir: Path,
    current_session_dir: Path,
) -> Path:
    """Resolve the current active-follow target for a trace log root."""
    active_session = read_active_trace_session(base_log_dir)
    if active_session is not None:
        return active_session.session_dir
    return current_session_dir


def _format_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")


def _preview_text(text: str, max_chars: int = 120) -> tuple[str, bool]:
    collapsed = " ".join(text.split())
    if len(collapsed) <= max_chars:
        return collapsed, False
    return collapsed[: max_chars - 3] + "...", True
