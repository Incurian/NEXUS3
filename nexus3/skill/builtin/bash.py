"""Shell execution skills for NEXUS3.

Two skills with different security models:

- bash_safe: Uses shlex.split() + subprocess_exec (no shell interpretation)
  - Shell operators (|, &&, >, etc.) do NOT work
  - Safe from injection attacks
  - Recommended for most use cases

- shell_UNSAFE: Uses shell=True (full shell interpretation)
  - Shell operators work (pipes, redirects, etc.)
  - VULNERABLE to injection if input is not trusted
  - Name is intentionally alarming to prompt careful consideration

Both skills have identical permission settings:
- YOLO: No confirmation required
- TRUSTED: Always requires confirmation
- SANDBOXED: Completely disabled

P2.7 SECURITY: Defense-in-depth - these skills internally verify permission
level and refuse to execute in SANDBOXED mode, even if mistakenly registered.
"""

import asyncio
import os
import shlex
import subprocess
import sys
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from nexus3.core.permissions import PermissionLevel
from nexus3.core.types import ToolResult
from nexus3.skill.base import ExecutionSkill, execution_skill_factory
from nexus3.skill.builtin.env import get_safe_env

if TYPE_CHECKING:
    from nexus3.skill.services import ServiceContainer


def _check_permission_level(services: "ServiceContainer", skill_name: str) -> ToolResult | None:
    """P2.7 SECURITY: Defense-in-depth permission check.

    Verifies the agent's permission level allows execution skills.
    Returns an error ToolResult if blocked, or None if allowed.
    """
    level = services.get_permission_level()
    if level == PermissionLevel.SANDBOXED:
        return ToolResult(
            error=f"{skill_name} is disabled in SANDBOXED mode. "
            "This is a defense-in-depth check - the skill should"
            " not be registered for sandboxed agents."
        )
    return None


async def _execute_with_process_factory(
    skill: ExecutionSkill,
    timeout: int,
    cwd: str | None,
    timeout_message: str,
    process_factory: Callable[[str | None], Awaitable[asyncio.subprocess.Process]],
) -> ToolResult:
    """Execute a subprocess using per-request process arguments only."""
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


class BashSafeSkill(ExecutionSkill):
    """Safe shell skill using subprocess_exec (no shell interpretation).

    Commands are parsed with shlex.split() and executed directly without
    a shell. This prevents injection attacks but means shell operators
    like |, &&, >, $(), etc. do NOT work.

    Use this skill for:
    - Running single commands with arguments
    - Cases where you don't need shell features
    - Any situation where input might not be fully trusted

    Examples that WORK:
    - "ls -la /tmp"
    - "git status"
    - "python script.py --arg value"

    Examples that DON'T work:
    - "ls | grep foo" (pipe)
    - "cd /tmp && ls" (chaining)
    - "echo hello > file.txt" (redirect)
    - "echo $HOME" (variable expansion)
    """

    @property
    def name(self) -> str:
        return "bash_safe"

    @property
    def description(self) -> str:
        return "Execute a command safely (no shell operators like | && >)"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Command to execute (shell operators like | && > do NOT work)"
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
        work_dir: str | None,
        args: list[str],
    ) -> asyncio.subprocess.Process:
        """Create subprocess without shell."""
        # Platform-specific process group handling for clean timeout kills
        if sys.platform == "win32":
            return await asyncio.create_subprocess_exec(
                *args,
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
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=work_dir,
                env=get_safe_env(work_dir),
                start_new_session=True,
            )

    async def execute(
        self,
        command: str = "",
        timeout: int = 30,
        cwd: str | None = None,
        **kwargs: Any
    ) -> ToolResult:
        """Execute command safely without shell interpretation."""
        # P2.7 SECURITY: Defense-in-depth permission check
        if error := _check_permission_level(self._services, self.name):
            return error

        if not command:
            return ToolResult(error="Command is required")

        # Parse command with shlex
        # Use non-POSIX mode on Windows to preserve backslash paths
        # POSIX mode: C:\Users\foo → C:Usersfoo (backslash escapes)
        # Non-POSIX: C:\Users\foo → C:\Users\foo (preserved)
        try:
            posix_mode = sys.platform != "win32"
            args = shlex.split(command, posix=posix_mode)

            # On Windows, posix=False preserves quotes in output which breaks
            # downstream processing. Strip matching outer quotes.
            if sys.platform == "win32":
                args = [
                    arg[1:-1] if len(arg) >= 2 and arg[0] in "\"'" and arg[-1] == arg[0] else arg
                    for arg in args
                ]
        except ValueError as e:
            return ToolResult(error=f"Invalid command syntax: {e}")

        if not args:
            return ToolResult(error="Empty command after parsing")

        return await _execute_with_process_factory(
            skill=self,
            timeout=timeout,
            cwd=cwd,
            timeout_message="Command timed out after {timeout}s",
            process_factory=lambda work_dir: self._create_process(work_dir, args),
        )

class ShellUnsafeSkill(ExecutionSkill):
    """UNSAFE shell skill using shell=True (full shell interpretation).

    ⚠️  WARNING: This skill is vulnerable to shell injection attacks!

    Commands are passed directly to the shell, which means:
    - Shell operators work (|, &&, ||, >, >>, <, $(), ``, etc.)
    - Environment variable expansion works ($HOME, $PATH, etc.)
    - Glob expansion works (*.py, **/*.txt, etc.)
    - BUT malicious input can execute arbitrary commands

    Use this skill ONLY when:
    - You need shell features (pipes, redirects, etc.)
    - You trust the command source completely
    - You understand the security implications

    The name "shell_UNSAFE" is intentionally alarming to prompt
    careful consideration before use.
    """

    @property
    def name(self) -> str:
        return "shell_UNSAFE"

    @property
    def description(self) -> str:
        return (
            "Execute shell command with full shell features"
            " (pipes, redirects) - USE WITH CAUTION"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        "Shell command (supports | && > etc."
                        " but UNSAFE with untrusted input)"
                    )
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
        work_dir: str | None,
        command: str,
    ) -> asyncio.subprocess.Process:
        """Create shell subprocess."""
        # Platform-specific process group handling for clean timeout kills.
        # On Windows, route through the active shell family when detectable.
        # This prevents cmd.exe fallback from breaking Git Bash / PowerShell syntax.
        if sys.platform == "win32":
            if os.environ.get("MSYSTEM"):
                return await asyncio.create_subprocess_exec(
                    "bash", "-lc", command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=work_dir,
                    env=get_safe_env(work_dir),
                    creationflags=(
                        subprocess.CREATE_NEW_PROCESS_GROUP |
                        subprocess.CREATE_NO_WINDOW
                    ),
                )
            if os.environ.get("PSModulePath"):
                return await asyncio.create_subprocess_exec(
                    "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-Command", command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=work_dir,
                    env=get_safe_env(work_dir),
                    creationflags=(
                        subprocess.CREATE_NEW_PROCESS_GROUP |
                        subprocess.CREATE_NO_WINDOW
                    ),
                )
            return await asyncio.create_subprocess_shell(
                command,
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
            return await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=work_dir,
                env=get_safe_env(work_dir),
                start_new_session=True,
            )

    async def execute(
        self,
        command: str = "",
        timeout: int = 30,
        cwd: str | None = None,
        **kwargs: Any
    ) -> ToolResult:
        """Execute shell command with full shell interpretation."""
        # P2.7 SECURITY: Defense-in-depth permission check
        if error := _check_permission_level(self._services, self.name):
            return error

        if not command:
            return ToolResult(error="Command is required")

        return await _execute_with_process_factory(
            skill=self,
            timeout=timeout,
            cwd=cwd,
            timeout_message="Command timed out after {timeout}s",
            process_factory=lambda work_dir: self._create_process(work_dir, command),
        )


# Factories for dependency injection
bash_safe_factory = execution_skill_factory(BashSafeSkill)
shell_unsafe_factory = execution_skill_factory(ShellUnsafeSkill)

# Legacy alias for backwards compatibility during transition
bash_factory = bash_safe_factory
