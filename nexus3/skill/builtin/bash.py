"""Bash skill for executing shell commands."""

import asyncio
import os
from typing import Any

from nexus3.core.types import ToolResult
from nexus3.skill.base import ExecutionSkill, execution_skill_factory


class BashSkill(ExecutionSkill):
    """Skill that executes shell commands.

    This is a high-risk skill that allows arbitrary command execution.
    Permission settings:
    - YOLO: No confirmation required
    - TRUSTED: Always requires confirmation (even in CWD)
    - SANDBOXED: Completely disabled

    The skill captures stdout and stderr, enforces timeout,
    and returns the command output along with exit code.
    """

    # Store command for _create_process to use
    _command: str = ""

    @property
    def name(self) -> str:
        return "bash"

    @property
    def description(self) -> str:
        return "Execute a shell command"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to execute"
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default: 30, max: 300)",
                    "default": 30
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory for command (default: current)"
                }
            },
            "required": ["command"]
        }

    async def _create_process(
        self,
        work_dir: str | None
    ) -> asyncio.subprocess.Process:
        """Create a shell subprocess."""
        return await asyncio.create_subprocess_shell(
            self._command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=work_dir,
            env={**os.environ},
        )

    async def execute(
        self,
        command: str = "",
        timeout: int = 30,
        cwd: str | None = None,
        **kwargs: Any
    ) -> ToolResult:
        """Execute a shell command."""
        if not command:
            return ToolResult(error="Command is required")

        self._command = command
        return await self._execute_subprocess(
            timeout=timeout,
            cwd=cwd,
            timeout_message="Command timed out after {timeout}s"
        )


# Factory for dependency injection
bash_factory = execution_skill_factory(BashSkill)
