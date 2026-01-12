"""Permission system for NEXUS3 agents.

This module defines the permission system for controlling agent access.
Three permission levels are supported:
- yolo: Full access, no confirmations required
- trusted: CWD auto-allowed, dynamic "allow once/always" for other paths
- sandboxed: Immutable sandbox, can write within it, no execution/agent mgmt

The permission system enforces ceiling inheritance: child agents cannot
exceed parent permissions.

Key types:
- PermissionLevel: Enum of permission levels
- PermissionPolicy: Path and action restrictions
- ToolPermission: Per-tool configuration
- PermissionPreset: Named preset configuration
- PermissionDelta: Changes to apply to a preset
- WriteAllowances: Dynamic write path allowances for TRUSTED mode
- AgentPermissions: Runtime permission state
- ConfirmationResult: User's response to confirmation prompt
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


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
class SessionAllowances:
    """Dynamic allowances for TRUSTED mode.

    Stores user's "allow always" decisions during a session.
    These are persisted with the session.

    Categories:
    - Write allowances: Per-file or per-directory for write operations
    - Execution allowances: Per-directory or global for execution tools (bash, run_python)

    Note: Read operations are unrestricted in TRUSTED mode.
    """
    # Path-based allowances for write operations
    write_files: set[Path] = field(default_factory=set)
    write_directories: set[Path] = field(default_factory=set)

    # Execution tools allowed globally (any working directory)
    exec_global: set[str] = field(default_factory=set)

    # Execution tools allowed in specific directories only
    # Maps tool_name -> set of allowed directories
    exec_directories: dict[str, set[Path]] = field(default_factory=dict)

    def is_write_allowed(self, path: Path) -> bool:
        """Check if path is covered by an existing write allowance."""
        resolved = path.resolve()

        # Check exact file match
        if resolved in self.write_files:
            return True

        # Check directory allowances
        for allowed_dir in self.write_directories:
            try:
                if resolved.is_relative_to(allowed_dir):
                    return True
            except (OSError, ValueError):
                continue

        return False

    def is_exec_allowed(self, tool_name: str, cwd: Path | None = None) -> bool:
        """Check if execution tool is allowed.

        Args:
            tool_name: The tool (e.g., "bash", "run_python")
            cwd: Working directory for the execution (None = current directory)

        Returns:
            True if the tool is allowed globally or in the given directory.
        """
        # Check global allowance first
        if tool_name in self.exec_global:
            return True

        # Check directory-specific allowance
        if tool_name not in self.exec_directories:
            return False

        # Check if cwd is within any allowed directory
        if cwd is None:
            cwd = Path.cwd()
        resolved_cwd = cwd.resolve()

        for allowed_dir in self.exec_directories[tool_name]:
            try:
                if resolved_cwd.is_relative_to(allowed_dir):
                    return True
            except (OSError, ValueError):
                continue

        return False

    def add_write_file(self, path: Path) -> None:
        """Add a file to the write allowance list."""
        self.write_files.add(path.resolve())

    def add_write_directory(self, path: Path) -> None:
        """Add a directory to the write allowance list."""
        self.write_directories.add(path.resolve())

    def add_exec_global(self, tool_name: str) -> None:
        """Allow execution tool globally (any directory)."""
        self.exec_global.add(tool_name)
        # Remove from directory-specific if present (global supersedes)
        self.exec_directories.pop(tool_name, None)

    def add_exec_directory(self, tool_name: str, directory: Path) -> None:
        """Allow execution tool in a specific directory.

        If the tool is already globally allowed, this is a no-op.
        Otherwise, adds the directory to the list of allowed directories.
        """
        # Don't add directory restriction if already globally allowed
        if tool_name in self.exec_global:
            return

        if tool_name not in self.exec_directories:
            self.exec_directories[tool_name] = set()

        self.exec_directories[tool_name].add(directory.resolve())

    def to_dict(self) -> dict[str, Any]:
        """Serialize for persistence."""
        return {
            "write_files": [str(p) for p in self.write_files],
            "write_directories": [str(p) for p in self.write_directories],
            "exec_global": list(self.exec_global),
            "exec_directories": {
                tool: [str(p) for p in dirs]
                for tool, dirs in self.exec_directories.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionAllowances:
        """Deserialize from persistence."""
        return cls(
            write_files={Path(p) for p in data.get("write_files", [])},
            write_directories={Path(p) for p in data.get("write_directories", [])},
            exec_global=set(data.get("exec_global", [])),
            exec_directories={
                tool: {Path(p) for p in dirs}
                for tool, dirs in data.get("exec_directories", {}).items()
            },
        )

    # Backwards compatibility
    @property
    def allowed_files(self) -> set[Path]:
        return self.write_files

    @property
    def allowed_directories(self) -> set[Path]:
        return self.write_directories

    def is_path_allowed(self, path: Path) -> bool:
        """Backwards compatibility alias for is_write_allowed."""
        return self.is_write_allowed(path)

    def add_file(self, path: Path) -> None:
        """Backwards compatibility alias for add_write_file."""
        self.add_write_file(path)

    def add_directory(self, path: Path) -> None:
        """Backwards compatibility alias for add_write_directory."""
        self.add_write_directory(path)


# Backwards compatibility alias
WriteAllowances = SessionAllowances


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
        return cls(
            level=PermissionLevel(data["level"]),
            allowed_paths=[Path(p) for p in data["allowed_paths"]] if data.get("allowed_paths") else None,
            blocked_paths=[Path(p) for p in data.get("blocked_paths", [])],
            cwd=Path(data.get("cwd", ".")),
            frozen=data.get("frozen", False),
        )


@dataclass
class ToolPermission:
    """Per-tool permission configuration.

    Attributes:
        enabled: Whether the tool is enabled at all.
        allowed_paths: Per-tool path restrictions.
            - None: Inherit from preset/policy (default)
            - []: Empty list means tool cannot access any paths
            - [Path(...)]: Tool can only access paths within these directories
        timeout: Tool-specific timeout (None = use default).
        requires_confirmation: Override confirmation behavior (None = use policy default).
    """

    enabled: bool = True
    # None = inherit from preset, [] = deny all, [paths...] = only these
    allowed_paths: list[Path] | None = None
    timeout: float | None = None  # None = use default
    requires_confirmation: bool | None = None  # None = use policy default

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for RPC transport."""
        result: dict[str, Any] = {"enabled": self.enabled}
        if self.allowed_paths is not None:
            result["allowed_paths"] = [str(p) for p in self.allowed_paths]
        if self.timeout is not None:
            result["timeout"] = self.timeout
        if self.requires_confirmation is not None:
            result["requires_confirmation"] = self.requires_confirmation
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolPermission:
        """Deserialize from dict."""
        return cls(
            enabled=data.get("enabled", True),
            allowed_paths=[Path(p) for p in data["allowed_paths"]] if data.get("allowed_paths") else None,
            timeout=data.get("timeout"),
            requires_confirmation=data.get("requires_confirmation"),
        )


@dataclass
class PermissionPreset:
    """Named permission configuration preset.

    Attributes:
        name: Preset identifier.
        level: Base permission level (yolo/trusted/sandboxed).
        description: Human-readable description.
        allowed_paths: Path restrictions for the preset.
            - None: Unrestricted access (can access any path)
            - []: Empty list means NO paths allowed (deny all)
            - [Path(...)]: Only paths within listed directories allowed
        blocked_paths: Paths always blocked regardless of allowed_paths.
        network_access: Whether network operations are permitted.
        tool_permissions: Per-tool configuration overrides.
        default_tool_timeout: Default timeout for tools in this preset.
    """

    name: str
    level: PermissionLevel
    description: str = ""
    # None = unrestricted, [] = deny all, [paths...] = only within these
    allowed_paths: list[Path] | None = None
    blocked_paths: list[Path] = field(default_factory=list)
    network_access: bool = True
    tool_permissions: dict[str, ToolPermission] = field(default_factory=dict)
    default_tool_timeout: float = 30.0


@dataclass
class PermissionDelta:
    """Changes to apply to a base preset.

    Attributes:
        disable_tools: Tools to disable.
        enable_tools: Tools to enable.
        allowed_paths: Replace base allowed_paths.
            - None: Keep base preset's allowed_paths (no change)
            - []: Replace with empty list (deny all paths)
            - [Path(...)]: Replace with specific paths
        add_blocked_paths: Additional paths to block.
        tool_overrides: Per-tool permission overrides.
    """

    disable_tools: list[str] = field(default_factory=list)
    enable_tools: list[str] = field(default_factory=list)
    # None = keep base paths, [] = deny all, [paths...] = replace with these
    allowed_paths: list[Path] | None = None
    add_blocked_paths: list[Path] = field(default_factory=list)
    tool_overrides: dict[str, ToolPermission] = field(default_factory=dict)


@dataclass
class AgentPermissions:
    """Runtime permission state for an agent."""

    base_preset: str
    effective_policy: PermissionPolicy
    tool_permissions: dict[str, ToolPermission] = field(default_factory=dict)
    session_allowances: SessionAllowances = field(default_factory=SessionAllowances)
    ceiling: AgentPermissions | None = None
    parent_agent_id: str | None = None
    depth: int = 0  # 0 = root agent, 1 = child, etc.

    # Backwards compatibility
    @property
    def write_allowances(self) -> SessionAllowances:
        return self.session_allowances

    def is_path_allowed_for_write(self, path: Path) -> bool:
        """Check if a write to this path is allowed without confirmation.

        Combines policy checks with session allowances.
        """
        if isinstance(path, str):
            path = Path(path)

        # YOLO - always allowed
        if self.effective_policy.level == PermissionLevel.YOLO:
            return True

        # SANDBOXED - must be in sandbox
        if self.effective_policy.level == PermissionLevel.SANDBOXED:
            return self.effective_policy.can_write_path(path)

        # TRUSTED - within CWD or session allowances
        if self.effective_policy.is_within_cwd(path):
            return True

        return self.session_allowances.is_path_allowed(path)

    def add_file_allowance(self, path: Path) -> None:
        """Add a file to session allowances (for TRUSTED mode)."""
        self.session_allowances.add_file(path)

    def add_directory_allowance(self, path: Path) -> None:
        """Add a directory to session allowances (for TRUSTED mode)."""
        self.session_allowances.add_directory(path)

    def add_exec_cwd_allowance(self, tool_name: str, cwd: Path) -> None:
        """Add an execution tool allowance for a specific directory."""
        self.session_allowances.add_exec_directory(tool_name, cwd)

    def add_exec_global_allowance(self, tool_name: str) -> None:
        """Add an execution tool allowance globally (any directory)."""
        self.session_allowances.add_exec_global(tool_name)

    def can_grant(self, requested: AgentPermissions) -> bool:
        """Check if this agent can grant requested permissions to subagent.

        Subagent permissions must be strictly more restrictive:
        - Must have lower permission level (YOLO > TRUSTED > SANDBOXED)
        - Can't enable tools this agent has disabled
        - Can't access paths this agent can't access (including allowances)

        Args:
            requested: The permissions requested for the subagent.

        Returns:
            True if this agent can grant the requested permissions.
        """
        level_order = {
            PermissionLevel.SANDBOXED: 0,
            PermissionLevel.TRUSTED: 1,
            PermissionLevel.YOLO: 2,
        }

        # Requested level must be strictly lower than our level
        # (agents can only spawn children with fewer permissions)
        if level_order[requested.effective_policy.level] >= level_order[self.effective_policy.level]:
            return False

        # Check tool permissions - requested can't enable what we disabled
        for tool_name, our_perm in self.tool_permissions.items():
            if not our_perm.enabled:
                their_perm = requested.tool_permissions.get(tool_name)
                if their_perm is None or their_perm.enabled:
                    return False

        # Check path permissions based on our level
        if requested.effective_policy.allowed_paths is not None:
            # Child has restricted paths - verify each is within our access
            for their_path in requested.effective_policy.allowed_paths:
                if not self._can_access_path(their_path):
                    return False
        elif self.effective_policy.level != PermissionLevel.YOLO:
            # Child wants unrestricted but we're not YOLO
            # Only allow if child is TRUSTED (uses CWD-based restrictions)
            if requested.effective_policy.level == PermissionLevel.SANDBOXED:
                return False

        return True

    def _can_access_path(self, path: Path) -> bool:
        """Check if we have access to a path (policy + allowances)."""
        if self.effective_policy.level == PermissionLevel.YOLO:
            return True

        if self.effective_policy._is_path_blocked(path):
            return False

        # For SANDBOXED, check allowed_paths
        if self.effective_policy.level == PermissionLevel.SANDBOXED:
            return self.effective_policy._is_path_allowed(path)

        # For TRUSTED, check CWD + allowances
        if self.effective_policy.is_within_cwd(path):
            return True

        return self.write_allowances.is_path_allowed(path)

    def apply_delta(self, delta: PermissionDelta) -> AgentPermissions:
        """Apply a delta and return new permissions.

        Creates a new AgentPermissions with delta applied.
        Does NOT check ceiling - caller should verify with can_grant().

        Args:
            delta: The permission changes to apply.

        Returns:
            New AgentPermissions with delta applied.
        """
        # Don't allow path changes if frozen (SANDBOXED)
        if self.effective_policy.frozen and delta.allowed_paths is not None:
            raise PermissionError("Cannot modify paths on frozen (sandboxed) permissions")

        new_tool_perms = copy.deepcopy(self.tool_permissions)

        if delta.allowed_paths is not None:
            new_allowed = copy.deepcopy(delta.allowed_paths)
        elif self.effective_policy.allowed_paths is not None:
            new_allowed = copy.deepcopy(self.effective_policy.allowed_paths)
        else:
            new_allowed = None

        new_blocked = copy.deepcopy(self.effective_policy.blocked_paths) + copy.deepcopy(delta.add_blocked_paths)

        # Apply tool disables
        for tool_name in delta.disable_tools:
            if tool_name in new_tool_perms:
                new_tool_perms[tool_name].enabled = False
            else:
                new_tool_perms[tool_name] = ToolPermission(enabled=False)

        # Apply tool enables
        for tool_name in delta.enable_tools:
            if tool_name in new_tool_perms:
                new_tool_perms[tool_name].enabled = True
            else:
                new_tool_perms[tool_name] = ToolPermission(enabled=True)

        # Apply tool overrides
        for tool_name, override in delta.tool_overrides.items():
            new_tool_perms[tool_name] = copy.deepcopy(override)

        new_policy = PermissionPolicy(
            level=self.effective_policy.level,
            allowed_paths=new_allowed,
            blocked_paths=new_blocked,
            cwd=self.effective_policy.cwd,
            frozen=self.effective_policy.frozen,
        )

        return AgentPermissions(
            base_preset=self.base_preset,
            effective_policy=new_policy,
            tool_permissions=new_tool_perms,
            session_allowances=copy.deepcopy(self.session_allowances),
            ceiling=self.ceiling,
            parent_agent_id=self.parent_agent_id,
            depth=self.depth,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for RPC transport."""
        result: dict[str, Any] = {
            "base_preset": self.base_preset,
            "effective_policy": self.effective_policy.to_dict(),
            "tool_permissions": {
                name: perm.to_dict() for name, perm in self.tool_permissions.items()
            },
            "write_allowances": self.write_allowances.to_dict(),
            "depth": self.depth,
        }
        if self.parent_agent_id is not None:
            result["parent_agent_id"] = self.parent_agent_id
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentPermissions:
        """Deserialize from dict."""
        return cls(
            base_preset=data["base_preset"],
            effective_policy=PermissionPolicy.from_dict(data["effective_policy"]),
            tool_permissions={
                name: ToolPermission.from_dict(perm)
                for name, perm in data.get("tool_permissions", {}).items()
            },
            session_allowances=SessionAllowances.from_dict(data.get("write_allowances", {})),
            ceiling=None,
            parent_agent_id=data.get("parent_agent_id"),
            depth=data.get("depth", 0),
        )


# Built-in permission presets (WORKER removed - use sandboxed with tool deltas)
def _create_builtin_presets() -> dict[str, PermissionPreset]:
    """Create built-in presets. Function to avoid Path.cwd() at import time."""
    return {
        "yolo": PermissionPreset(
            name="yolo",
            level=PermissionLevel.YOLO,
            description="Full access, no confirmations",
        ),
        "trusted": PermissionPreset(
            name="trusted",
            level=PermissionLevel.TRUSTED,
            description="CWD auto-allowed, prompts for other paths",
        ),
        "sandboxed": PermissionPreset(
            name="sandboxed",
            level=PermissionLevel.SANDBOXED,
            description="Immutable sandbox, no execution/agent management",
            network_access=False,
            tool_permissions={
                # Execution tools disabled
                "bash": ToolPermission(enabled=False),
                "run_python": ToolPermission(enabled=False),
                # Agent management disabled
                "nexus_send": ToolPermission(enabled=False),
                "nexus_create": ToolPermission(enabled=False),
                "nexus_destroy": ToolPermission(enabled=False),
                "nexus_shutdown": ToolPermission(enabled=False),
                "nexus_cancel": ToolPermission(enabled=False),
                "nexus_status": ToolPermission(enabled=False),
            },
        ),
    }


def get_builtin_presets() -> dict[str, PermissionPreset]:
    """Get built-in permission presets."""
    return _create_builtin_presets()


def resolve_preset(
    preset_name: str,
    custom_presets: dict[str, PermissionPreset] | None = None,
    cwd: Path | None = None,
) -> AgentPermissions:
    """Resolve a preset name to AgentPermissions.

    Args:
        preset_name: Name of preset to resolve.
        custom_presets: Optional custom presets from config.
        cwd: Working directory / sandbox root. Defaults to Path.cwd().
            For SANDBOXED presets, this is the only path the agent can access.

    Returns:
        AgentPermissions based on the preset.

    Raises:
        ValueError: If preset not found.
    """
    # Handle legacy "worker" preset by mapping to sandboxed
    if preset_name == "worker":
        preset_name = "sandboxed"

    # Check custom presets first
    if custom_presets and preset_name in custom_presets:
        preset = custom_presets[preset_name]
    else:
        builtin = get_builtin_presets()
        if preset_name not in builtin:
            valid = list(builtin.keys())
            if custom_presets:
                valid.extend(custom_presets.keys())
            raise ValueError(f"Unknown preset: {preset_name}. Valid: {valid}")
        preset = builtin[preset_name]

    effective_cwd = cwd if cwd is not None else Path.cwd()

    # Determine allowed_paths and frozen status
    if preset.level == PermissionLevel.SANDBOXED:
        # Sandboxed: Use provided cwd, or preset paths, or default to actual CWD
        # The cwd parameter overrides preset.allowed_paths for sandboxed agents
        if cwd is not None:
            allowed_paths = [cwd]
        elif preset.allowed_paths:
            allowed_paths = preset.allowed_paths
        else:
            allowed_paths = [effective_cwd]
        frozen = True
    else:
        # YOLO and TRUSTED: Use preset paths (usually None = unrestricted)
        allowed_paths = preset.allowed_paths
        frozen = False

    policy = PermissionPolicy(
        level=preset.level,
        allowed_paths=allowed_paths,
        blocked_paths=list(preset.blocked_paths),
        cwd=effective_cwd,
        frozen=frozen,
    )

    return AgentPermissions(
        base_preset=preset_name,
        effective_policy=policy,
        tool_permissions=copy.deepcopy(preset.tool_permissions),
        session_allowances=SessionAllowances(),
    )


def load_custom_presets_from_config(
    config_presets: dict[str, Any],
) -> dict[str, PermissionPreset]:
    """Convert config presets to PermissionPreset objects.

    Args:
        config_presets: Dict from config.permissions.presets

    Returns:
        Dict mapping preset names to PermissionPreset objects.
    """
    if not config_presets:
        return {}

    builtin = get_builtin_presets()
    custom: dict[str, PermissionPreset] = {}

    for preset_name, preset_config in config_presets.items():
        extends = preset_config.get("extends")
        if extends:
            # Handle legacy "worker" reference
            if extends == "worker":
                extends = "sandboxed"

            if extends in builtin:
                base = builtin[extends]
            elif extends in custom:
                base = custom[extends]
            else:
                raise ValueError(f"Preset '{preset_name}' extends unknown preset '{extends}'")
            level = base.level
            base_allowed_paths = base.allowed_paths
            base_blocked_paths = list(base.blocked_paths)
            base_tool_perms = copy.deepcopy(base.tool_permissions)
            base_timeout = base.default_tool_timeout
        else:
            level = PermissionLevel.TRUSTED
            base_allowed_paths = None
            base_blocked_paths = []
            base_tool_perms = {}
            base_timeout = 30.0

        description = preset_config.get("description", "")

        allowed_paths_config = preset_config.get("allowed_paths")
        if allowed_paths_config is not None:
            allowed_paths = [Path(p) for p in allowed_paths_config]
        else:
            allowed_paths = base_allowed_paths

        blocked_paths_config = preset_config.get("blocked_paths", [])
        blocked_paths = base_blocked_paths + [Path(p) for p in blocked_paths_config]

        tool_perms = copy.deepcopy(base_tool_perms)
        for tool_name, tool_config in preset_config.get("tool_permissions", {}).items():
            tool_perms[tool_name] = ToolPermission(
                enabled=tool_config.get("enabled", True),
                allowed_paths=[Path(p) for p in tool_config.get("allowed_paths", [])] if tool_config.get("allowed_paths") else None,
                timeout=tool_config.get("timeout"),
                requires_confirmation=tool_config.get("requires_confirmation"),
            )

        timeout = preset_config.get("default_tool_timeout", base_timeout)

        custom[preset_name] = PermissionPreset(
            name=preset_name,
            level=level,
            description=description,
            allowed_paths=allowed_paths,
            blocked_paths=blocked_paths,
            tool_permissions=tool_perms,
            default_tool_timeout=timeout,
        )

    return custom
