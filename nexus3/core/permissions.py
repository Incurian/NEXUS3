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
from pathlib import Path
from typing import Any

# Import from split modules
from nexus3.core.allowances import SessionAllowances, WriteAllowances
from nexus3.core.policy import (
    DESTRUCTIVE_ACTIONS,
    NETWORK_ACTIONS,
    SAFE_ACTIONS,
    SANDBOXED_DISABLED_TOOLS,
    ConfirmationResult,
    PermissionLevel,
    PermissionPolicy,
)
from nexus3.core.presets import (
    PermissionDelta,
    PermissionPreset,
    ToolPermission,
    get_builtin_presets,
    load_custom_presets_from_config,
)

# Re-export everything for backwards compatibility
__all__ = [
    # From policy.py
    "PermissionLevel",
    "ConfirmationResult",
    "DESTRUCTIVE_ACTIONS",
    "SAFE_ACTIONS",
    "NETWORK_ACTIONS",
    "SANDBOXED_DISABLED_TOOLS",
    "PermissionPolicy",
    # From allowances.py
    "SessionAllowances",
    "WriteAllowances",
    # From presets.py
    "ToolPermission",
    "PermissionPreset",
    "PermissionDelta",
    "get_builtin_presets",
    "load_custom_presets_from_config",
    # From this module
    "AgentPermissions",
    "resolve_preset",
]


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
        our_level = level_order[self.effective_policy.level]
        their_level = level_order[requested.effective_policy.level]
        if their_level >= our_level:
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

        new_blocked = (
            copy.deepcopy(self.effective_policy.blocked_paths)
            + copy.deepcopy(delta.add_blocked_paths)
        )

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
