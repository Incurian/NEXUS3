"""Permission policy primitives for NEXUS3.

This module defines the core permission primitives:
- PermissionLevel: Enum of permission levels (yolo, trusted, sandboxed)
- ConfirmationResult: User's response to confirmation prompts
- Action constants: DESTRUCTIVE_ACTIONS, SAFE_ACTIONS, etc.
- PermissionPolicy: Path and action restrictions
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nexus3.core.allowances import SessionAllowances


class PermissionLevel(Enum):
    """Permission levels for agents.

    Attributes:
        YOLO: Full access, no confirmations. Use with caution.
        TRUSTED: CWD auto-allowed, prompts for other paths with allow once/always.
        SANDBOXED: Immutable sandbox, no execution, no agent management.
    """
    YOLO = "yolo"
    TRUSTED = "trusted"
    SANDBOXED = "sandboxed"


class ConfirmationResult(Enum):
    """Result of a confirmation prompt.

    Used by TRUSTED mode to implement "allow once/always" functionality.
    """
    DENY = "deny"
    ALLOW_ONCE = "allow_once"
    # For write operations (write_file, edit_file)
    ALLOW_FILE = "allow_file"               # Allow always for this specific file
    ALLOW_WRITE_DIRECTORY = "allow_write_directory"  # Allow writes in this directory
    # For execution operations (bash, run_python)
    ALLOW_EXEC_CWD = "allow_exec_cwd"       # Allow tool in current working directory
    ALLOW_EXEC_GLOBAL = "allow_exec_global" # Allow tool globally (any directory)


# Actions that are always destructive (require confirmation or allowance check)
DESTRUCTIVE_ACTIONS = frozenset({
    "write",
    "delete",
    "remove",
    "overwrite",
    "execute",
    "run_command",
    "shutdown",
    # Specific tool names
    "write_file",
    "edit_file",
    "append_file",
    "regex_replace",
    "bash",
    "run_python",
    "nexus_destroy",
    "nexus_shutdown",
})

# Actions always allowed without confirmation
SAFE_ACTIONS = frozenset({
    "read",
    "list",
    "status",
    "search",
    "glob",
    "grep",
})

# Network-related actions (restricted in SANDBOXED mode)
NETWORK_ACTIONS = frozenset({
    "http_request",
    "send_message",
    "connect",
})

# Tools completely disabled in SANDBOXED mode (execution and agent management)
SANDBOXED_DISABLED_TOOLS = frozenset({
    "bash",
    "run_python",
    "nexus_send",
    "nexus_create",
    "nexus_destroy",
    "nexus_shutdown",
    "nexus_cancel",
    "nexus_status",
})


@dataclass
class PermissionPolicy:
    """Permission policy for an agent.

    Controls what actions an agent can perform based on its permission level
    and configured path restrictions.

    Attributes:
        level: The permission level (yolo, trusted, or sandboxed).
        allowed_paths: Paths the agent can access.
            - None: Unrestricted access (can access any path)
            - []: Empty list means NO paths allowed (deny all)
            - [Path(...)]: Only paths within the listed directories allowed
        blocked_paths: Paths that are always blocked regardless of level.
        cwd: The working directory at agent creation (auto-allowed for TRUSTED).
        frozen: If True, allowed_paths cannot be modified (for SANDBOXED).
    """
    level: PermissionLevel
    # None = unrestricted, [] = nothing allowed, [paths...] = only within these
    allowed_paths: list[Path] | None = None
    blocked_paths: list[Path] = field(default_factory=list)
    cwd: Path = field(default_factory=Path.cwd)
    frozen: bool = False

    @classmethod
    def from_level(cls, level: str | PermissionLevel) -> PermissionPolicy:
        """Create policy from level string or enum.

        Args:
            level: Permission level as string or PermissionLevel enum.

        Returns:
            PermissionPolicy with appropriate defaults for the level.

        Raises:
            ValueError: If level string is not recognized.
        """
        if isinstance(level, str):
            try:
                level = PermissionLevel(level.lower())
            except ValueError as e:
                valid = [pl.value for pl in PermissionLevel]
                raise ValueError(
                    f"Invalid permission level: {level!r}. Valid levels: {valid}"
                ) from e

        cwd = Path.cwd()

        if level == PermissionLevel.SANDBOXED:
            # Sandboxed: CWD only, frozen
            return cls(
                level=level,
                allowed_paths=[cwd],
                blocked_paths=[],
                cwd=cwd,
                frozen=True,
            )
        elif level == PermissionLevel.TRUSTED:
            # Trusted: CWD auto-allowed, can expand via session allowances
            return cls(
                level=level,
                allowed_paths=None,  # Unrestricted, but uses CWD + allowances for confirmation
                blocked_paths=[],
                cwd=cwd,
                frozen=False,
            )
        else:
            # YOLO: No restrictions
            return cls(
                level=level,
                allowed_paths=None,
                blocked_paths=[],
                cwd=cwd,
                frozen=False,
            )

    def _is_path_blocked(self, path: Path) -> bool:
        """Check if path is in blocked_paths list."""
        if not self.blocked_paths:
            return False

        resolved = path.resolve()
        for blocked in self.blocked_paths:
            try:
                blocked_resolved = blocked.resolve()
                if resolved.is_relative_to(blocked_resolved):
                    return True
            except (OSError, ValueError):
                continue
        return False

    def _is_path_allowed(self, path: Path) -> bool:
        """Check if path is in allowed_paths list (for SANDBOXED).

        allowed_paths semantics:
        - None: Unrestricted - allow any path
        - []: Empty list - deny ALL paths (nothing allowed)
        - [Path(...)]: Allow only paths within listed directories
        """
        if self.allowed_paths is None:  # None = unrestricted
            return True

        if not self.allowed_paths:  # [] = nothing allowed
            return False

        resolved = path.resolve()
        for allowed in self.allowed_paths:
            try:
                allowed_resolved = allowed.resolve()
                if resolved.is_relative_to(allowed_resolved):
                    return True
            except (OSError, ValueError):
                continue
        return False

    def is_within_cwd(self, path: Path) -> bool:
        """Check if path is within the working directory."""
        try:
            resolved = path.resolve()
            return resolved.is_relative_to(self.cwd.resolve())
        except (OSError, ValueError):
            return False

    def can_read_path(self, path: Path | str) -> bool:
        """Check if reading this path is allowed."""
        if isinstance(path, str):
            path = Path(path)

        resolved = path.resolve()

        if self._is_path_blocked(resolved):
            return False

        return self._is_path_allowed(resolved)

    def can_write_path(self, path: Path | str) -> bool:
        """Check if writing to this path is allowed (ignoring confirmations).

        For SANDBOXED: Must be within sandbox.
        For TRUSTED/YOLO: Always returns True (confirmation handled separately).
        """
        if isinstance(path, str):
            path = Path(path)

        resolved = path.resolve()

        if self._is_path_blocked(resolved):
            return False

        if self.level == PermissionLevel.SANDBOXED:
            return self._is_path_allowed(resolved)

        return True

    def can_network(self) -> bool:
        """Check if network access is allowed."""
        return self.level != PermissionLevel.SANDBOXED

    def requires_confirmation(
        self,
        action: str,
        path: Path | None = None,
        exec_cwd: Path | None = None,
        session_allowances: SessionAllowances | None = None,
    ) -> bool:
        """Check if this action requires user confirmation.

        YOLO: Never requires confirmation.
        TRUSTED: Requires confirmation for destructive actions outside CWD/allowances.
        SANDBOXED: Never requires confirmation (just enforces sandbox).

        Args:
            action: The action to check (e.g., "write_file", "bash").
            path: Optional path being accessed (for write operations).
            exec_cwd: Working directory for execution tools (bash, run_python).
            session_allowances: Dynamic allowances from user's "allow always" responses.

        Returns:
            True if user confirmation should be requested.
        """
        action_lower = action.lower()

        if self.level == PermissionLevel.YOLO:
            return False

        if self.level == PermissionLevel.SANDBOXED:
            # Sandboxed doesn't use confirmation - just enforces sandbox
            return False

        # TRUSTED mode
        if action_lower in SAFE_ACTIONS:
            return False

        if action_lower not in DESTRUCTIVE_ACTIONS:
            return False

        # For execution tools, check exec allowances
        if action_lower in ("bash", "run_python"):
            if session_allowances:
                # Check if tool is allowed in the execution directory
                if session_allowances.is_exec_allowed(action_lower, exec_cwd):
                    return False
            # Execution tools in CWD still need confirmation unless explicitly allowed
            return True

        # For path-based tools (write_file, edit_file), check path allowances
        if path is not None:
            # Within CWD - no confirmation needed
            if self.is_within_cwd(path):
                return False

            # Check write allowances
            if session_allowances and session_allowances.is_write_allowed(path):
                return False

        # Destructive action outside allowed paths - needs confirmation
        return True

    def allows_action(self, action: str) -> bool:
        """Check if an action is allowed at all (regardless of confirmation).

        Some actions are completely blocked in SANDBOXED mode.

        Args:
            action: The action to check.

        Returns:
            True if the action is allowed (may still require confirmation).
        """
        if self.level == PermissionLevel.SANDBOXED:
            # Execution tools blocked in sandboxed mode
            if action.lower() in SANDBOXED_DISABLED_TOOLS:
                return False

        return True

    def __str__(self) -> str:
        """Human-readable representation of the policy."""
        path_info = ""
        if self.allowed_paths is not None:
            paths_str = ", ".join(str(p) for p in self.allowed_paths)
            path_info = f", allowed_paths=[{paths_str}]"
        if self.blocked_paths:
            blocked_str = ", ".join(str(p) for p in self.blocked_paths)
            path_info += f", blocked_paths=[{blocked_str}]"
        if self.frozen:
            path_info += ", frozen=True"
        return f"PermissionPolicy(level={self.level.value}, cwd={self.cwd}{path_info})"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for RPC transport."""
        result: dict[str, Any] = {
            "level": self.level.value,
            "cwd": str(self.cwd),
            "frozen": self.frozen,
        }
        if self.allowed_paths is not None:
            result["allowed_paths"] = [str(p) for p in self.allowed_paths]
        if self.blocked_paths:
            result["blocked_paths"] = [str(p) for p in self.blocked_paths]
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PermissionPolicy:
        """Deserialize from dict."""
        allowed = data.get("allowed_paths")
        return cls(
            level=PermissionLevel(data["level"]),
            allowed_paths=[Path(p) for p in allowed] if allowed else None,
            blocked_paths=[Path(p) for p in data.get("blocked_paths", [])],
            cwd=Path(data.get("cwd", ".")),
            frozen=data.get("frozen", False),
        )
