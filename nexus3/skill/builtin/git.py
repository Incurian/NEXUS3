"""Git skill for version control operations with permission-based filtering."""

import asyncio
import json
import re
import shlex
import subprocess
import sys
from typing import TYPE_CHECKING, Any

from nexus3.core.errors import PathSecurityError
from nexus3.skill.builtin.env import get_safe_env

if TYPE_CHECKING:
    pass
from nexus3.core.permissions import PermissionLevel
from nexus3.core.types import ToolResult
from nexus3.skill.base import FilteredCommandSkill, filtered_command_skill_factory

# Commands safe for read-only (SANDBOXED) mode
READ_ONLY_COMMANDS = frozenset({
    "status", "diff", "log", "show", "branch", "remote",
    "blame", "rev-parse", "describe", "ls-files", "ls-tree",
    "shortlog", "tag",  # tag without args is read-only
})

# Commands that require confirmation in TRUSTED mode
CONFIRM_COMMANDS = frozenset({
    "push", "pull", "merge", "rebase", "tag",
})

# Dangerous flags per command - blocked in all modes except YOLO
# Maps command -> {flag -> reason}
# Flags are checked after shlex parsing to prevent quote-based bypasses
DANGEROUS_FLAGS: dict[str, dict[str, str]] = {
    "reset": {
        "--hard": "discards uncommitted changes",
    },
    "push": {
        "-f": "rewrites remote history",
        "--force": "rewrites remote history",
        "--force-with-lease": "rewrites remote history",
    },
    "clean": {
        "-f": "deletes untracked files",
        "-d": "deletes untracked directories",
    },
    "rebase": {
        "-i": "requires terminal interaction",
        "--interactive": "requires terminal interaction",
    },
    "checkout": {
        "--orphan": "destroys branch history",
    },
}

# Timeout for git commands
GIT_TIMEOUT = 30.0


class GitSkill(FilteredCommandSkill):
    """Skill for git operations with permission-based command filtering.

    Provides granular git access without requiring full bash access.
    Commands are filtered based on permission level:
    - SANDBOXED: Read-only commands only (status, diff, log, etc.)
    - TRUSTED: Read + write commands, with confirmation for push/pull/merge
    - YOLO: All commands allowed

    Dangerous operations (reset --hard, push --force, etc.) are blocked
    in all modes except YOLO.
    """

    def get_read_only_commands(self) -> frozenset[str]:
        """Get commands allowed in SANDBOXED mode."""
        return READ_ONLY_COMMANDS

    def get_blocked_patterns(self) -> list[tuple[str, str]]:
        """Get regex patterns blocked in TRUSTED mode.

        Git uses DANGEROUS_FLAGS + _check_dangerous_flags() for security
        instead of regex patterns. This returns empty list to satisfy
        the FilteredCommandSkill interface.
        """
        return []

    @property
    def name(self) -> str:
        return "git"

    @property
    def description(self) -> str:
        return "Execute git commands with permission-based filtering"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Git command to run (e.g., 'status', 'diff HEAD~1', 'log -5')"
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory (default: current directory)"
                }
            },
            "required": ["command"]
        }

    def _validate_command(self, command: str) -> tuple[bool, list[str] | None, str | None]:
        """Validate git command against permission level.

        Parses the command with shlex.split() FIRST, then validates the parsed
        arguments. This prevents bypass attacks via creative quoting like
        'push "--force"' which would pass regex but execute dangerously.

        Returns:
            (allowed, parsed_args, error_message) tuple.
            parsed_args is the shlex-parsed argument list if allowed.
        """
        if not command.strip():
            return False, None, "No git command provided"

        # Parse command FIRST - this is the key security fix
        # Validation must operate on the same form that will be executed
        # Use non-POSIX mode on Windows to preserve backslash paths
        try:
            posix_mode = sys.platform != "win32"
            args = shlex.split(command, posix=posix_mode)

            # On Windows, posix=False preserves quotes in output which breaks
            # dangerous flag detection. Strip matching outer quotes.
            if sys.platform == "win32":
                args = [
                    arg[1:-1] if len(arg) >= 2 and arg[0] in "\"'" and arg[-1] == arg[0] else arg
                    for arg in args
                ]
        except ValueError as e:
            return False, None, f"Invalid command syntax: {e}"

        if not args:
            return False, None, "No git command provided"

        base_cmd = args[0].lower()

        # Check dangerous flags on PARSED args (except YOLO)
        if self._permission_level != PermissionLevel.YOLO:
            error = self._check_dangerous_flags(base_cmd, args)
            if error:
                return False, None, error

        # Check permission level
        if self._permission_level == PermissionLevel.SANDBOXED:
            if base_cmd not in READ_ONLY_COMMANDS:
                allowed = ', '.join(sorted(READ_ONLY_COMMANDS))
                return (
                    False, None,
                    "Only read-only git commands allowed in"
                    f" sandboxed mode. Allowed: {allowed}",
                )

        return True, args, None

    def _check_dangerous_flags(self, base_cmd: str, args: list[str]) -> str | None:
        """Check parsed arguments for dangerous flags.

        Handles both long flags (--force) and combined short flags (-fd).

        Args:
            base_cmd: The git subcommand (e.g., 'push', 'reset').
            args: Parsed argument list from shlex.split().

        Returns:
            Error message if dangerous flag found, None otherwise.
        """
        if base_cmd not in DANGEROUS_FLAGS:
            return None

        dangerous = DANGEROUS_FLAGS[base_cmd]

        for arg in args[1:]:  # Skip the command itself
            # Handle long flags (--force, --hard, etc.)
            if arg.startswith("--"):
                if arg in dangerous:
                    return f"Command blocked: {base_cmd} {arg} {dangerous[arg]}"
            # Handle short flags, including combined ones (-fd, -rf, etc.)
            elif arg.startswith("-") and len(arg) > 1:
                # Check each character in combined flags
                for char in arg[1:]:
                    flag = f"-{char}"
                    if flag in dangerous:
                        return f"Command blocked: {base_cmd} {flag} {dangerous[flag]}"

        return None

    def _parse_status_output(self, stdout: str) -> dict[str, Any]:
        """Parse git status output into structured format."""
        result: dict[str, Any] = {
            "branch": None,
            "ahead": 0,
            "behind": 0,
            "staged": [],
            "unstaged": [],
            "untracked": [],
        }

        for line in stdout.splitlines():
            # Branch info
            if line.startswith("On branch "):
                result["branch"] = line[10:].strip()
            elif "ahead of" in line:
                match = re.search(r"ahead of .+ by (\d+)", line)
                if match:
                    result["ahead"] = int(match.group(1))
            elif "behind" in line:
                match = re.search(r"behind .+ by (\d+)", line)
                if match:
                    result["behind"] = int(match.group(1))
            # Staged files
            elif line.startswith("\tnew file:"):
                result["staged"].append(line.split(":", 1)[1].strip())
            elif (
                line.startswith("\tmodified:")
                and "Changes to be committed" in stdout[:stdout.find(line)]
            ):
                result["staged"].append(line.split(":", 1)[1].strip())
            # Unstaged files
            elif line.startswith("\tmodified:"):
                result["unstaged"].append(line.split(":", 1)[1].strip())
            # Untracked
            elif line.startswith("\t") and "Untracked files:" in stdout[:stdout.find(line)]:
                result["untracked"].append(line.strip())

        return result

    def _parse_log_output(self, stdout: str) -> list[dict[str, str]]:
        """Parse git log output into structured format."""
        commits = []
        current: dict[str, str] = {}

        for line in stdout.splitlines():
            if line.startswith("commit "):
                if current:
                    commits.append(current)
                current = {"sha": line[7:].strip()}
            elif line.startswith("Author:"):
                current["author"] = line[7:].strip()
            elif line.startswith("Date:"):
                current["date"] = line[5:].strip()
            elif line.strip() and "sha" in current:
                if "message" not in current:
                    current["message"] = line.strip()

        if current:
            commits.append(current)

        return commits

    async def execute(
        self,
        command: str = "",
        cwd: str = ".",
        **kwargs: Any
    ) -> ToolResult:
        """Execute git command.

        Args:
            command: Git command to run (without 'git' prefix).
            cwd: Working directory for the command.

        Returns:
            ToolResult with command output or error.
        """
        # Validate command - returns parsed args to ensure we execute
        # exactly what we validated (no parse/validate/re-parse mismatch)
        allowed, parsed_args, error = self._validate_command(command)
        if not allowed or parsed_args is None:
            return ToolResult(error=error or "Command not allowed")

        try:
            # Validate working directory using base class method
            # (resolves relative paths against agent's cwd for multi-agent isolation)
            work_dir, error = self._validate_cwd(cwd)
            if error:
                return ToolResult(error=error)

            # Build command using pre-parsed args (not re-parsing!)
            cmd_parts = ["git"] + parsed_args

            # Execute with platform-specific process groups
            if sys.platform == "win32":
                process = await asyncio.create_subprocess_exec(
                    *cmd_parts,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(work_dir),
                    env=get_safe_env(str(work_dir)),
                    creationflags=(
                        subprocess.CREATE_NEW_PROCESS_GROUP |
                        subprocess.CREATE_NO_WINDOW
                    ),
                )
            else:
                process = await asyncio.create_subprocess_exec(
                    *cmd_parts,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(work_dir),
                    env=get_safe_env(str(work_dir)),
                    start_new_session=True,
                )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(),
                    timeout=GIT_TIMEOUT
                )
            except TimeoutError:
                from nexus3.core.process import terminate_process_tree
                await terminate_process_tree(process)
                return ToolResult(error=f"Git command timed out after {GIT_TIMEOUT}s")

            stdout_str = stdout_bytes.decode("utf-8", errors="replace").strip()
            stderr_str = stderr_bytes.decode("utf-8", errors="replace").strip()

            # Handle errors
            if process.returncode != 0:
                error_msg = stderr_str or stdout_str
                return ToolResult(error=f"Git error (exit {process.returncode}): {error_msg}")

            # Build output
            base_cmd = parsed_args[0].lower() if parsed_args else ""

            # Try to add structured data for common commands
            output_data: dict[str, Any] = {
                "success": True,
                "command": command,
                "output": stdout_str,
            }

            if base_cmd == "status":
                output_data["parsed"] = self._parse_status_output(stdout_str)
            elif base_cmd == "log":
                output_data["parsed"] = {"commits": self._parse_log_output(stdout_str)}

            return ToolResult(output=json.dumps(output_data, indent=2))

        except (PathSecurityError, ValueError) as e:
            return ToolResult(error=str(e))
        except FileNotFoundError:
            return ToolResult(error="Git is not installed or not in PATH")
        except Exception as e:
            return ToolResult(error=f"Git error: {e}")


# Apply standard factory decorator - permission_level is now resolved
# automatically via ServiceContainer.get_permission_level()
git_factory = filtered_command_skill_factory(GitSkill)
