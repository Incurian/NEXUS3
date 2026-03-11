"""Built-in tools for read-only host process discovery and inspection."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

import psutil  # type: ignore[import-untyped]

from nexus3.core.process_tools import (
    ProcessMatchMode,
    build_port_map,
    get_process_details,
    get_process_filter_view,
    matches_process_query,
    normalize_process_limit,
    normalize_process_offset,
    process_match_text,
    summarize_process_info,
)
from nexus3.core.types import ToolResult
from nexus3.skill.base import base_skill_factory

if TYPE_CHECKING:
    from nexus3.skill.services import ServiceContainer


_PROCESS_ATTRS = (
    "pid",
    "ppid",
    "name",
    "status",
    "username",
    "create_time",
    "cmdline",
)


def _normalize_port_filter(port: int | None) -> int | None:
    """Normalize optional port filters.

    `port=0` is treated as omitted to absorb common placeholder misuse from
    model-generated tool calls. Negative values still fail closed.
    """
    if port is None or port == 0:
        return None
    if port < 0:
        raise ValueError("port must be >= 0")
    return port


def _matches_filters(
    info: dict[str, Any],
    *,
    query: str,
    match: ProcessMatchMode,
    user: str,
    port: int | None,
    port_map: dict[int, list[int]],
) -> bool:
    """Check whether a process info dict matches the requested filters."""
    process_pid = int(info["pid"])

    if user:
        username = str(info.get("username") or "")
        if username.casefold() != user.casefold():
            return False

    if port is not None and port not in port_map.get(process_pid, []):
        return False

    if query:
        name, command = process_match_text(info)
        if not matches_process_query(name=name, command=command, query=query, match=match):
            return False

    return True


def _build_port_map(port: int | None) -> dict[int, list[int]]:
    """Build a port map only when port-based filtering is actually requested."""
    return build_port_map(required=True) if port is not None else {}


def _list_processes_sync(
    *,
    query: str,
    match: ProcessMatchMode,
    user: str,
    port: int | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    """Return paginated process summaries."""
    port_map = _build_port_map(port)
    items: list[dict[str, Any]] = []

    for proc in psutil.process_iter(attrs=list(_PROCESS_ATTRS)):
        info = proc.info
        if not _matches_filters(
            info,
            query=query,
            match=match,
            user=user,
            port=port,
            port_map=port_map,
        ):
            continue

        ports = port_map.get(int(info["pid"])) if port_map else None
        items.append(summarize_process_info(info, ports=ports))

    items.sort(key=lambda item: int(item["pid"]))
    total = len(items)
    page = items[offset : offset + limit]
    next_offset = offset + len(page) if offset + len(page) < total else None

    return {
        "count": len(page),
        "total": total,
        "offset": offset,
        "limit": limit,
        "truncated": next_offset is not None,
        "next_offset": next_offset,
        "items": page,
    }


def _get_process_sync(
    *,
    pid: int | None,
    query: str,
    match: ProcessMatchMode,
    user: str,
    port: int | None,
) -> dict[str, Any]:
    """Resolve and return a single detailed process record."""
    if pid is not None:
        filter_view = get_process_filter_view(
            pid,
            include_ports=port is not None,
            port_lookup_required=port is not None,
        )
        details = get_process_details(
            pid,
            include_ports=True,
            port_lookup_required=port is not None,
        )
        _validate_detail_filters(
            details,
            query=query,
            match=match,
            user=user,
            port=port,
            match_name=str(filter_view.get("name") or ""),
            match_command=str(filter_view.get("command") or ""),
            match_ports=list(filter_view.get("ports", [])),
        )
        return {"process": details}

    if not query:
        raise ValueError("get_process requires pid or query")

    port_map = _build_port_map(port)
    matches: list[dict[str, Any]] = []
    for proc in psutil.process_iter(attrs=list(_PROCESS_ATTRS)):
        info = proc.info
        if not _matches_filters(
            info,
            query=query,
            match=match,
            user=user,
            port=port,
            port_map=port_map,
        ):
            continue
        matches.append(summarize_process_info(info, ports=port_map.get(int(info["pid"]))))

    matches.sort(key=lambda item: int(item["pid"]))
    if not matches:
        raise ValueError(f"No running process matched query: {query!r}")
    if len(matches) > 1:
        candidates = ", ".join(
            f"{item['pid']}:{item['name'] or item['command_preview'] or '<unknown>'}"
            for item in matches[:10]
        )
        raise ValueError(
            "Multiple processes matched query; retry with an explicit pid. "
            f"Candidates: {candidates}"
        )

    return {"process": get_process_details(int(matches[0]["pid"]))}


def _validate_detail_filters(
    details: dict[str, Any],
    *,
    query: str,
    match: ProcessMatchMode,
    user: str,
    port: int | None,
    match_name: str | None = None,
    match_command: str | None = None,
    match_ports: list[int] | None = None,
) -> None:
    """Apply optional query/user/port filters to an exact-PID detail result."""
    if user:
        username = str(details.get("username") or "")
        if username.casefold() != user.casefold():
            raise ValueError(f"PID {details['pid']} does not belong to user {user!r}")
    if port is not None:
        ports = match_ports if match_ports is not None else details.get("ports", [])
        if not isinstance(ports, list) or port not in ports:
            raise ValueError(f"PID {details['pid']} is not associated with port {port}")
    if query:
        name = match_name if match_name is not None else str(details.get("name") or "")
        command = (
            match_command
            if match_command is not None
            else str(details.get("command_preview") or "")
        )
        if not matches_process_query(name=name, command=command, query=query, match=match):
            raise ValueError(f"PID {details['pid']} does not match query {query!r}")


@base_skill_factory
class ListProcessesSkill:
    """List running host processes without relying on shell commands."""

    def __init__(self, services: ServiceContainer | None = None) -> None:
        self._services = services

    @property
    def name(self) -> str:
        return "list_processes"

    @property
    def description(self) -> str:
        return "List running processes by query, user, or port"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Process name or command-line query to match",
                },
                "match": {
                    "type": "string",
                    "enum": ["exact", "contains", "regex"],
                    "description": "How to interpret `query` (default: contains)",
                },
                "user": {
                    "type": "string",
                    "description": "Exact username filter",
                },
                "port": {
                    "type": "integer",
                    "description": "Optional local TCP/UDP port filter; `0` is treated as omitted",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 50)",
                },
                "offset": {
                    "type": "integer",
                    "description": "Best-effort pagination offset (default: 0)",
                },
            },
            "additionalProperties": False,
        }

    async def execute(
        self,
        query: str = "",
        match: ProcessMatchMode = "contains",
        user: str = "",
        port: int | None = None,
        limit: int | None = None,
        offset: int | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        try:
            normalized_limit = normalize_process_limit(limit)
            normalized_offset = normalize_process_offset(offset)
            normalized_port = _normalize_port_filter(port)

            result = await asyncio.to_thread(
                _list_processes_sync,
                query=query.strip(),
                match=match,
                user=user.strip(),
                port=normalized_port,
                limit=normalized_limit,
                offset=normalized_offset,
            )
            return ToolResult(output=json.dumps(result, indent=2))
        except ValueError as e:
            return ToolResult(error=str(e))
        except Exception as e:
            return ToolResult(error=f"Process lookup failed: {e}")


@base_skill_factory
class GetProcessSkill:
    """Inspect one host process by PID or a unique query match."""

    def __init__(self, services: ServiceContainer | None = None) -> None:
        self._services = services

    @property
    def name(self) -> str:
        return "get_process"

    @property
    def description(self) -> str:
        return "Inspect one running process by pid or a unique query match"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pid": {
                    "type": "integer",
                    "description": "Exact PID to inspect (> 0 only)",
                },
                "query": {
                    "type": "string",
                    "description": "Process name or command-line query to resolve uniquely",
                },
                "match": {
                    "type": "string",
                    "enum": ["exact", "contains", "regex"],
                    "description": "How to interpret `query` (default: contains)",
                },
                "user": {
                    "type": "string",
                    "description": "Optional exact username filter",
                },
                "port": {
                    "type": "integer",
                    "description": "Optional local TCP/UDP port filter; `0` is treated as omitted",
                },
            },
            "additionalProperties": False,
        }

    async def execute(
        self,
        pid: int | None = None,
        query: str = "",
        match: ProcessMatchMode = "contains",
        user: str = "",
        port: int | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        try:
            normalized_port = _normalize_port_filter(port)
            if pid is not None and pid <= 0:
                return ToolResult(error="pid must be > 0")

            result = await asyncio.to_thread(
                _get_process_sync,
                pid=pid,
                query=query.strip(),
                match=match,
                user=user.strip(),
                port=normalized_port,
            )
            return ToolResult(output=json.dumps(result, indent=2))
        except ValueError as e:
            return ToolResult(error=str(e))
        except Exception as e:
            return ToolResult(error=f"Process lookup failed: {e}")


list_processes_factory = ListProcessesSkill.factory  # type: ignore[attr-defined]
get_process_factory = GetProcessSkill.factory  # type: ignore[attr-defined]
