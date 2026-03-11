"""Non-interactive live trace viewer for persisted NEXUS3 session logs."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from nexus3.display import get_console
from nexus3.display.safe_sink import SafeSink
from nexus3.session.storage import MessageRow, SessionStorage
from nexus3.session.trace import tool_display_id

TRACE_PRESETS = ("execution", "debug")
DEFAULT_MAX_TOOL_LINES = 50
_TRACE_HEADER_STYLES = {
    "user": "bold bright_blue",
    "assistant": "bold bright_magenta",
    "tool_call": "bold bright_cyan",
    "tool_result": "bold bright_green",
}
_TRACE_BODY_STYLES = {
    "user": "blue",
    "assistant": "magenta",
    "tool_call": "cyan",
    "tool_result": "green",
}


@dataclass(frozen=True)
class ExecutionTraceEntry:
    """A rendered execution trace entry derived from persisted session messages."""

    source_message_id: int
    timestamp: float
    kind: str
    header: str
    body_lines: tuple[str, ...] = ()
    truncation_note: str | None = None


def resolve_trace_session_dir(base_log_dir: Path, target: str | None = None) -> Path:
    """Resolve a trace target to a session directory containing `session.db`."""
    if target == "latest":
        target = None

    if target:
        candidate = Path(target).expanduser()
        if candidate.is_file() and candidate.name == "session.db":
            return candidate.parent.resolve()
        if candidate.is_dir() and (candidate / "session.db").exists():
            return candidate.resolve()

    session_dbs = sorted(
        (
            path.resolve()
            for path in base_log_dir.expanduser().resolve().rglob("session.db")
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

    if not target:
        return candidates[0]

    matches = [path for path in candidates if path.name.startswith(target)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise FileNotFoundError(
            f"No session directory matches '{target}' under {base_log_dir}"
        )

    names = ", ".join(path.name for path in matches[:5])
    raise ValueError(f"Ambiguous session target '{target}'. Matches: {names}")


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
            entries.append(
                ExecutionTraceEntry(
                    source_message_id=row.id,
                    timestamp=row.timestamp,
                    kind="user",
                    header=f"[{timestamp}] USER",
                    body_lines=(_preview_text(row.content),),
                )
            )
            continue

        if row.role == "assistant":
            if row.content.strip():
                entries.append(
                    ExecutionTraceEntry(
                        source_message_id=row.id,
                        timestamp=row.timestamp,
                        kind="assistant",
                        header=f"[{timestamp}] ASSISTANT",
                        body_lines=(_preview_text(row.content),),
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
    follow: bool,
    history: int,
    poll_interval: float,
    max_tool_lines: int,
) -> int:
    """Run the trace viewer."""
    if preset not in TRACE_PRESETS:
        raise ValueError(f"Unknown trace preset: {preset}")

    console = get_console()
    safe_sink = SafeSink(console)

    try:
        session_dir = resolve_trace_session_dir(log_dir, target)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Error:[/] {safe_sink.sanitize_print_value(e)}")
        return 1

    if max_tool_lines < 0:
        console.print("[red]Error:[/] --max-tool-lines must be >= 0")
        return 1

    console.print("[bold]NEXUS3 Trace[/]")
    console.print(f"[dim]Preset:[/] {safe_sink.sanitize_print_value(preset)}")
    console.print(f"[dim]Session:[/] {safe_sink.sanitize_print_value(session_dir)}")
    console.print("")

    try:
        if preset == "execution":
            await _run_execution_trace(
                session_dir=session_dir,
                follow=follow,
                history=history,
                poll_interval=poll_interval,
                safe_sink=safe_sink,
                max_tool_lines=max_tool_lines,
            )
        else:
            await _run_debug_trace(
                session_dir=session_dir,
                follow=follow,
                history=history,
                poll_interval=poll_interval,
                safe_sink=safe_sink,
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
) -> None:
    storage = SessionStorage(session_dir / "session.db")
    try:
        entries = build_execution_entries(
            storage.get_messages(in_context_only=False),
            max_tool_lines=max_tool_lines,
        )
        for entry in entries[-history:]:
            _print_trace_entry(safe_sink, entry)

        if not follow:
            return

        last_message_id = max((entry.source_message_id for entry in entries), default=0)
        while True:
            await asyncio.sleep(poll_interval)
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
        storage.close()


async def _run_debug_trace(
    *,
    session_dir: Path,
    follow: bool,
    history: int,
    poll_interval: float,
    safe_sink: SafeSink,
) -> None:
    verbose_path = session_dir / "verbose.md"
    position = 0

    if verbose_path.exists():
        lines = verbose_path.read_text(encoding="utf-8").splitlines()
        for line in lines[-history:]:
            safe_sink.print_untrusted(line)
        position = verbose_path.stat().st_size
    else:
        safe_sink.print_untrusted(
            "verbose.md not present yet. Start the REPL with -v or -V for debug trace output."
        )

    if not follow:
        return

    while True:
        await asyncio.sleep(poll_interval)
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


def _print_trace_entry(safe_sink: SafeSink, entry: ExecutionTraceEntry) -> None:
    safe_sink.print_untrusted(entry.header, style=_TRACE_HEADER_STYLES.get(entry.kind, "bold"))
    for line in entry.body_lines:
        safe_sink.print_untrusted(f"  {line}", style=_TRACE_BODY_STYLES.get(entry.kind))
    if entry.truncation_note:
        safe_sink.print_untrusted(f"  {entry.truncation_note}", style="dim")
    safe_sink.print_trusted("")


def _format_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")


def _preview_text(text: str, max_chars: int = 120) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= max_chars:
        return collapsed
    return collapsed[: max_chars - 3] + "..."
