"""Permission levels for NEXUS3 agents.

This module defines the permission system for controlling agent access.
Three permission levels are supported:
- yolo: Full access, no confirmations required
- trusted: Confirmations required for destructive actions (default)
- sandboxed: Limited paths, restricted network access

The PermissionPolicy class provides methods to check if specific actions
are allowed based on the permission level and configured path restrictions.

Additional types for the extended permission system:
- ToolPermission: Per-tool permission configuration
- PermissionPreset: Named permission configuration preset
- PermissionDelta: Changes to apply to a base preset
- AgentPermissions: Runtime permission state for an agent

Built-in presets available via get_builtin_presets():
- yolo: Full access, no confirmations
- trusted: Confirmations for destructive actions (default)
- sandboxed: Limited to CWD, no network
- worker: Minimal permissions for background workers
"""

from __future__ import annotations

import copy
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
# Includes both action categories and specific tool names
DESTRUCTIVE_ACTIONS = frozenset({
    "delete",
    "remove",
    "overwrite",
    "write",
    "execute",
    "run_command",
    "shutdown",
    # Specific tool names
    "write_file",
    "nexus_destroy",
    "nexus_shutdown",
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

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for RPC transport."""
        result: dict[str, Any] = {"level": self.level.value}
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
        )


@dataclass
class ToolPermission:
    """Per-tool permission configuration."""

    enabled: bool = True
    allowed_paths: list[Path] | None = None  # None = inherit from preset
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
    """Named permission configuration preset."""

    name: str
    level: PermissionLevel
    description: str = ""
    allowed_paths: list[Path] | None = None  # None = unrestricted
    blocked_paths: list[Path] = field(default_factory=list)
    network_access: bool = True
    tool_permissions: dict[str, ToolPermission] = field(default_factory=dict)
    default_tool_timeout: float = 30.0


@dataclass
class PermissionDelta:
    """Changes to apply to a base preset."""

    disable_tools: list[str] = field(default_factory=list)
    enable_tools: list[str] = field(default_factory=list)
    allowed_paths: list[Path] | None = None  # Replaces base if set
    add_blocked_paths: list[Path] = field(default_factory=list)
    tool_overrides: dict[str, ToolPermission] = field(default_factory=dict)
    # Note: network_access is controlled by permission level (SANDBOXED = no network)


@dataclass
class AgentPermissions:
    """Runtime permission state for an agent."""

    base_preset: str
    effective_policy: PermissionPolicy
    tool_permissions: dict[str, ToolPermission] = field(default_factory=dict)
    ceiling: AgentPermissions | None = None
    parent_agent_id: str | None = None
    depth: int = 0  # 0 = root agent, 1 = child, 2 = grandchild, etc.

    def can_grant(self, requested: AgentPermissions) -> bool:
        """Check if this agent can grant requested permissions to subagent.

        Subagent permissions must be equal or more restrictive:
        - Can't have more permissive level (YOLO > TRUSTED > SANDBOXED)
        - Can't enable tools this agent has disabled
        - Can't access paths this agent can't access

        Args:
            requested: The permissions requested for the subagent.

        Returns:
            True if this agent can grant the requested permissions.
        """
        # Level ordering: SANDBOXED < TRUSTED < YOLO
        level_order = {
            PermissionLevel.SANDBOXED: 0,
            PermissionLevel.TRUSTED: 1,
            PermissionLevel.YOLO: 2,
        }

        # Requested level can't exceed our level
        if level_order[requested.effective_policy.level] > level_order[self.effective_policy.level]:
            return False

        # Check tool permissions - requested can't enable what we disabled
        for tool_name, our_perm in self.tool_permissions.items():
            if not our_perm.enabled:
                their_perm = requested.tool_permissions.get(tool_name)
                if their_perm is None or their_perm.enabled:
                    return False

        # Check path permissions
        if self.effective_policy.allowed_paths is not None:
            # We have path restrictions
            if requested.effective_policy.allowed_paths is None:
                # They want unrestricted - not allowed
                return False
            # Check each of their paths is within our allowed paths
            for their_path in requested.effective_policy.allowed_paths:
                if not self.effective_policy._is_path_allowed(their_path):
                    return False

        return True

    def apply_delta(self, delta: PermissionDelta) -> AgentPermissions:
        """Apply a delta and return new permissions.

        Creates a new AgentPermissions with delta applied.
        Does NOT check ceiling - caller should verify with can_grant().

        Args:
            delta: The permission changes to apply.

        Returns:
            New AgentPermissions with delta applied.
        """
        # Start with copies of current state
        new_tool_perms = copy.deepcopy(self.tool_permissions)
        # Preserve empty list [] as empty (restricted to nothing), don't convert to None (unrestricted)
        # Use deepcopy for consistency with the rest of the permission system,
        # even though Path objects are immutable
        if delta.allowed_paths is not None:
            new_allowed = copy.deepcopy(delta.allowed_paths)
        elif self.effective_policy.allowed_paths is not None:
            new_allowed = copy.deepcopy(self.effective_policy.allowed_paths)
        else:
            new_allowed = None
        new_blocked = copy.deepcopy(self.effective_policy.blocked_paths) + copy.deepcopy(delta.add_blocked_paths)
        # Note: network_access is derived from level, not stored separately

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

        # Apply tool overrides (deep copy to avoid sharing between agents)
        for tool_name, override in delta.tool_overrides.items():
            new_tool_perms[tool_name] = copy.deepcopy(override)

        # Create new policy
        new_policy = PermissionPolicy(
            level=self.effective_policy.level,
            allowed_paths=new_allowed,
            blocked_paths=new_blocked,
        )

        return AgentPermissions(
            base_preset=self.base_preset,
            effective_policy=new_policy,
            tool_permissions=new_tool_perms,
            ceiling=self.ceiling,
            parent_agent_id=self.parent_agent_id,
            depth=self.depth,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for RPC transport.

        Used when passing parent permissions for ceiling enforcement
        in create_agent RPC calls.
        """
        result: dict[str, Any] = {
            "base_preset": self.base_preset,
            "effective_policy": self.effective_policy.to_dict(),
            "tool_permissions": {
                name: perm.to_dict() for name, perm in self.tool_permissions.items()
            },
            "depth": self.depth,
        }
        if self.parent_agent_id is not None:
            result["parent_agent_id"] = self.parent_agent_id
        # Note: ceiling is not serialized to avoid circular references
        # The receiving end will set this agent as the ceiling
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentPermissions:
        """Deserialize from dict.

        Creates an AgentPermissions from RPC data.
        """
        return cls(
            base_preset=data["base_preset"],
            effective_policy=PermissionPolicy.from_dict(data["effective_policy"]),
            tool_permissions={
                name: ToolPermission.from_dict(perm)
                for name, perm in data.get("tool_permissions", {}).items()
            },
            ceiling=None,  # Not serialized; caller sets if needed
            parent_agent_id=data.get("parent_agent_id"),
            depth=data.get("depth", 0),
        )


# Built-in permission presets
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
            description="Confirmations for destructive actions (default)",
        ),
        "sandboxed": PermissionPreset(
            name="sandboxed",
            level=PermissionLevel.SANDBOXED,
            description="Limited to CWD, no network",
            network_access=False,
            tool_permissions={
                "nexus_send": ToolPermission(enabled=False),
                "nexus_create": ToolPermission(enabled=False),
                "nexus_destroy": ToolPermission(enabled=False),
                "nexus_shutdown": ToolPermission(enabled=False),
            },
        ),
        "worker": PermissionPreset(
            name="worker",
            level=PermissionLevel.SANDBOXED,
            description="Minimal permissions for background workers",
            network_access=False,
            tool_permissions={
                "write_file": ToolPermission(enabled=False),
                "nexus_create": ToolPermission(enabled=False),
                "nexus_destroy": ToolPermission(enabled=False),
                "nexus_shutdown": ToolPermission(enabled=False),
            },
        ),
    }


def get_builtin_presets() -> dict[str, PermissionPreset]:
    """Get built-in permission presets."""
    return _create_builtin_presets()


def resolve_preset(
    preset_name: str,
    custom_presets: dict[str, PermissionPreset] | None = None,
) -> AgentPermissions:
    """Resolve a preset name to AgentPermissions.

    Args:
        preset_name: Name of preset to resolve.
        custom_presets: Optional custom presets from config.

    Returns:
        AgentPermissions based on the preset.

    Raises:
        ValueError: If preset not found.
    """
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

    # Create policy from preset
    allowed_paths = preset.allowed_paths
    if allowed_paths is None and preset.level == PermissionLevel.SANDBOXED:
        # Sandboxed defaults to CWD
        allowed_paths = [Path.cwd()]

    policy = PermissionPolicy(
        level=preset.level,
        allowed_paths=allowed_paths,
        blocked_paths=list(preset.blocked_paths),
    )

    # Deep copy tool_permissions to prevent cross-agent mutation
    return AgentPermissions(
        base_preset=preset_name,
        effective_policy=policy,
        tool_permissions=copy.deepcopy(preset.tool_permissions),
    )


def load_custom_presets_from_config(
    config_presets: dict[str, Any],
) -> dict[str, PermissionPreset]:
    """Convert config presets to PermissionPreset objects.

    This function converts permission presets from the config.json format
    to runtime PermissionPreset objects that can be used with resolve_preset().

    Args:
        config_presets: Dict from config.permissions.presets
            Each value should have: extends?, description?, allowed_paths?, blocked_paths?,
            tool_permissions?, default_tool_timeout?

    Returns:
        Dict mapping preset names to PermissionPreset objects.
    """
    if not config_presets:
        return {}

    builtin = get_builtin_presets()
    custom: dict[str, PermissionPreset] = {}

    for preset_name, preset_config in config_presets.items():
        # Get base preset to extend
        extends = preset_config.get("extends")
        if extends:
            # Must extend a builtin or already-processed custom preset
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
            # Default to trusted if not extending
            level = PermissionLevel.TRUSTED
            base_allowed_paths = None
            base_blocked_paths = []
            base_tool_perms = {}
            base_timeout = 30.0

        # Override with config values
        description = preset_config.get("description", "")

        # Handle allowed_paths
        allowed_paths_config = preset_config.get("allowed_paths")
        if allowed_paths_config is not None:
            allowed_paths = [Path(p) for p in allowed_paths_config]
        else:
            allowed_paths = base_allowed_paths

        # Handle blocked_paths (append to base)
        blocked_paths_config = preset_config.get("blocked_paths", [])
        blocked_paths = base_blocked_paths + [Path(p) for p in blocked_paths_config]

        # Handle tool_permissions (merge with base, deep copy to isolate)
        tool_perms = copy.deepcopy(base_tool_perms)
        for tool_name, tool_config in preset_config.get("tool_permissions", {}).items():
            tool_perms[tool_name] = ToolPermission(
                enabled=tool_config.get("enabled", True),
                allowed_paths=[Path(p) for p in tool_config.get("allowed_paths", [])] if tool_config.get("allowed_paths") else None,
                timeout=tool_config.get("timeout"),
                requires_confirmation=tool_config.get("requires_confirmation"),
            )

        # Handle timeout
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
