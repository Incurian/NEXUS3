"""Run Python skill for executing Python code."""

import asyncio
import os
import sys
from typing import Any

from nexus3.core.types import ToolResult
from nexus3.skill.base import ExecutionSkill, execution_skill_factory


class RunPythonSkill(ExecutionSkill):
    """Skill that executes Python code.

    This is a high-risk skill that allows arbitrary Python execution.
    Permission settings:
    - YOLO: No confirmation required
    - TRUSTED: Always requires confirmation (even in CWD)
    - SANDBOXED: Completely disabled

    Safer than bash for simple scripts as it doesn't use shell expansion.
    The skill captures stdout and stderr, enforces timeout,
    and returns the output.
    """

    # Store code for _create_process to use
    _code: str = ""

    @property
    def name(self) -> str:
        return "run_python"

    @property
    def description(self) -> str:
        return "Execute Python code"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to execute"
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default: 30, max: 300)",
                    "default": 30
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory (default: current)"
                }
            },
            "required": ["code"]
        }

    async def _create_process(
        self,
        work_dir: str | None
    ) -> asyncio.subprocess.Process:
        """Create a Python subprocess."""
        return await asyncio.create_subprocess_exec(
            sys.executable, "-c", self._code,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=work_dir,
            env={**os.environ},
        )

    async def execute(
        self,
        code: str = "",
        timeout: int = 30,
        cwd: str | None = None,
        **kwargs: Any
    ) -> ToolResult:
        """Execute Python code."""
        if not code:
            return ToolResult(error="Code is required")

        self._code = code
        return await self._execute_subprocess(
            timeout=timeout,
            cwd=cwd,
            timeout_message="Python execution timed out after {timeout}s"
        )


# Factory for dependency injection
run_python_factory = execution_skill_factory(RunPythonSkill)
