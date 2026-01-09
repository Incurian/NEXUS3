"""Permission levels for NEXUS3 agents.

This module defines the permission system for controlling agent access.
Three permission levels are supported:
- yolo: Full access, no confirmations required
- trusted: Confirmations required for destructive actions (default)
- sandboxed: Limited paths, restricted network access

The PermissionPolicy class provides methods to check if specific actions
are allowed based on the permission level and configured path restrictions.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class PermissionLevel(Enum):
    """Permission levels for agents.

    Attributes:
        YOLO: Full access, no confirmations. Use with caution.
        TRUSTED: Confirmations for destructive actions. Recommended default.
        SANDBOXED: Limited paths, restricted network. For untrusted agents.
    """
    YOLO = "yolo"
    TRUSTED = "trusted"
    SANDBOXED = "sandboxed"


# Actions considered destructive (require confirmation in TRUSTED mode)
DESTRUCTIVE_ACTIONS = frozenset({
    "delete",
    "remove",
    "overwrite",
    "write",  # Writing to existing files
    "execute",
    "run_command",
    "shutdown",
})

# Actions always allowed without confirmation in TRUSTED mode
SAFE_ACTIONS = frozenset({
    "read",
    "list",
    "status",
    "search",
})

# Network-related actions (restricted in SANDBOXED mode)
NETWORK_ACTIONS = frozenset({
    "http_request",
    "send_message",
    "connect",
})


@dataclass
class PermissionPolicy:
    """Permission policy for an agent.

    Controls what actions an agent can perform based on its permission level
    and configured path restrictions.

    Attributes:
        level: The permission level (yolo, trusted, or sandboxed).
        allowed_paths: Paths the agent can access. None means unrestricted.
        blocked_paths: Paths that are always blocked regardless of level.
    """
    level: PermissionLevel
    allowed_paths: list[Path] | None = None
    blocked_paths: list[Path] = field(default_factory=list)

    @classmethod
    def from_level(cls, level: str | PermissionLevel) -> "PermissionPolicy":
        """Create policy from level string or enum.

        Args:
            level: Permission level as string ("yolo", "trusted", "sandboxed")
                   or PermissionLevel enum value.

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
                    f"Invalid permission level: {level!r}. "
                    f"Valid levels: {valid}"
                ) from e

        # Set defaults based on level
        if level == PermissionLevel.SANDBOXED:
            # Sandboxed agents default to CWD only
            return cls(
                level=level,
                allowed_paths=[Path.cwd()],
                blocked_paths=[],
            )
        else:
            # YOLO and TRUSTED have no path restrictions by default
            return cls(
                level=level,
                allowed_paths=None,
                blocked_paths=[],
            )

    def _is_path_blocked(self, path: Path) -> bool:
        """Check if path is in blocked_paths list.

        Args:
            path: Resolved path to check.

        Returns:
            True if path is within any blocked path.
        """
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
        """Check if path is in allowed_paths list.

        Args:
            path: Resolved path to check.

        Returns:
            True if allowed_paths is None (unrestricted) or path is within
            any allowed path.
        """
        # None means unrestricted
        if self.allowed_paths is None:
            return True

        # Empty list means nothing is allowed
        if not self.allowed_paths:
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

    def can_read_path(self, path: Path | str) -> bool:
        """Check if reading this path is allowed.

        Args:
            path: Path to check for read access.

        Returns:
            True if reading the path is allowed.
        """
        if isinstance(path, str):
            path = Path(path)

        resolved = path.resolve()

        # Blocked paths are always blocked
        if self._is_path_blocked(resolved):
            return False

        # Check allowed paths
        return self._is_path_allowed(resolved)

    def can_write_path(self, path: Path | str) -> bool:
        """Check if writing to this path is allowed.

        Args:
            path: Path to check for write access.

        Returns:
            True if writing to the path is allowed.
        """
        if isinstance(path, str):
            path = Path(path)

        resolved = path.resolve()

        # Blocked paths are always blocked
        if self._is_path_blocked(resolved):
            return False

        # Check allowed paths
        return self._is_path_allowed(resolved)

    def can_network(self) -> bool:
        """Check if network access is allowed.

        Returns:
            True if network operations are allowed.
            SANDBOXED mode restricts network access.
        """
        return self.level != PermissionLevel.SANDBOXED

    def requires_confirmation(self, action: str) -> bool:
        """Check if this action requires user confirmation.

        Confirmation behavior by level:
        - yolo: Never requires confirmation
        - trusted: Requires confirmation for destructive actions
        - sandboxed: Requires confirmation for most actions

        Args:
            action: The action to check (e.g., "delete", "write", "read").

        Returns:
            True if user confirmation should be requested.
        """
        action_lower = action.lower()

        if self.level == PermissionLevel.YOLO:
            # YOLO never requires confirmation
            return False

        elif self.level == PermissionLevel.TRUSTED:
            # TRUSTED requires confirmation for destructive actions
            return action_lower in DESTRUCTIVE_ACTIONS

        else:  # SANDBOXED
            # SANDBOXED requires confirmation for everything except safe reads
            if action_lower in SAFE_ACTIONS:
                return False
            return True

    def allows_action(self, action: str) -> bool:
        """Check if an action is allowed at all (regardless of confirmation).

        Some actions may be completely blocked in SANDBOXED mode, such as
        network operations.

        Args:
            action: The action to check.

        Returns:
            True if the action is allowed (may still require confirmation).
        """
        action_lower = action.lower()

        if self.level == PermissionLevel.SANDBOXED:
            # Network actions are blocked in sandboxed mode
            if action_lower in NETWORK_ACTIONS:
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
        return f"PermissionPolicy(level={self.level.value}{path_info})"
