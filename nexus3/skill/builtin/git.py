"""Git skill for version control operations with permission-based filtering."""

import asyncio
import json
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

from nexus3.core.errors import PathSecurityError
from nexus3.core.paths import validate_sandbox
from nexus3.core.permissions import PermissionLevel
from nexus3.core.types import ToolResult
from nexus3.skill.services import ServiceContainer


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

# Dangerous patterns - blocked in all modes except YOLO
BLOCKED_PATTERNS = [
    (r"reset\s+--hard", "reset --hard discards uncommitted changes"),
    (r"push\s+(-f|--force)", "force push rewrites remote history"),
    (r"clean\s+-[fd]", "clean -f/-d deletes untracked files"),
    (r"rebase\s+-i", "interactive rebase requires terminal"),
    (r"checkout\s+--orphan", "orphan checkout destroys branch history"),
    (r"push\s+--force-with-lease", "force push rewrites remote history"),
]

# Timeout for git commands
GIT_TIMEOUT = 30.0


class GitSkill:
    """Skill for git operations with permission-based command filtering.

    Provides granular git access without requiring full bash access.
    Commands are filtered based on permission level:
    - SANDBOXED: Read-only commands only (status, diff, log, etc.)
    - TRUSTED: Read + write commands, with confirmation for push/pull/merge
    - YOLO: All commands allowed

    Dangerous operations (reset --hard, push --force, etc.) are blocked
    in all modes except YOLO.
    """

    def __init__(
        self,
        allowed_paths: list[Path] | None = None,
        permission_level: PermissionLevel = PermissionLevel.TRUSTED,
    ) -> None:
        """Initialize GitSkill.

        Args:
            allowed_paths: Directories where git operations are allowed.
                - None: Unrestricted
                - []: No paths allowed
                - [Path(...)]: Only within these directories
            permission_level: Controls which commands are allowed.
        """
        self._allowed_paths = allowed_paths
        self._permission_level = permission_level

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

    def _validate_command(self, command: str) -> tuple[bool, str | None]:
        """Validate git command against permission level.

        Returns:
            (allowed, error_message) tuple.
        """
        if not command.strip():
            return False, "No git command provided"

        # Extract base command (first word)
        parts = command.split()
        base_cmd = parts[0].lower() if parts else ""

        # Check blocked patterns (except YOLO)
        if self._permission_level != PermissionLevel.YOLO:
            for pattern, reason in BLOCKED_PATTERNS:
                if re.search(pattern, command, re.IGNORECASE):
                    return False, f"Command blocked: {reason}"

        # Check permission level
        if self._permission_level == PermissionLevel.SANDBOXED:
            if base_cmd not in READ_ONLY_COMMANDS:
                return False, f"Only read-only git commands allowed in sandboxed mode. Allowed: {', '.join(sorted(READ_ONLY_COMMANDS))}"

        return True, None

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
            elif line.startswith("\tmodified:") and "Changes to be committed" in stdout[:stdout.find(line)]:
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
        # Validate command
        allowed, error = self._validate_command(command)
        if not allowed:
            return ToolResult(error=error or "Command not allowed")

        try:
            # Validate working directory if sandbox active
            if self._allowed_paths is not None:
                work_dir = validate_sandbox(cwd, self._allowed_paths)
            else:
                work_dir = Path(cwd).resolve()

            # Verify directory exists
            if not work_dir.is_dir():
                return ToolResult(error=f"Directory not found: {cwd}")

            # Build command
            cmd_parts = ["git"] + shlex.split(command)

            # Execute with timeout
            def run_git() -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    cmd_parts,
                    cwd=str(work_dir),
                    capture_output=True,
                    text=True,
                    timeout=GIT_TIMEOUT,
                )

            result = await asyncio.wait_for(
                asyncio.to_thread(run_git),
                timeout=GIT_TIMEOUT + 1,
            )

            # Handle errors
            if result.returncode != 0:
                error_msg = result.stderr.strip() or result.stdout.strip()
                return ToolResult(error=f"Git error (exit {result.returncode}): {error_msg}")

            # Build output
            stdout = result.stdout.strip()
            base_cmd = command.split()[0].lower() if command.split() else ""

            # Try to add structured data for common commands
            output_data: dict[str, Any] = {
                "success": True,
                "command": command,
                "output": stdout,
            }

            if base_cmd == "status":
                output_data["parsed"] = self._parse_status_output(stdout)
            elif base_cmd == "log":
                output_data["parsed"] = {"commits": self._parse_log_output(stdout)}

            return ToolResult(output=json.dumps(output_data, indent=2))

        except PathSecurityError as e:
            return ToolResult(error=str(e))
        except subprocess.TimeoutExpired:
            return ToolResult(error=f"Git command timed out after {GIT_TIMEOUT}s")
        except FileNotFoundError:
            return ToolResult(error="Git is not installed or not in PATH")
        except Exception as e:
            return ToolResult(error=f"Git error: {e}")


def git_factory(services: ServiceContainer) -> GitSkill:
    """Factory function for GitSkill.

    Args:
        services: ServiceContainer for dependency injection.

    Returns:
        New GitSkill instance configured based on services.
    """
    allowed_paths: list[Path] | None = services.get("allowed_paths")

    # Get permission level from permissions object
    permissions = services.get("permissions")
    if permissions:
        level = permissions.effective_policy.level
    else:
        level = PermissionLevel.TRUSTED

    return GitSkill(allowed_paths=allowed_paths, permission_level=level)
