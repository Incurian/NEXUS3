"""Permission presets and tool permissions for NEXUS3.

This module defines:
- ToolPermission: Per-tool configuration
- PermissionPreset: Named preset configurations
- PermissionDelta: Changes to apply to a preset
- Built-in presets (yolo, trusted, sandboxed)
- Custom preset loading from config
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nexus3.core.policy import PermissionLevel


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
        allowed = data.get("allowed_paths")
        return cls(
            enabled=data.get("enabled", True),
            allowed_paths=[Path(p) for p in allowed] if allowed else None,
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
                "bash_safe": ToolPermission(enabled=False),
                "shell_UNSAFE": ToolPermission(enabled=False),
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
            tool_allowed = tool_config.get("allowed_paths")
            tool_perms[tool_name] = ToolPermission(
                enabled=tool_config.get("enabled", True),
                allowed_paths=[Path(p) for p in tool_allowed] if tool_allowed else None,
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
