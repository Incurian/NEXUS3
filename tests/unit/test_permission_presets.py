"""Unit tests for permission presets and delegation in nexus3.core.permissions module.

Tests for:
- ToolPermission: Per-tool permission settings
- PermissionPreset: Named permission configurations
- PermissionDelta: Changes to apply to permissions
- AgentPermissions: Runtime permissions with can_grant() and apply_delta()
- get_builtin_presets(): Returns built-in preset definitions
- resolve_preset(): Resolves preset names to AgentPermissions
"""

import pytest
from pathlib import Path

from nexus3.core.permissions import (
    PermissionLevel,
    PermissionPolicy,
    ToolPermission,
    PermissionPreset,
    PermissionDelta,
    AgentPermissions,
    get_builtin_presets,
    resolve_preset,
)


class TestToolPermission:
    """Tests for ToolPermission dataclass."""

    def test_defaults(self):
        """Default values: enabled=True, others None."""
        perm = ToolPermission()
        assert perm.enabled is True
        assert perm.allowed_paths is None
        assert perm.timeout is None
        assert perm.requires_confirmation is None

    def test_custom_enabled_false(self):
        """Can disable a tool."""
        perm = ToolPermission(enabled=False)
        assert perm.enabled is False

    def test_custom_allowed_paths(self, tmp_path):
        """Can set custom allowed_paths."""
        perm = ToolPermission(allowed_paths=[tmp_path])
        assert perm.allowed_paths == [tmp_path]

    def test_custom_timeout(self):
        """Can set custom timeout."""
        perm = ToolPermission(timeout=60.0)
        assert perm.timeout == 60.0

    def test_custom_requires_confirmation(self):
        """Can set requires_confirmation."""
        perm = ToolPermission(requires_confirmation=True)
        assert perm.requires_confirmation is True

    def test_all_custom_values(self, tmp_path):
        """Can set all values at once."""
        perm = ToolPermission(
            enabled=False,
            allowed_paths=[tmp_path],
            timeout=10.0,
            requires_confirmation=True,
        )
        assert perm.enabled is False
        assert perm.allowed_paths == [tmp_path]
        assert perm.timeout == 10.0
        assert perm.requires_confirmation is True


class TestPermissionPreset:
    """Tests for PermissionPreset dataclass."""

    def test_default_preset_creation(self):
        """Default preset has sensible defaults."""
        preset = PermissionPreset(
            name="test",
            level=PermissionLevel.TRUSTED,
        )
        assert preset.name == "test"
        assert preset.level == PermissionLevel.TRUSTED
        assert preset.description == ""
        assert preset.tool_permissions == {}
        assert preset.allowed_paths is None
        assert preset.blocked_paths == []
        assert preset.network_access is True

    def test_preset_with_tool_permissions(self):
        """Preset with tool_permissions dict."""
        tool_perm = ToolPermission(enabled=False)
        preset = PermissionPreset(
            name="restricted",
            level=PermissionLevel.SANDBOXED,
            tool_permissions={"write_file": tool_perm},
        )
        assert "write_file" in preset.tool_permissions
        assert preset.tool_permissions["write_file"].enabled is False

    def test_preset_with_allowed_paths(self, tmp_path):
        """Preset with allowed_paths restriction."""
        preset = PermissionPreset(
            name="project-only",
            level=PermissionLevel.TRUSTED,
            allowed_paths=[tmp_path],
        )
        assert preset.allowed_paths == [tmp_path]

    def test_preset_with_blocked_paths(self, tmp_path):
        """Preset with blocked_paths."""
        secret_dir = tmp_path / ".secret"
        preset = PermissionPreset(
            name="no-secrets",
            level=PermissionLevel.YOLO,
            blocked_paths=[secret_dir],
        )
        assert secret_dir in preset.blocked_paths

    def test_preset_with_description(self):
        """Preset with description."""
        preset = PermissionPreset(
            name="worker",
            level=PermissionLevel.SANDBOXED,
            description="Limited permissions for worker agents",
        )
        assert preset.description == "Limited permissions for worker agents"

    def test_preset_with_network_access_disabled(self):
        """Preset with network access disabled."""
        preset = PermissionPreset(
            name="offline",
            level=PermissionLevel.TRUSTED,
            network_access=False,
        )
        assert preset.network_access is False

    def test_preset_has_default_tool_timeout(self):
        """Preset has default_tool_timeout field."""
        preset = PermissionPreset(
            name="test",
            level=PermissionLevel.TRUSTED,
        )
        assert preset.default_tool_timeout == 30.0

    def test_preset_custom_tool_timeout(self):
        """Preset can have custom default_tool_timeout."""
        preset = PermissionPreset(
            name="quick",
            level=PermissionLevel.TRUSTED,
            default_tool_timeout=5.0,
        )
        assert preset.default_tool_timeout == 5.0


class TestPermissionDelta:
    """Tests for PermissionDelta dataclass."""

    def test_empty_delta_no_changes(self):
        """Empty delta represents no changes."""
        delta = PermissionDelta()
        assert delta.disable_tools == []
        assert delta.enable_tools == []
        assert delta.allowed_paths is None
        assert delta.add_blocked_paths == []
        assert delta.tool_overrides == {}

    def test_delta_with_disable_tools(self):
        """Delta can disable specific tools."""
        delta = PermissionDelta(disable_tools=["write_file", "nexus_shutdown"])
        assert "write_file" in delta.disable_tools
        assert "nexus_shutdown" in delta.disable_tools

    def test_delta_with_enable_tools(self):
        """Delta can enable specific tools."""
        delta = PermissionDelta(enable_tools=["read_file"])
        assert "read_file" in delta.enable_tools

    def test_delta_with_allowed_paths_replacement(self, tmp_path):
        """Delta can replace allowed_paths."""
        new_path = tmp_path / "restricted"
        delta = PermissionDelta(allowed_paths=[new_path])
        assert delta.allowed_paths == [new_path]

    def test_delta_with_add_blocked_paths(self, tmp_path):
        """Delta can add blocked paths."""
        secret_path = tmp_path / ".env"
        delta = PermissionDelta(add_blocked_paths=[secret_path])
        assert secret_path in delta.add_blocked_paths

    def test_delta_with_tool_overrides(self):
        """Delta can provide tool-specific overrides."""
        override = ToolPermission(timeout=5.0)
        delta = PermissionDelta(tool_overrides={"slow_tool": override})
        assert "slow_tool" in delta.tool_overrides
        assert delta.tool_overrides["slow_tool"].timeout == 5.0

    def test_delta_with_multiple_changes(self, tmp_path):
        """Delta can combine multiple changes."""
        delta = PermissionDelta(
            disable_tools=["dangerous_tool"],
            add_blocked_paths=[tmp_path / ".secrets"],
            tool_overrides={"write_file": ToolPermission(requires_confirmation=True)},
        )
        assert delta.disable_tools == ["dangerous_tool"]
        assert len(delta.add_blocked_paths) == 1
        assert delta.tool_overrides["write_file"].requires_confirmation is True

    # Note: network_access was removed from PermissionDelta
    # Network access is now derived from permission level (SANDBOXED = no network)


class TestAgentPermissionsCanGrant:
    """Tests for AgentPermissions.can_grant() method.

    Hierarchy rules:
    - YOLO > TRUSTED > SANDBOXED
    - Can only grant equal or lower permissions
    - Cannot enable tools parent disabled
    - Cannot access paths parent cannot access
    """

    def test_same_level_cannot_grant_same_level(self):
        """Same level cannot grant same level (lower only policy)."""
        trusted = resolve_preset("trusted")
        other_trusted = resolve_preset("trusted")
        assert trusted.can_grant(other_trusted) is False

    def test_yolo_can_grant_trusted(self):
        """YOLO can grant TRUSTED (lower level)."""
        yolo = resolve_preset("yolo")
        trusted = resolve_preset("trusted")
        assert yolo.can_grant(trusted) is True

    def test_yolo_can_grant_sandboxed(self):
        """YOLO can grant SANDBOXED (lowest level)."""
        yolo = resolve_preset("yolo")
        sandboxed = resolve_preset("sandboxed")
        assert yolo.can_grant(sandboxed) is True

    def test_trusted_can_grant_sandboxed(self):
        """TRUSTED can grant SANDBOXED (lower level)."""
        trusted = resolve_preset("trusted")
        sandboxed = resolve_preset("sandboxed")
        assert trusted.can_grant(sandboxed) is True

    def test_trusted_cannot_grant_yolo(self):
        """TRUSTED cannot grant YOLO (higher level)."""
        trusted = resolve_preset("trusted")
        yolo = resolve_preset("yolo")
        assert trusted.can_grant(yolo) is False

    def test_sandboxed_cannot_grant_trusted(self):
        """SANDBOXED cannot grant TRUSTED (higher level)."""
        sandboxed = resolve_preset("sandboxed")
        trusted = resolve_preset("trusted")
        assert sandboxed.can_grant(trusted) is False

    def test_sandboxed_cannot_grant_yolo(self):
        """SANDBOXED cannot grant YOLO (highest level)."""
        sandboxed = resolve_preset("sandboxed")
        yolo = resolve_preset("yolo")
        assert sandboxed.can_grant(yolo) is False

    def test_cannot_enable_tools_parent_disabled(self):
        """Cannot grant permissions with tools enabled that parent disabled."""
        # Parent with write_file disabled
        parent_policy = PermissionPolicy(level=PermissionLevel.TRUSTED)
        parent = AgentPermissions(
            base_preset="trusted",
            effective_policy=parent_policy,
            tool_permissions={"write_file": ToolPermission(enabled=False)},
        )
        # Child trying to have write_file enabled (default is enabled)
        child_policy = PermissionPolicy(level=PermissionLevel.TRUSTED)
        child = AgentPermissions(
            base_preset="trusted",
            effective_policy=child_policy,
            tool_permissions={},  # write_file not in dict means enabled by default
        )
        assert parent.can_grant(child) is False

    def test_cannot_access_paths_parent_cannot_access(self, tmp_path):
        """Cannot grant access to paths parent cannot access."""
        allowed_dir = tmp_path / "allowed"
        allowed_dir.mkdir()
        restricted_dir = tmp_path / "restricted"
        restricted_dir.mkdir()

        # Parent can only access allowed_dir
        parent_policy = PermissionPolicy(
            level=PermissionLevel.TRUSTED,
            allowed_paths=[allowed_dir],
        )
        parent = AgentPermissions(
            base_preset="trusted",
            effective_policy=parent_policy,
        )
        # Child trying to access restricted_dir too
        child_policy = PermissionPolicy(
            level=PermissionLevel.TRUSTED,
            allowed_paths=[allowed_dir, restricted_dir],
        )
        child = AgentPermissions(
            base_preset="trusted",
            effective_policy=child_policy,
        )
        assert parent.can_grant(child) is False

    def test_can_grant_subset_of_allowed_paths(self, tmp_path, monkeypatch):
        """Can grant if child paths are subset of parent paths in CWD."""
        # For TRUSTED, path checking uses CWD + allowances, not just allowed_paths
        parent_dir = tmp_path / "project"
        parent_dir.mkdir()
        child_dir = parent_dir / "subdir"
        child_dir.mkdir()

        # Set CWD to parent_dir so paths are within CWD
        monkeypatch.chdir(parent_dir)

        parent_policy = PermissionPolicy(
            level=PermissionLevel.TRUSTED,
            cwd=parent_dir,  # CWD is parent_dir
        )
        parent = AgentPermissions(
            base_preset="trusted",
            effective_policy=parent_policy,
        )
        # Child with restricted paths within parent's CWD
        child_policy = PermissionPolicy(
            level=PermissionLevel.SANDBOXED,
            allowed_paths=[child_dir],
            cwd=parent_dir,
        )
        child = AgentPermissions(
            base_preset="sandboxed",
            effective_policy=child_policy,
        )
        assert parent.can_grant(child) is True

    def test_can_grant_more_restricted_tools(self):
        """Can grant if child has lower level with more tool restrictions."""
        # YOLO parent granting TRUSTED child with tool restrictions
        parent_policy = PermissionPolicy(level=PermissionLevel.YOLO)
        parent = AgentPermissions(
            base_preset="yolo",
            effective_policy=parent_policy,
            tool_permissions={},  # All tools enabled by default
        )
        child_policy = PermissionPolicy(level=PermissionLevel.TRUSTED)
        child = AgentPermissions(
            base_preset="trusted",
            effective_policy=child_policy,
            tool_permissions={"write_file": ToolPermission(enabled=False)},
        )
        assert parent.can_grant(child) is True

    def test_parent_with_unrestricted_paths_can_grant_restricted(self, tmp_path, monkeypatch):
        """YOLO parent with unrestricted paths can grant SANDBOXED child with restrictions."""
        # Set CWD to tmp_path so child's paths are within CWD
        monkeypatch.chdir(tmp_path)

        # YOLO parent has no path restrictions (allowed_paths=None)
        parent_policy = PermissionPolicy(level=PermissionLevel.YOLO, cwd=tmp_path)
        parent = AgentPermissions(
            base_preset="yolo",
            effective_policy=parent_policy,
        )
        # SANDBOXED child has path restrictions within CWD
        child_policy = PermissionPolicy(
            level=PermissionLevel.SANDBOXED,
            allowed_paths=[tmp_path],
            cwd=tmp_path,
        )
        child = AgentPermissions(
            base_preset="sandboxed",
            effective_policy=child_policy,
        )
        assert parent.can_grant(child) is True

    def test_yolo_parent_can_grant_trusted_child_unrestricted(self, tmp_path):
        """YOLO parent can grant TRUSTED child with unrestricted access."""
        # YOLO parent can grant any lower level
        parent_policy = PermissionPolicy(
            level=PermissionLevel.YOLO,
            allowed_paths=[tmp_path],  # Even with restrictions
        )
        parent = AgentPermissions(
            base_preset="yolo",
            effective_policy=parent_policy,
        )
        child_policy = PermissionPolicy(
            level=PermissionLevel.TRUSTED,
            allowed_paths=None,  # Unrestricted (uses CWD)
        )
        child = AgentPermissions(
            base_preset="trusted",
            effective_policy=child_policy,
        )
        # YOLO parent can grant TRUSTED child
        assert parent.can_grant(child) is True


class TestAgentPermissionsApplyDelta:
    """Tests for AgentPermissions.apply_delta() method."""

    def test_disable_a_tool(self):
        """apply_delta can disable a tool."""
        perms = resolve_preset("trusted")
        delta = PermissionDelta(disable_tools=["write_file"])
        new_perms = perms.apply_delta(delta)

        assert new_perms.tool_permissions["write_file"].enabled is False
        # Original unchanged - check it doesn't have the disabled tool
        assert "write_file" not in perms.tool_permissions or \
               perms.tool_permissions.get("write_file", ToolPermission()).enabled is True

    def test_enable_a_tool(self):
        """apply_delta can enable a tool."""
        # Start with a preset that has a tool disabled
        policy = PermissionPolicy(level=PermissionLevel.TRUSTED)
        perms = AgentPermissions(
            base_preset="trusted",
            effective_policy=policy,
            tool_permissions={"write_file": ToolPermission(enabled=False)},
        )
        delta = PermissionDelta(enable_tools=["write_file"])
        new_perms = perms.apply_delta(delta)

        assert new_perms.tool_permissions["write_file"].enabled is True

    def test_replace_allowed_paths(self, tmp_path):
        """apply_delta can replace allowed_paths."""
        old_path = tmp_path / "old"
        old_path.mkdir()
        new_path = tmp_path / "new"
        new_path.mkdir()

        policy = PermissionPolicy(
            level=PermissionLevel.TRUSTED,
            allowed_paths=[old_path],
        )
        perms = AgentPermissions(
            base_preset="trusted",
            effective_policy=policy,
        )
        delta = PermissionDelta(allowed_paths=[new_path])
        new_perms = perms.apply_delta(delta)

        assert new_perms.effective_policy.allowed_paths == [new_path]
        # Original unchanged
        assert perms.effective_policy.allowed_paths == [old_path]

    def test_add_blocked_paths(self, tmp_path):
        """apply_delta can add blocked paths."""
        secret_path = tmp_path / ".secret"

        perms = resolve_preset("trusted")
        delta = PermissionDelta(add_blocked_paths=[secret_path])
        new_perms = perms.apply_delta(delta)

        assert secret_path in new_perms.effective_policy.blocked_paths

    def test_add_blocked_paths_preserves_existing(self, tmp_path):
        """apply_delta adds to existing blocked paths."""
        existing_blocked = tmp_path / ".env"
        new_blocked = tmp_path / ".secret"

        policy = PermissionPolicy(
            level=PermissionLevel.TRUSTED,
            blocked_paths=[existing_blocked],
        )
        perms = AgentPermissions(
            base_preset="trusted",
            effective_policy=policy,
        )
        delta = PermissionDelta(add_blocked_paths=[new_blocked])
        new_perms = perms.apply_delta(delta)

        assert existing_blocked in new_perms.effective_policy.blocked_paths
        assert new_blocked in new_perms.effective_policy.blocked_paths

    def test_tool_override(self):
        """apply_delta can apply tool-specific overrides."""
        perms = resolve_preset("trusted")
        delta = PermissionDelta(
            tool_overrides={
                "slow_tool": ToolPermission(timeout=5.0, requires_confirmation=True)
            }
        )
        new_perms = perms.apply_delta(delta)

        assert new_perms.tool_permissions["slow_tool"].timeout == 5.0
        assert new_perms.tool_permissions["slow_tool"].requires_confirmation is True

    def test_apply_delta_returns_new_instance(self):
        """apply_delta returns a new AgentPermissions instance."""
        perms = resolve_preset("trusted")
        delta = PermissionDelta(disable_tools=["sleep"])
        new_perms = perms.apply_delta(delta)

        assert new_perms is not perms

    def test_empty_delta_returns_equivalent_permissions(self):
        """Empty delta returns equivalent permissions."""
        perms = resolve_preset("trusted")
        delta = PermissionDelta()
        new_perms = perms.apply_delta(delta)

        assert new_perms.effective_policy.level == perms.effective_policy.level
        assert new_perms.base_preset == perms.base_preset
        # Should be equivalent (but new instance)
        assert new_perms is not perms

    def test_apply_delta_preserves_base_preset(self):
        """apply_delta preserves the base_preset name."""
        perms = resolve_preset("trusted")
        delta = PermissionDelta(disable_tools=["write_file"])
        new_perms = perms.apply_delta(delta)

        assert new_perms.base_preset == "trusted"

    def test_apply_delta_preserves_ceiling(self):
        """apply_delta preserves the ceiling reference."""
        ceiling = resolve_preset("yolo")
        policy = PermissionPolicy(level=PermissionLevel.TRUSTED)
        perms = AgentPermissions(
            base_preset="trusted",
            effective_policy=policy,
            ceiling=ceiling,
        )
        delta = PermissionDelta(disable_tools=["write_file"])
        new_perms = perms.apply_delta(delta)

        assert new_perms.ceiling is ceiling


class TestResolvePreset:
    """Tests for resolve_preset() function."""

    def test_resolve_yolo_preset(self):
        """Resolve 'yolo' returns YOLO level permissions."""
        perms = resolve_preset("yolo")
        assert perms.effective_policy.level == PermissionLevel.YOLO
        assert perms.effective_policy.allowed_paths is None  # Unrestricted
        assert perms.base_preset == "yolo"

    def test_resolve_trusted_preset(self):
        """Resolve 'trusted' returns TRUSTED level permissions."""
        perms = resolve_preset("trusted")
        assert perms.effective_policy.level == PermissionLevel.TRUSTED
        assert perms.effective_policy.allowed_paths is None  # Unrestricted by default
        assert perms.base_preset == "trusted"

    def test_resolve_sandboxed_preset(self):
        """Resolve 'sandboxed' returns SANDBOXED level permissions."""
        perms = resolve_preset("sandboxed")
        assert perms.effective_policy.level == PermissionLevel.SANDBOXED
        # Sandboxed has CWD restriction by default
        assert perms.effective_policy.allowed_paths is not None
        assert perms.base_preset == "sandboxed"

    def test_resolve_worker_preset_backwards_compat(self):
        """Resolve 'worker' maps to sandboxed for backwards compatibility."""
        perms = resolve_preset("worker")
        # Worker is mapped to sandboxed for backwards compatibility
        assert perms.effective_policy.level == PermissionLevel.SANDBOXED
        # base_preset is now "sandboxed" due to mapping
        assert perms.base_preset == "sandboxed"

    def test_unknown_preset_raises_valueerror(self):
        """Unknown preset name raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            resolve_preset("unknown_preset")
        assert "unknown_preset" in str(exc_info.value)

    def test_resolve_preset_with_custom_presets(self):
        """Custom presets can be resolved."""
        custom = PermissionPreset(
            name="custom",
            level=PermissionLevel.TRUSTED,
            description="Custom preset for testing",
        )
        perms = resolve_preset("custom", custom_presets={"custom": custom})
        assert perms.effective_policy.level == PermissionLevel.TRUSTED
        assert perms.base_preset == "custom"

    def test_custom_preset_overrides_builtin(self):
        """Custom preset with same name as builtin takes precedence."""
        # Create custom "trusted" that is actually sandboxed
        custom = PermissionPreset(
            name="trusted",
            level=PermissionLevel.SANDBOXED,
            description="Overridden trusted",
        )
        perms = resolve_preset("trusted", custom_presets={"trusted": custom})
        # Should use custom, not builtin
        assert perms.effective_policy.level == PermissionLevel.SANDBOXED

    def test_resolve_preset_copies_tool_permissions(self):
        """resolve_preset copies tool_permissions from preset."""
        perms = resolve_preset("sandboxed")
        # Sandboxed preset has some tools disabled
        assert "nexus_send" in perms.tool_permissions
        assert perms.tool_permissions["nexus_send"].enabled is False


class TestGetBuiltinPresets:
    """Tests for get_builtin_presets() function."""

    def test_returns_all_three_presets(self):
        """Returns all 3 built-in presets (worker was removed)."""
        presets = get_builtin_presets()
        assert len(presets) == 3
        assert set(presets.keys()) == {"yolo", "trusted", "sandboxed"}

    def test_yolo_preset_has_correct_level(self):
        """YOLO preset has YOLO level."""
        presets = get_builtin_presets()
        assert presets["yolo"].level == PermissionLevel.YOLO

    def test_trusted_preset_has_correct_level(self):
        """TRUSTED preset has TRUSTED level."""
        presets = get_builtin_presets()
        assert presets["trusted"].level == PermissionLevel.TRUSTED

    def test_sandboxed_preset_has_correct_level(self):
        """SANDBOXED preset has SANDBOXED level."""
        presets = get_builtin_presets()
        assert presets["sandboxed"].level == PermissionLevel.SANDBOXED

    def test_presets_have_descriptions(self):
        """All presets have non-empty descriptions."""
        presets = get_builtin_presets()
        for name, preset in presets.items():
            assert preset.description, f"Preset {name} has no description"

    def test_returns_new_dict_each_call(self):
        """get_builtin_presets returns a new dict each call (not mutable shared state)."""
        presets1 = get_builtin_presets()
        presets2 = get_builtin_presets()
        assert presets1 is not presets2

    def test_sandboxed_has_network_access_disabled(self):
        """Sandboxed preset has network_access disabled."""
        presets = get_builtin_presets()
        assert presets["sandboxed"].network_access is False

    def test_yolo_has_network_access_enabled(self):
        """YOLO preset has network_access enabled."""
        presets = get_builtin_presets()
        assert presets["yolo"].network_access is True

    def test_trusted_has_network_access_enabled(self):
        """Trusted preset has network_access enabled."""
        presets = get_builtin_presets()
        assert presets["trusted"].network_access is True


class TestAgentPermissionsConstruction:
    """Tests for AgentPermissions construction and attributes."""

    def test_create_with_base_preset_and_policy(self):
        """AgentPermissions requires base_preset and effective_policy."""
        policy = PermissionPolicy(level=PermissionLevel.TRUSTED)
        perms = AgentPermissions(
            base_preset="trusted",
            effective_policy=policy,
        )
        assert perms.base_preset == "trusted"
        assert perms.effective_policy.level == PermissionLevel.TRUSTED

    def test_defaults(self):
        """AgentPermissions has sensible defaults."""
        policy = PermissionPolicy(level=PermissionLevel.TRUSTED)
        perms = AgentPermissions(
            base_preset="trusted",
            effective_policy=policy,
        )
        assert perms.tool_permissions == {}
        assert perms.ceiling is None
        assert perms.parent_agent_id is None

    def test_create_with_all_options(self, tmp_path):
        """AgentPermissions can be created with all options."""
        policy = PermissionPolicy(
            level=PermissionLevel.SANDBOXED,
            allowed_paths=[tmp_path],
            blocked_paths=[tmp_path / ".secret"],
        )
        ceiling = resolve_preset("yolo")
        perms = AgentPermissions(
            base_preset="sandboxed",
            effective_policy=policy,
            tool_permissions={"write_file": ToolPermission(enabled=False)},
            ceiling=ceiling,
            parent_agent_id="main",
        )
        assert perms.effective_policy.level == PermissionLevel.SANDBOXED
        assert perms.tool_permissions["write_file"].enabled is False
        assert perms.effective_policy.allowed_paths == [tmp_path]
        assert tmp_path / ".secret" in perms.effective_policy.blocked_paths
        assert perms.ceiling is ceiling
        assert perms.parent_agent_id == "main"

    def test_tool_enabled_by_default(self):
        """Tools not in tool_permissions dict are enabled by default."""
        policy = PermissionPolicy(level=PermissionLevel.TRUSTED)
        perms = AgentPermissions(
            base_preset="trusted",
            effective_policy=policy,
            tool_permissions={},
        )
        # Tools not in the dict are considered enabled
        # (The dict only tracks explicit overrides)
        assert "read_file" not in perms.tool_permissions

    def test_tool_disabled_when_in_dict(self):
        """Tools in tool_permissions dict with enabled=False are disabled."""
        policy = PermissionPolicy(level=PermissionLevel.TRUSTED)
        perms = AgentPermissions(
            base_preset="trusted",
            effective_policy=policy,
            tool_permissions={"write_file": ToolPermission(enabled=False)},
        )
        assert perms.tool_permissions["write_file"].enabled is False


class TestPermissionLevelHierarchy:
    """Tests for permission level hierarchy comparison."""

    def test_yolo_is_highest(self):
        """YOLO is the highest permission level."""
        yolo = resolve_preset("yolo")
        trusted = resolve_preset("trusted")
        sandboxed = resolve_preset("sandboxed")

        assert yolo.can_grant(trusted) is True
        assert yolo.can_grant(sandboxed) is True

    def test_sandboxed_is_lowest(self):
        """SANDBOXED is the lowest permission level."""
        sandboxed = resolve_preset("sandboxed")
        trusted = resolve_preset("trusted")
        yolo = resolve_preset("yolo")

        assert sandboxed.can_grant(trusted) is False
        assert sandboxed.can_grant(yolo) is False

    def test_trusted_is_middle(self):
        """TRUSTED is between YOLO and SANDBOXED."""
        trusted = resolve_preset("trusted")
        yolo = resolve_preset("yolo")
        sandboxed = resolve_preset("sandboxed")

        assert trusted.can_grant(yolo) is False
        assert trusted.can_grant(sandboxed) is True

    def test_yolo_cannot_grant_yolo(self):
        """YOLO cannot grant YOLO (same level - lower only policy)."""
        yolo1 = resolve_preset("yolo")
        yolo2 = resolve_preset("yolo")
        assert yolo1.can_grant(yolo2) is False

    def test_sandboxed_cannot_grant_sandboxed(self):
        """SANDBOXED cannot grant SANDBOXED (same level - lower only policy)."""
        sandboxed1 = resolve_preset("sandboxed")
        sandboxed2 = resolve_preset("sandboxed")
        assert sandboxed1.can_grant(sandboxed2) is False
