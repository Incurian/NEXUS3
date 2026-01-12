"""Bash skill for executing shell commands."""

import asyncio
import os
from pathlib import Path
from typing import Any

from nexus3.core.types import ToolResult
from nexus3.skill.services import ServiceContainer


class BashSkill:
    """Skill that executes shell commands.

    This is a high-risk skill that allows arbitrary command execution.
    Permission settings:
    - YOLO: No confirmation required
    - TRUSTED: Always requires confirmation (even in CWD)
    - SANDBOXED: Completely disabled

    The skill captures stdout and stderr, enforces timeout,
    and returns the command output along with exit code.
    """

    def __init__(self) -> None:
        """Initialize BashSkill.

        Unlike file skills, bash does not use allowed_paths for sandbox.
        Instead, it is completely disabled in SANDBOXED mode via permissions.
        """
        pass

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

    async def execute(
        self,
        command: str = "",
        timeout: int = 30,
        cwd: str | None = None,
        **kwargs: Any
    ) -> ToolResult:
        """Execute a shell command.

        Args:
            command: Shell command to execute
            timeout: Timeout in seconds (max 300)
            cwd: Working directory (default: current)

        Returns:
            ToolResult with command output or error message
        """
        if not command:
            return ToolResult(error="Command is required")

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
            # Create subprocess
            process = await asyncio.create_subprocess_shell(
                command,
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
                return ToolResult(error=f"Command timed out after {timeout}s")

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
            return ToolResult(error=f"Failed to execute command: {e}")
        except Exception as e:
            return ToolResult(error=f"Error executing command: {e}")


def bash_factory(services: ServiceContainer) -> BashSkill:
    """Factory function for BashSkill.

    Args:
        services: ServiceContainer (not used, but required by protocol)

    Returns:
        New BashSkill instance
    """
    return BashSkill()
