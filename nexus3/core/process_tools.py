"""Cross-platform process inspection and termination helpers."""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from typing import Any, Literal

import psutil  # type: ignore[import-untyped]

from nexus3.core.redaction import redact_secrets
from nexus3.core.text_safety import strip_terminal_escapes

ProcessMatchMode = Literal["exact", "contains", "regex"]

DEFAULT_PROCESS_LIMIT = 50
MAX_PROCESS_LIMIT = 200
DEFAULT_KILL_TIMEOUT_SECONDS = 2.0
MAX_KILL_TIMEOUT_SECONDS = 30.0
MAX_COMMAND_PREVIEW_LENGTH = 300

_PROCESS_ITER_ATTRS = (
    "pid",
    "ppid",
    "name",
    "status",
    "username",
    "create_time",
    "cmdline",
)
_SENSITIVE_FLAG_RE = re.compile(
    r"(?i)(--?(?:api[-_]?key|token|access[-_]?token|secret|password|pwd|authorization)"
    r"(?:[=\s]+))(\"[^\"]*\"|'[^']*'|\S+)"
)


def normalize_process_limit(limit: int | None) -> int:
    """Validate and normalize a process list limit."""
    if limit is None:
        return DEFAULT_PROCESS_LIMIT
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if limit > MAX_PROCESS_LIMIT:
        raise ValueError(f"limit must be <= {MAX_PROCESS_LIMIT}")
    return limit


def normalize_process_offset(offset: int | None) -> int:
    """Validate and normalize a process list offset."""
    if offset is None:
        return 0
    if offset < 0:
        raise ValueError("offset must be >= 0")
    return offset


def normalize_kill_timeout(timeout_seconds: float | None) -> float:
    """Validate and normalize process kill timeout."""
    if timeout_seconds is None:
        return DEFAULT_KILL_TIMEOUT_SECONDS
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be > 0")
    if timeout_seconds > MAX_KILL_TIMEOUT_SECONDS:
        raise ValueError(f"timeout_seconds must be <= {MAX_KILL_TIMEOUT_SECONDS}")
    return timeout_seconds


def format_command_preview(cmdline: list[str] | tuple[str, ...] | None) -> str:
    """Build a redacted command-line preview safe for model/display use."""
    if not cmdline:
        return ""

    raw = " ".join(str(part) for part in cmdline if part)
    if not raw:
        return ""

    redacted = _SENSITIVE_FLAG_RE.sub(r"\1[REDACTED]", raw)
    redacted = redact_secrets(redacted)
    redacted = strip_terminal_escapes(redacted).strip()
    if len(redacted) > MAX_COMMAND_PREVIEW_LENGTH:
        return redacted[: MAX_COMMAND_PREVIEW_LENGTH - 3] + "..."
    return redacted


def matches_process_query(
    *,
    name: str,
    command: str,
    query: str,
    match: ProcessMatchMode,
) -> bool:
    """Check whether a process name/cmdline matches a query."""
    if not query:
        return True

    haystacks = (name, command)
    query_lower = query.casefold()

    if match == "exact":
        return any(query_lower == value.casefold() for value in haystacks if value)
    if match == "contains":
        return any(query_lower in value.casefold() for value in haystacks if value)
    if match == "regex":
        try:
            regex = re.compile(query, re.IGNORECASE)
        except re.error as e:
            raise ValueError(f"Invalid regex pattern: {e}") from e
        return any(regex.search(value) for value in haystacks if value)
    raise ValueError(f"Unsupported match mode: {match}")


def format_process_time(timestamp: float | None) -> str | None:
    """Convert a process create_time timestamp to ISO-8601."""
    if timestamp is None:
        return None
    try:
        return datetime.fromtimestamp(timestamp, tz=UTC).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def build_port_map(*, required: bool = False) -> dict[int, list[int]]:
    """Build a PID -> local ports map best-effort.

    When `required=True`, failures raise ValueError instead of silently
    returning an empty mapping.
    """
    ports_by_pid: dict[int, set[int]] = {}

    try:
        connections = psutil.net_connections(kind="inet")
    except (psutil.AccessDenied, PermissionError, OSError) as e:
        if required:
            raise ValueError(
                "Port-based process lookup is unavailable on this host or "
                "under the current permissions."
            ) from e
        return {}

    for conn in connections:
        pid = conn.pid
        if pid is None:
            continue
        laddr = conn.laddr
        port = getattr(laddr, "port", None)
        if port is None:
            continue
        ports_by_pid.setdefault(pid, set()).add(int(port))

    return {pid: sorted(ports) for pid, ports in ports_by_pid.items()}


def summarize_process_info(
    info: dict[str, Any],
    *,
    ports: list[int] | None = None,
) -> dict[str, Any]:
    """Build a stable process summary from psutil info."""
    cmdline = info.get("cmdline")
    cmdline_parts = cmdline if isinstance(cmdline, (list, tuple)) else None

    summary: dict[str, Any] = {
        "pid": int(info["pid"]),
        "ppid": int(info.get("ppid") or 0),
        "name": str(info.get("name") or ""),
        "status": str(info.get("status") or ""),
        "username": info.get("username"),
        "create_time": format_process_time(_coerce_float(info.get("create_time"))),
        "command_preview": format_command_preview(cmdline_parts),
    }
    if ports:
        summary["ports"] = ports
    return summary


def process_match_text(info: dict[str, Any]) -> tuple[str, str]:
    """Extract raw name/cmdline text for matching."""
    name = str(info.get("name") or "")
    cmdline = info.get("cmdline")
    if isinstance(cmdline, (list, tuple)):
        command = " ".join(str(part) for part in cmdline if part)
    else:
        command = ""
    return name, command


def get_process_filter_view(
    pid: int,
    *,
    include_ports: bool = False,
    port_lookup_required: bool = False,
) -> dict[str, Any]:
    """Return raw process fields used for internal filtering/validation."""
    process = psutil.Process(pid)
    with process.oneshot():
        cmdline = _safe_process_call(process.cmdline)
        cmdline_parts = cmdline if isinstance(cmdline, (list, tuple)) else None
        view: dict[str, Any] = {
            "pid": process.pid,
            "name": _safe_process_call(process.name) or "",
            "username": _safe_process_call(process.username),
            "command": " ".join(str(part) for part in cmdline_parts or [] if part),
        }

    if include_ports:
        port_map = build_port_map(required=port_lookup_required)
        view["ports"] = port_map.get(pid, [])

    return view


def get_process_details(
    pid: int,
    *,
    include_ports: bool = True,
    port_lookup_required: bool = False,
) -> dict[str, Any]:
    """Return detailed information for a single PID."""
    process = psutil.Process(pid)
    with process.oneshot():
        details: dict[str, Any] = {
            "pid": process.pid,
            "ppid": _safe_process_call(process.ppid),
            "name": _safe_process_call(process.name) or "",
            "status": _safe_process_call(process.status) or "",
            "username": _safe_process_call(process.username),
            "create_time": format_process_time(_safe_process_call(process.create_time)),
            "command_preview": format_command_preview(_safe_process_call(process.cmdline)),
            "cwd": _safe_process_call(process.cwd),
            "exe": _safe_process_call(process.exe),
            "memory_rss": _memory_rss(process),
        }

    if include_ports:
        port_map = build_port_map(required=port_lookup_required)
        if pid in port_map:
            details["ports"] = port_map[pid]

    return details


def get_protected_pids() -> set[int]:
    """Return PIDs that should not be terminated by agent tools."""
    protected = {os.getpid()}

    try:
        current = psutil.Process(os.getpid())
    except (psutil.Error, OSError):
        return protected

    try:
        for parent in current.parents():
            if _looks_like_nexus_process(parent):
                protected.add(parent.pid)
    except (psutil.Error, OSError):
        pass

    return protected


def protected_process_reason(pid: int) -> str | None:
    """Return a fail-closed reason if a PID is protected."""
    if pid not in get_protected_pids():
        return None
    return (
        f"Refusing to terminate protected PID {pid}. "
        "NEXUS blocks self-termination and closely related runtime processes."
    )


def protected_termination_reason(pid: int, *, tree: bool) -> str | None:
    """Return a fail-closed reason if a termination request reaches protected PIDs."""
    root_reason = protected_process_reason(pid)
    if root_reason:
        return root_reason

    if not tree:
        return None

    process = psutil.Process(pid)
    protected = get_protected_pids()
    protected_descendants = sorted(
        target.pid
        for target in _collect_termination_targets(process, tree=True)
        if target.pid in protected
    )
    if not protected_descendants:
        return None

    protected_ids = ", ".join(str(target_pid) for target_pid in protected_descendants)
    return (
        f"Refusing to terminate PID {pid} because tree termination would include "
        f"protected PID(s): {protected_ids}. "
        "NEXUS blocks self-termination and closely related runtime processes."
    )


def terminate_pid(
    pid: int,
    *,
    tree: bool,
    force: bool,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Terminate a PID, optionally including its descendants."""
    process = psutil.Process(pid)
    targets = _collect_termination_targets(process, tree=tree)
    immediate_force = force

    if immediate_force:
        for target in targets:
            _safe_terminate_call(target.kill)
        gone, alive = psutil.wait_procs(targets, timeout=timeout_seconds)
        return {
            "pid": pid,
            "tree": tree,
            "force": True,
            "graceful_attempted": False,
            "escalated": False,
            "terminated_pids": sorted(p.pid for p in gone),
            "alive_pids": sorted(p.pid for p in alive),
            "success": not alive,
        }

    for target in targets:
        _safe_terminate_call(target.terminate)

    gone, alive = psutil.wait_procs(targets, timeout=timeout_seconds)
    escalated = False
    if alive:
        escalated = True
        for target in alive:
            _safe_terminate_call(target.kill)
        gone_after_kill, alive = psutil.wait_procs(alive, timeout=timeout_seconds)
        gone.extend(gone_after_kill)

    return {
        "pid": pid,
        "tree": tree,
        "force": False,
        "graceful_attempted": True,
        "escalated": escalated,
        "terminated_pids": sorted({p.pid for p in gone}),
        "alive_pids": sorted(p.pid for p in alive),
        "success": not alive,
    }


def _collect_termination_targets(
    process: psutil.Process,
    *,
    tree: bool,
) -> list[psutil.Process]:
    """Collect processes to terminate in child-first order."""
    targets: list[psutil.Process] = []
    if tree:
        try:
            children = process.children(recursive=True)
        except (psutil.Error, OSError):
            children = []
        # Kill deeper descendants first when possible.
        child_depth = {child.pid: 0 for child in children}
        for child in children:
            try:
                child_depth[child.pid] = len(child.parents())
            except (psutil.Error, OSError):
                child_depth[child.pid] = 0
        targets.extend(
            sorted(
                children,
                key=lambda child: child_depth.get(child.pid, 0),
                reverse=True,
            )
        )
    targets.append(process)
    return targets


def _memory_rss(process: psutil.Process) -> int | None:
    """Return RSS memory in bytes when available."""
    try:
        return int(process.memory_info().rss)
    except (psutil.Error, OSError, AttributeError):
        return None


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _safe_process_call(method: Any) -> Any:
    """Best-effort wrapper for psutil accessors."""
    try:
        if callable(method):
            return method()
        return method
    except (psutil.Error, OSError, RuntimeError):
        return None


def _safe_terminate_call(method: Any) -> None:
    """Best-effort terminate/kill call wrapper."""
    try:
        method()
    except (psutil.NoSuchProcess, psutil.ZombieProcess, OSError):
        return None


def _looks_like_nexus_process(process: psutil.Process) -> bool:
    """Best-effort detection of current NEXUS runtime ancestry."""
    name = (_safe_process_call(process.name) or "").lower()
    cmdline = _safe_process_call(process.cmdline) or []
    cmdline_text = " ".join(str(part).lower() for part in cmdline)
    return "nexus3" in name or "nexus3" in cmdline_text
