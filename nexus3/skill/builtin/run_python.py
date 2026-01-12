"""Run Python skill for executing Python code."""

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

from nexus3.core.types import ToolResult
from nexus3.skill.services import ServiceContainer


class RunPythonSkill:
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

    def __init__(self) -> None:
        """Initialize RunPythonSkill.

        Unlike file skills, run_python does not use allowed_paths for sandbox.
        Instead, it is completely disabled in SANDBOXED mode via permissions.
        """
        pass

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

    async def execute(
        self,
        code: str = "",
        timeout: int = 30,
        cwd: str | None = None,
        **kwargs: Any
    ) -> ToolResult:
        """Execute Python code.

        Args:
            code: Python code to execute
            timeout: Timeout in seconds (max 300)
            cwd: Working directory (default: current)

        Returns:
            ToolResult with output or error message
        """
        if not code:
            return ToolResult(error="Code is required")

        # Enforce timeout limits
        timeout = min(max(timeout, 1), 300)

        # Resolve working directory
        work_dir: str | None = None
        if cwd:
            work_path = Path(cwd).expanduser()
            if not work_path.is_absolute():
                work_path = Path.cwd() / work_path
            if not work_path.is_dir():
                return ToolResult(error=f"Working directory not found: {cwd}")
            work_dir = str(work_path)

        try:
            # Use the same Python interpreter that's running NEXUS3
            python_exe = sys.executable

            # Create subprocess with python -c
            # Use exec() to avoid issues with multi-line code
            process = await asyncio.create_subprocess_exec(
                python_exe, "-c", code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=work_dir,
                env={**os.environ},  # Inherit environment
            )

            # Wait for completion with timeout
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return ToolResult(error=f"Python execution timed out after {timeout}s")

            # Decode output
            stdout_str = stdout.decode("utf-8", errors="replace").strip()
            stderr_str = stderr.decode("utf-8", errors="replace").strip()
            exit_code = process.returncode

            # Build output
            parts = []
            if stdout_str:
                parts.append(stdout_str)
            if stderr_str:
                if stdout_str:
                    parts.append(f"\n[stderr]\n{stderr_str}")
                else:
                    parts.append(f"[stderr]\n{stderr_str}")

            output = "\n".join(parts) if parts else "(no output)"

            # Include exit code if non-zero
            if exit_code != 0:
                output += f"\n\n[exit code: {exit_code}]"

            return ToolResult(output=output)

        except OSError as e:
            return ToolResult(error=f"Failed to execute Python: {e}")
        except Exception as e:
            return ToolResult(error=f"Error executing Python: {e}")


def run_python_factory(services: ServiceContainer) -> RunPythonSkill:
    """Factory function for RunPythonSkill.

    Args:
        services: ServiceContainer (not used, but required by protocol)

    Returns:
        New RunPythonSkill instance
    """
    return RunPythonSkill()
