"""Execution-oriented skills for NEXUS3.

Two skills with different security models:

- exec: Direct subprocess execution (no shell interpretation)
  - Shell operators (|, &&, >, etc.) do NOT work
  - Safer default for normal command execution
  - Recommended when shell syntax is not required

- shell_UNSAFE: Full shell execution with explicit shell-family selection
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
import shutil
import subprocess
import sys
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from nexus3.core.permissions import PermissionLevel
from nexus3.core.shell_detection import resolve_git_bash_executable
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


class ExecSkill(ExecutionSkill):
    """Direct process execution skill (no shell interpretation).

    `exec` launches the requested program and argument vector directly with
    `subprocess_exec`. Shell operators like `|`, `&&`, `>`, `$()`, and glob
    expansion do not work because no shell participates in execution.
    """

    @property
    def name(self) -> str:
        return "exec"

    @property
    def description(self) -> str:
        return "Execute a program directly without shell interpretation"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "program": {
                    "type": "string",
                    "description": "Program or executable path to run directly"
                },
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Argument vector passed to the program (default: [])",
                    "default": [],
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
            "required": ["program"],
            "additionalProperties": False,
        }

    async def _create_process(
        self,
        work_dir: str | None,
        program: str = "",
        args: list[str] | None = None,
    ) -> asyncio.subprocess.Process:
        """Create a subprocess without shell interpretation."""
        if not program:
            raise ValueError("Program is required")
        if args is None:
            args = []

        # Platform-specific process group handling for clean timeout kills
        if sys.platform == "win32":
            return await asyncio.create_subprocess_exec(
                program,
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
                program,
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=work_dir,
                env=get_safe_env(work_dir),
                start_new_session=True,
            )

    async def execute(
        self,
        program: str = "",
        args: list[str] | None = None,
        timeout: int = 30,
        cwd: str | None = None,
        **kwargs: Any
    ) -> ToolResult:
        """Execute a program directly without shell interpretation."""
        # P2.7 SECURITY: Defense-in-depth permission check
        if error := _check_permission_level(self._services, self.name):
            return error

        if not program or not program.strip():
            return ToolResult(error="Program is required")
        if args is None:
            args = []
        if not isinstance(args, list) or any(not isinstance(arg, str) for arg in args):
            return ToolResult(error="'args' must be an array of strings")

        return await _execute_with_process_factory(
            skill=self,
            timeout=timeout,
            cwd=cwd,
            timeout_message="Process timed out after {timeout}s",
            process_factory=lambda work_dir: self._create_process(work_dir, program.strip(), args),
        )

class ShellUnsafeSkill(ExecutionSkill):
    """UNSAFE shell skill using explicit shell execution.

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
                "shell": {
                    "type": "string",
                    "enum": ["auto", "bash", "gitbash", "powershell", "pwsh", "cmd"],
                    "description": "Shell family to use (default: auto)",
                    "default": "auto",
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
            "required": ["command"],
            "additionalProperties": False,
        }

    async def _create_process(
        self,
        work_dir: str | None,
        command: str = "",
        shell: str = "auto",
    ) -> asyncio.subprocess.Process:
        """Create shell subprocess using the requested shell family."""
        if not command:
            raise ValueError("Command is required")

        requested_shell = shell.strip().lower()
        if requested_shell not in {"auto", "bash", "gitbash", "powershell", "pwsh", "cmd"}:
            raise ValueError(f"Unsupported shell: {shell!r}")

        if sys.platform == "win32":
            env = get_safe_env(work_dir)
            creationflags = (
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) |
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
            if requested_shell == "auto":
                if os.environ.get("MSYSTEM"):
                    requested_shell = "gitbash"
                elif os.environ.get("PSModulePath"):
                    requested_shell = "powershell"
                else:
                    requested_shell = "cmd"

            if requested_shell == "gitbash":
                bash_executable = resolve_git_bash_executable(env.get("PATH"))
                if bash_executable is None:
                    raise OSError(
                        "Shell 'gitbash' is not available on this Windows host"
                    )
                if os.environ.get("MSYSTEM"):
                    env["MSYSTEM"] = os.environ["MSYSTEM"]
                return await asyncio.create_subprocess_exec(
                    bash_executable, "-lc", command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=work_dir,
                    env=env,
                    creationflags=creationflags,
                )
            if requested_shell == "powershell":
                return await asyncio.create_subprocess_exec(
                    "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-Command", command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=work_dir,
                    env=env,
                    creationflags=creationflags,
                )
            if requested_shell == "pwsh":
                if shutil.which("pwsh", path=env.get("PATH")) is None:
                    raise OSError("Shell 'pwsh' is not available on this Windows host")
                return await asyncio.create_subprocess_exec(
                    "pwsh", "-NoProfile", "-Command", command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=work_dir,
                    env=env,
                    creationflags=creationflags,
                )
            if requested_shell == "cmd":
                return await asyncio.create_subprocess_exec(
                    env.get("COMSPEC") or "cmd.exe", "/d", "/c", command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=work_dir,
                    env=env,
                    creationflags=creationflags,
                )
            if requested_shell == "bash":
                raise OSError("Shell 'bash' is not supported on Windows; use 'gitbash'")
            raise OSError(f"Unsupported shell on Windows: {shell!r}")

        env = get_safe_env(work_dir)
        if requested_shell == "auto":
            return await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=work_dir,
                env=env,
                start_new_session=True,
            )
        if requested_shell == "bash":
            if shutil.which("bash", path=env.get("PATH")) is None:
                raise OSError("Shell 'bash' is not available on this host")
            return await asyncio.create_subprocess_exec(
                "bash", "-lc", command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=work_dir,
                env=env,
                start_new_session=True,
            )
        if requested_shell == "powershell":
            if shutil.which("powershell", path=env.get("PATH")) is None:
                raise OSError("Shell 'powershell' is not available on this host")
            return await asyncio.create_subprocess_exec(
                "powershell", "-NoProfile", "-Command", command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=work_dir,
                env=env,
                start_new_session=True,
            )
        if requested_shell == "pwsh":
            if shutil.which("pwsh", path=env.get("PATH")) is None:
                raise OSError("Shell 'pwsh' is not available on this host")
            return await asyncio.create_subprocess_exec(
                "pwsh", "-NoProfile", "-Command", command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=work_dir,
                env=env,
                start_new_session=True,
            )
        if requested_shell in {"gitbash", "cmd"}:
            raise OSError(f"Shell '{requested_shell}' is only supported on Windows")
        raise OSError(f"Unsupported shell: {shell!r}")

    async def execute(
        self,
        command: str = "",
        shell: str = "auto",
        timeout: int = 30,
        cwd: str | None = None,
        **kwargs: Any
    ) -> ToolResult:
        """Execute shell command with full shell interpretation."""
        # P2.7 SECURITY: Defense-in-depth permission check
        if error := _check_permission_level(self._services, self.name):
            return error

        if not command or not command.strip():
            return ToolResult(error="Command is required")

        return await _execute_with_process_factory(
            skill=self,
            timeout=timeout,
            cwd=cwd,
            timeout_message="Command timed out after {timeout}s",
            process_factory=lambda work_dir: self._create_process(work_dir, command, shell),
        )


# Factories for dependency injection
exec_factory = execution_skill_factory(ExecSkill)
shell_unsafe_factory = execution_skill_factory(ShellUnsafeSkill)
