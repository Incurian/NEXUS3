"""Built-in tool for explicit PID-based process termination."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

import psutil  # type: ignore[import-untyped]

from nexus3.core.process_tools import (
    get_process_details,
    normalize_kill_timeout,
    protected_termination_reason,
    terminate_pid,
)
from nexus3.core.types import ToolResult
from nexus3.skill.base import base_skill_factory

if TYPE_CHECKING:
    from nexus3.skill.services import ServiceContainer


@base_skill_factory
class KillProcessSkill:
    """Terminate a running process by explicit PID."""

    def __init__(self, services: ServiceContainer | None = None) -> None:
        self._services = services

    @property
    def name(self) -> str:
        return "kill_process"

    @property
    def description(self) -> str:
        return "Terminate a running process by PID"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pid": {
                    "type": "integer",
                    "description": "PID of the process to terminate",
                },
                "tree": {
                    "type": "boolean",
                    "description": "Terminate child processes too (default: true)",
                },
                "force": {
                    "type": "boolean",
                    "description": "Kill immediately instead of graceful-first termination",
                },
                "timeout_seconds": {
                    "type": "number",
                    "description": "Graceful wait timeout before escalation (default: 2.0)",
                },
            },
            "required": ["pid"],
            "additionalProperties": False,
        }

    async def execute(
        self,
        pid: int | None = None,
        tree: bool = True,
        force: bool = False,
        timeout_seconds: float | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        if pid is None:
            return ToolResult(error="No pid provided")
        if pid <= 0:
            return ToolResult(error="pid must be > 0")

        try:
            normalized_timeout = normalize_kill_timeout(timeout_seconds)
            reason = protected_termination_reason(pid, tree=tree)
            if reason:
                return ToolResult(error=reason)

            target = await asyncio.to_thread(get_process_details, pid, include_ports=False)
            result = await asyncio.to_thread(
                terminate_pid,
                pid,
                tree=tree,
                force=force,
                timeout_seconds=normalized_timeout,
            )
            return ToolResult(
                output=json.dumps(
                    {
                        "target": target,
                        "result": result,
                    },
                    indent=2,
                )
            )
        except psutil.NoSuchProcess:
            return ToolResult(error=f"Process not found: PID {pid}")
        except psutil.AccessDenied:
            return ToolResult(error=f"Permission denied while terminating PID {pid}")
        except ValueError as e:
            return ToolResult(error=str(e))
        except Exception as e:
            return ToolResult(error=f"Process termination failed: {e}")


kill_process_factory = KillProcessSkill.factory  # type: ignore[attr-defined]
