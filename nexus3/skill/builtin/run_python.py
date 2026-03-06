"""Run Python skill for executing Python code.

P2.7 SECURITY: Defense-in-depth - this skill internally verifies permission
level and refuses to execute in SANDBOXED mode, even if mistakenly registered.
"""

import asyncio
import subprocess
import sys
from collections.abc import Awaitable, Callable
from typing import Any

from nexus3.core.permissions import PermissionLevel
from nexus3.core.types import ToolResult
from nexus3.skill.base import ExecutionSkill, execution_skill_factory
from nexus3.skill.builtin.env import get_safe_env


async def _execute_with_process_factory(
    skill: ExecutionSkill,
    timeout: int,
    cwd: str | None,
    timeout_message: str,
    process_factory: Callable[[str | None], Awaitable[asyncio.subprocess.Process]],
) -> ToolResult:
    """Execute a subprocess using per-request code payload only."""
    timeout = skill._enforce_timeout(timeout)

    work_dir, error = skill._resolve_working_directory(cwd)
    if error:
        return ToolResult(error=error)

    try:
        process = await process_factory(work_dir)

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout,
            )
        except TimeoutError:
            from nexus3.core.process import terminate_process_tree
            await terminate_process_tree(process)
            return ToolResult(error=timeout_message.format(timeout=timeout))

        output = skill._format_output(stdout, stderr, process.returncode)
        return ToolResult(output=output)

    except OSError as e:
        return ToolResult(error=f"Failed to execute: {e}")
    except Exception as e:
        return ToolResult(error=f"Error during execution: {e}")


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
        work_dir: str | None,
        code: str = "",
    ) -> asyncio.subprocess.Process:
        """Create a Python subprocess."""
        if not code:
            raise ValueError("Code payload is required")

        # Platform-specific process group handling for clean timeout kills
        if sys.platform == "win32":
            return await asyncio.create_subprocess_exec(
                sys.executable, "-c", code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=work_dir,
                env=get_safe_env(work_dir),
                creationflags=(
                    subprocess.CREATE_NEW_PROCESS_GROUP |
                    subprocess.CREATE_NO_WINDOW
                ),
            )
        else:
            return await asyncio.create_subprocess_exec(
                sys.executable, "-c", code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=work_dir,
                env=get_safe_env(work_dir),
                start_new_session=True,
            )

    async def execute(
        self,
        code: str = "",
        timeout: int = 30,
        cwd: str | None = None,
        **kwargs: Any
    ) -> ToolResult:
        """Execute Python code."""
        # P2.7 SECURITY: Defense-in-depth permission check
        level = self._services.get_permission_level()
        if level == PermissionLevel.SANDBOXED:
            return ToolResult(
                error=f"{self.name} is disabled in SANDBOXED mode. "
                "This is a defense-in-depth check - the skill should"
                " not be registered for sandboxed agents."
            )

        if not code:
            return ToolResult(error="Code is required")

        return await _execute_with_process_factory(
            skill=self,
            timeout=timeout,
            cwd=cwd,
            timeout_message="Python execution timed out after {timeout}s",
            process_factory=lambda work_dir: self._create_process(work_dir, code),
        )


# Factory for dependency injection
run_python_factory = execution_skill_factory(RunPythonSkill)
