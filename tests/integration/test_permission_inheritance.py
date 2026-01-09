"""Integration tests for permission inheritance between parent and child agents.

Tests that permissions correctly cascade from parent to child agents:
1. Parent can create child with same or more restrictive preset
2. Parent cannot create child with less restrictive preset
3. YOLO parent can create any preset
4. Child inherits ceiling from parent
5. Disabled tools propagate to child
6. Child cannot enable tools parent disabled
7. Ceiling cascades through generations

These tests verify the integration between:
- AgentPool.create() with parent_permissions
- AgentPermissions.can_grant()
- PermissionDelta for tool disabling
- resolve_preset() for preset resolution
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nexus3.core.permissions import (
    AgentPermissions,
    PermissionDelta,
    PermissionLevel,
    PermissionPolicy,
    ToolPermission,
    resolve_preset,
)
from nexus3.rpc.pool import AgentConfig, AgentPool, SharedComponents


def create_mock_shared_components(tmp_path: Path) -> SharedComponents:
    """Create SharedComponents with mocks for testing."""
    mock_config = MagicMock()
    mock_config.skill_timeout = 30.0
    mock_config.max_concurrent_tools = 10
    mock_config.permissions = MagicMock()
    mock_config.permissions.default_preset = "trusted"
    mock_provider = MagicMock()

    mock_prompt_loader = MagicMock()
    mock_loaded_prompt = MagicMock()
    mock_loaded_prompt.content = "You are a test assistant."
    mock_prompt_loader.load.return_value = mock_loaded_prompt

    return SharedComponents(
        config=mock_config,
        provider=mock_provider,
        prompt_loader=mock_prompt_loader,
        base_log_dir=tmp_path / "logs",
    )


class TestParentCanCreateChildWithSamePreset:
    """Parent can create child with same permission preset."""

    @pytest.mark.asyncio
    async def test_trusted_parent_creates_trusted_child(self, tmp_path: Path) -> None:
        """Parent with 'trusted' preset can create child with 'trusted' preset."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)

            # Create parent with trusted preset
            parent = await pool.create(
                config=AgentConfig(agent_id="parent", preset="trusted")
            )
            parent_permissions = parent.services.get("permissions")

            # Create child with trusted preset using parent's permissions as ceiling
            child = await pool.create(
                config=AgentConfig(
                    agent_id="child",
                    preset="trusted",
                    parent_permissions=parent_permissions,
                )
            )

            # Child should be created successfully
            assert child.agent_id == "child"
            assert "child" in pool

            # Verify child has trusted permissions
            child_permissions = child.services.get("permissions")
            assert child_permissions.base_preset == "trusted"
            assert child_permissions.effective_policy.level == PermissionLevel.TRUSTED

    @pytest.mark.asyncio
    async def test_sandboxed_parent_creates_sandboxed_child(self, tmp_path: Path) -> None:
        """Parent with 'sandboxed' preset can create child with 'sandboxed' preset."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)

            # Create parent with sandboxed preset
            parent = await pool.create(
                config=AgentConfig(agent_id="parent", preset="sandboxed")
            )
            parent_permissions = parent.services.get("permissions")

            # Create child with sandboxed preset
            child = await pool.create(
                config=AgentConfig(
                    agent_id="child",
                    preset="sandboxed",
                    parent_permissions=parent_permissions,
                )
            )

            # Child should be created successfully
            assert child.agent_id == "child"
            child_permissions = child.services.get("permissions")
            assert child_permissions.base_preset == "sandboxed"


class TestParentCanCreateChildWithMoreRestrictivePreset:
    """Parent can create child with more restrictive preset."""

    @pytest.mark.asyncio
    async def test_trusted_parent_creates_sandboxed_child(self, tmp_path: Path) -> None:
        """Parent with 'trusted' can create child with 'sandboxed'."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)

            # Create parent with trusted preset
            parent = await pool.create(
                config=AgentConfig(agent_id="parent", preset="trusted")
            )
            parent_permissions = parent.services.get("permissions")

            # Create child with sandboxed preset (more restrictive)
            child = await pool.create(
                config=AgentConfig(
                    agent_id="child",
                    preset="sandboxed",
                    parent_permissions=parent_permissions,
                )
            )

            # Child should be created successfully with sandboxed
            assert child.agent_id == "child"
            child_permissions = child.services.get("permissions")
            assert child_permissions.base_preset == "sandboxed"
            assert child_permissions.effective_policy.level == PermissionLevel.SANDBOXED

    @pytest.mark.asyncio
    async def test_yolo_parent_creates_trusted_child(self, tmp_path: Path) -> None:
        """Parent with 'yolo' can create child with 'trusted'."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)

            # Create parent with yolo preset
            parent = await pool.create(
                config=AgentConfig(agent_id="parent", preset="yolo")
            )
            parent_permissions = parent.services.get("permissions")

            # Create child with trusted preset (more restrictive)
            child = await pool.create(
                config=AgentConfig(
                    agent_id="child",
                    preset="trusted",
                    parent_permissions=parent_permissions,
                )
            )

            # Child should be created successfully
            assert child.agent_id == "child"
            child_permissions = child.services.get("permissions")
            assert child_permissions.base_preset == "trusted"

    @pytest.mark.asyncio
    async def test_trusted_parent_creates_worker_child(self, tmp_path: Path) -> None:
        """Parent with 'trusted' can create child with 'worker' (sandboxed level)."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)

            # Create parent with trusted preset
            parent = await pool.create(
                config=AgentConfig(agent_id="parent", preset="trusted")
            )
            parent_permissions = parent.services.get("permissions")

            # Create child with worker preset (sandboxed level, more restrictive)
            child = await pool.create(
                config=AgentConfig(
                    agent_id="child",
                    preset="worker",
                    parent_permissions=parent_permissions,
                )
            )

            # Child should be created successfully with worker preset
            assert child.agent_id == "child"
            child_permissions = child.services.get("permissions")
            assert child_permissions.base_preset == "worker"
            # Worker is sandboxed level
            assert child_permissions.effective_policy.level == PermissionLevel.SANDBOXED


class TestParentCannotCreateChildWithLessRestrictivePreset:
    """Parent cannot create child with less restrictive preset."""

    @pytest.mark.asyncio
    async def test_sandboxed_parent_cannot_create_trusted_child(self, tmp_path: Path) -> None:
        """Parent with 'sandboxed' cannot create child with 'trusted'."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)

            # Create parent with sandboxed preset
            parent = await pool.create(
                config=AgentConfig(agent_id="parent", preset="sandboxed")
            )
            parent_permissions = parent.services.get("permissions")

            # Attempt to create child with trusted preset (less restrictive)
            with pytest.raises(PermissionError) as exc_info:
                await pool.create(
                    config=AgentConfig(
                        agent_id="child",
                        preset="trusted",
                        parent_permissions=parent_permissions,
                    )
                )

            assert "exceed" in str(exc_info.value).lower()
            assert "ceiling" in str(exc_info.value).lower()

            # Child should not exist in pool
            assert "child" not in pool

    @pytest.mark.asyncio
    async def test_sandboxed_parent_cannot_create_yolo_child(self, tmp_path: Path) -> None:
        """Parent with 'sandboxed' cannot create child with 'yolo'."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)

            # Create parent with sandboxed preset
            parent = await pool.create(
                config=AgentConfig(agent_id="parent", preset="sandboxed")
            )
            parent_permissions = parent.services.get("permissions")

            # Attempt to create child with yolo preset (much less restrictive)
            with pytest.raises(PermissionError):
                await pool.create(
                    config=AgentConfig(
                        agent_id="child",
                        preset="yolo",
                        parent_permissions=parent_permissions,
                    )
                )

            assert "child" not in pool

    @pytest.mark.asyncio
    async def test_trusted_parent_cannot_create_yolo_child(self, tmp_path: Path) -> None:
        """Parent with 'trusted' cannot create child with 'yolo'."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)

            # Create parent with trusted preset
            parent = await pool.create(
                config=AgentConfig(agent_id="parent", preset="trusted")
            )
            parent_permissions = parent.services.get("permissions")

            # Attempt to create child with yolo preset (less restrictive)
            with pytest.raises(PermissionError):
                await pool.create(
                    config=AgentConfig(
                        agent_id="child",
                        preset="yolo",
                        parent_permissions=parent_permissions,
                    )
                )

            assert "child" not in pool

    @pytest.mark.asyncio
    async def test_worker_parent_cannot_create_sandboxed_child(self, tmp_path: Path) -> None:
        """Worker parent cannot create sandboxed child if sandboxed has more tools enabled."""
        # Note: Worker and sandboxed are both SANDBOXED level, but have different tool permissions
        # Worker has write_file disabled, sandboxed doesn't
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)

            # Create parent with worker preset (has write_file disabled)
            parent = await pool.create(
                config=AgentConfig(agent_id="parent", preset="worker")
            )
            parent_permissions = parent.services.get("permissions")

            # Attempting to create sandboxed child should fail because
            # sandboxed has write_file enabled but worker parent has it disabled
            with pytest.raises(PermissionError):
                await pool.create(
                    config=AgentConfig(
                        agent_id="child",
                        preset="sandboxed",
                        parent_permissions=parent_permissions,
                    )
                )


class TestYoloParentCanCreateAnyPreset:
    """YOLO parent can create children with any preset."""

    @pytest.mark.asyncio
    async def test_yolo_parent_creates_yolo_child(self, tmp_path: Path) -> None:
        """YOLO parent can create child with YOLO preset."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)

            # Create parent with yolo preset
            parent = await pool.create(
                config=AgentConfig(agent_id="parent", preset="yolo")
            )
            parent_permissions = parent.services.get("permissions")

            # Create child with yolo preset
            child = await pool.create(
                config=AgentConfig(
                    agent_id="child",
                    preset="yolo",
                    parent_permissions=parent_permissions,
                )
            )

            assert child.agent_id == "child"
            child_permissions = child.services.get("permissions")
            assert child_permissions.base_preset == "yolo"

    @pytest.mark.asyncio
    async def test_yolo_parent_creates_sandboxed_child(self, tmp_path: Path) -> None:
        """YOLO parent can create child with sandboxed preset."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)

            # Create parent with yolo preset
            parent = await pool.create(
                config=AgentConfig(agent_id="parent", preset="yolo")
            )
            parent_permissions = parent.services.get("permissions")

            # Create child with sandboxed preset
            child = await pool.create(
                config=AgentConfig(
                    agent_id="child",
                    preset="sandboxed",
                    parent_permissions=parent_permissions,
                )
            )

            assert child.agent_id == "child"
            child_permissions = child.services.get("permissions")
            assert child_permissions.base_preset == "sandboxed"

    @pytest.mark.asyncio
    async def test_yolo_parent_creates_worker_child(self, tmp_path: Path) -> None:
        """YOLO parent can create child with worker preset."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)

            parent = await pool.create(
                config=AgentConfig(agent_id="parent", preset="yolo")
            )
            parent_permissions = parent.services.get("permissions")

            child = await pool.create(
                config=AgentConfig(
                    agent_id="child",
                    preset="worker",
                    parent_permissions=parent_permissions,
                )
            )

            assert child.agent_id == "child"
            child_permissions = child.services.get("permissions")
            assert child_permissions.base_preset == "worker"


class TestChildInheritsCeilingFromParent:
    """Child's ceiling should be set to parent's permissions."""

    @pytest.mark.asyncio
    async def test_child_ceiling_is_parent_permissions(self, tmp_path: Path) -> None:
        """Child's ceiling should be set to parent's permissions."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)

            # Create parent with trusted preset
            parent = await pool.create(
                config=AgentConfig(agent_id="parent", preset="trusted")
            )
            parent_permissions = parent.services.get("permissions")

            # Create child with sandboxed preset
            child = await pool.create(
                config=AgentConfig(
                    agent_id="child",
                    preset="sandboxed",
                    parent_permissions=parent_permissions,
                )
            )

            child_permissions = child.services.get("permissions")

            # Child's ceiling should be the parent's permissions
            assert child_permissions.ceiling is parent_permissions

    @pytest.mark.asyncio
    async def test_child_parent_agent_id_is_set(self, tmp_path: Path) -> None:
        """Child should have parent_agent_id set."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)

            parent = await pool.create(
                config=AgentConfig(agent_id="parent", preset="trusted")
            )
            parent_permissions = parent.services.get("permissions")

            child = await pool.create(
                config=AgentConfig(
                    agent_id="child",
                    preset="sandboxed",
                    parent_permissions=parent_permissions,
                )
            )

            child_permissions = child.services.get("permissions")

            # Child's parent_agent_id should be set based on parent's base_preset
            # (as per pool.py implementation)
            assert child_permissions.parent_agent_id == parent_permissions.base_preset


class TestDisabledToolsPropagate:
    """Parent can disable additional tools when creating child."""

    @pytest.mark.asyncio
    async def test_parent_disables_tool_via_delta(self, tmp_path: Path) -> None:
        """Parent can disable additional tools when creating child via delta."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)

            # Create parent with trusted preset
            parent = await pool.create(
                config=AgentConfig(agent_id="parent", preset="trusted")
            )
            parent_permissions = parent.services.get("permissions")

            # Create child with delta that disables read_file
            delta = PermissionDelta(disable_tools=["read_file"])
            child = await pool.create(
                config=AgentConfig(
                    agent_id="child",
                    preset="trusted",
                    parent_permissions=parent_permissions,
                    delta=delta,
                )
            )

            child_permissions = child.services.get("permissions")

            # Child should have read_file disabled
            assert "read_file" in child_permissions.tool_permissions
            assert child_permissions.tool_permissions["read_file"].enabled is False

    @pytest.mark.asyncio
    async def test_multiple_tools_disabled_via_delta(self, tmp_path: Path) -> None:
        """Parent can disable multiple tools when creating child."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)

            parent = await pool.create(
                config=AgentConfig(agent_id="parent", preset="trusted")
            )
            parent_permissions = parent.services.get("permissions")

            # Disable multiple tools
            delta = PermissionDelta(disable_tools=["read_file", "write_file", "sleep"])
            child = await pool.create(
                config=AgentConfig(
                    agent_id="child",
                    preset="trusted",
                    parent_permissions=parent_permissions,
                    delta=delta,
                )
            )

            child_permissions = child.services.get("permissions")

            # All three tools should be disabled
            assert child_permissions.tool_permissions["read_file"].enabled is False
            assert child_permissions.tool_permissions["write_file"].enabled is False
            assert child_permissions.tool_permissions["sleep"].enabled is False


class TestChildCannotEnableToolsParentDisabled:
    """Child cannot re-enable tools that were disabled by parent."""

    @pytest.mark.asyncio
    async def test_child_cannot_enable_parent_disabled_tool(self, tmp_path: Path) -> None:
        """Child cannot re-enable tools that were disabled by parent."""
        # Use the can_grant logic directly since the pool.create enforcement
        # happens at creation time

        # Parent permissions with write_file disabled
        parent_permissions = resolve_preset("trusted")
        parent_permissions.tool_permissions["write_file"] = ToolPermission(enabled=False)

        # Child permissions attempting to have write_file enabled
        child_permissions = resolve_preset("trusted")
        # write_file is not in tool_permissions by default (meaning enabled)

        # Parent should NOT be able to grant these permissions to child
        assert parent_permissions.can_grant(child_permissions) is False

    @pytest.mark.asyncio
    async def test_worker_preset_tools_cannot_be_enabled_by_child(self, tmp_path: Path) -> None:
        """Worker preset has write_file disabled, child cannot enable it."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)

            # Create parent with worker preset (has write_file disabled)
            parent = await pool.create(
                config=AgentConfig(agent_id="parent", preset="worker")
            )
            parent_permissions = parent.services.get("permissions")

            # Try to create child with delta that enables write_file
            delta = PermissionDelta(enable_tools=["write_file"])

            # This should fail because worker has write_file disabled
            with pytest.raises(PermissionError):
                await pool.create(
                    config=AgentConfig(
                        agent_id="child",
                        preset="worker",
                        parent_permissions=parent_permissions,
                        delta=delta,
                    )
                )

    @pytest.mark.asyncio
    async def test_can_grant_checks_tool_permissions(self) -> None:
        """can_grant should return False when child tries to enable parent-disabled tool."""
        parent = resolve_preset("trusted")
        parent.tool_permissions["nexus_create"] = ToolPermission(enabled=False)

        # Child with nexus_create enabled (not in tool_permissions = enabled by default)
        child = resolve_preset("trusted")

        # can_grant should return False
        assert parent.can_grant(child) is False

        # Now disable nexus_create in child too
        child.tool_permissions["nexus_create"] = ToolPermission(enabled=False)

        # Now can_grant should return True
        assert parent.can_grant(child) is True


class TestCeilingCascadesThroughGenerations:
    """Grandchild cannot exceed grandparent's ceiling."""

    @pytest.mark.asyncio
    async def test_grandchild_cannot_exceed_grandparent_ceiling(self, tmp_path: Path) -> None:
        """Grandchild cannot exceed grandparent's ceiling."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)

            # Create grandparent with trusted preset
            grandparent = await pool.create(
                config=AgentConfig(agent_id="grandparent", preset="trusted")
            )
            grandparent_permissions = grandparent.services.get("permissions")

            # Create parent with sandboxed preset (more restrictive)
            parent = await pool.create(
                config=AgentConfig(
                    agent_id="parent",
                    preset="sandboxed",
                    parent_permissions=grandparent_permissions,
                )
            )
            parent_permissions = parent.services.get("permissions")

            # Parent (sandboxed) tries to create yolo grandchild - should fail
            with pytest.raises(PermissionError):
                await pool.create(
                    config=AgentConfig(
                        agent_id="grandchild",
                        preset="yolo",
                        parent_permissions=parent_permissions,
                    )
                )

            assert "grandchild" not in pool

    @pytest.mark.asyncio
    async def test_grandchild_cannot_exceed_parent_ceiling(self, tmp_path: Path) -> None:
        """Even if grandparent was yolo, parent's ceiling restricts grandchild."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)

            # Create grandparent with yolo preset
            grandparent = await pool.create(
                config=AgentConfig(agent_id="grandparent", preset="yolo")
            )
            grandparent_permissions = grandparent.services.get("permissions")

            # Create parent with sandboxed preset
            parent = await pool.create(
                config=AgentConfig(
                    agent_id="parent",
                    preset="sandboxed",
                    parent_permissions=grandparent_permissions,
                )
            )
            parent_permissions = parent.services.get("permissions")

            # Parent (sandboxed) tries to create trusted grandchild
            # This should fail because parent's own level is sandboxed
            with pytest.raises(PermissionError):
                await pool.create(
                    config=AgentConfig(
                        agent_id="grandchild",
                        preset="trusted",
                        parent_permissions=parent_permissions,
                    )
                )

            assert "grandchild" not in pool

    @pytest.mark.asyncio
    async def test_grandchild_can_be_same_or_more_restrictive(self, tmp_path: Path) -> None:
        """Grandchild can be sandboxed if parent is sandboxed."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)

            # Grandparent: trusted
            grandparent = await pool.create(
                config=AgentConfig(agent_id="grandparent", preset="trusted")
            )
            grandparent_permissions = grandparent.services.get("permissions")

            # Parent: sandboxed
            parent = await pool.create(
                config=AgentConfig(
                    agent_id="parent",
                    preset="sandboxed",
                    parent_permissions=grandparent_permissions,
                )
            )
            parent_permissions = parent.services.get("permissions")

            # Grandchild: sandboxed (same as parent) - should succeed
            grandchild = await pool.create(
                config=AgentConfig(
                    agent_id="grandchild",
                    preset="sandboxed",
                    parent_permissions=parent_permissions,
                )
            )

            assert grandchild.agent_id == "grandchild"
            grandchild_permissions = grandchild.services.get("permissions")
            assert grandchild_permissions.base_preset == "sandboxed"


class TestCanGrantLogic:
    """Direct tests for AgentPermissions.can_grant() logic."""

    def test_yolo_can_grant_any_level(self) -> None:
        """YOLO can grant any permission level."""
        yolo = resolve_preset("yolo")
        trusted = resolve_preset("trusted")
        sandboxed = resolve_preset("sandboxed")

        assert yolo.can_grant(yolo) is True
        assert yolo.can_grant(trusted) is True
        assert yolo.can_grant(sandboxed) is True

    def test_trusted_can_grant_trusted_or_sandboxed(self) -> None:
        """Trusted can grant trusted or sandboxed."""
        trusted = resolve_preset("trusted")
        sandboxed = resolve_preset("sandboxed")
        yolo = resolve_preset("yolo")

        assert trusted.can_grant(trusted) is True
        assert trusted.can_grant(sandboxed) is True
        assert trusted.can_grant(yolo) is False

    def test_sandboxed_can_only_grant_sandboxed(self) -> None:
        """Sandboxed can only grant sandboxed level."""
        sandboxed = resolve_preset("sandboxed")
        trusted = resolve_preset("trusted")
        yolo = resolve_preset("yolo")
        worker = resolve_preset("worker")

        assert sandboxed.can_grant(sandboxed) is True
        # Worker is also sandboxed level, but has different tool permissions
        # sandboxed has nexus_send disabled, worker doesn't
        # Actually worker has MORE disabled (including write_file, nexus_destroy)
        # So sandboxed should be able to grant worker if worker has more restrictions
        # Let's check the actual presets
        assert sandboxed.can_grant(trusted) is False
        assert sandboxed.can_grant(yolo) is False

    def test_can_grant_checks_path_restrictions(self) -> None:
        """can_grant should check path restrictions."""
        # Parent with restricted paths
        parent = AgentPermissions(
            base_preset="custom",
            effective_policy=PermissionPolicy(
                level=PermissionLevel.TRUSTED,
                allowed_paths=[Path("/home/user/project")],
            ),
        )

        # Child requesting unrestricted paths
        child_unrestricted = AgentPermissions(
            base_preset="custom",
            effective_policy=PermissionPolicy(
                level=PermissionLevel.TRUSTED,
                allowed_paths=None,  # Unrestricted
            ),
        )

        # Parent cannot grant unrestricted paths
        assert parent.can_grant(child_unrestricted) is False

        # Child requesting subset of parent's paths
        child_subset = AgentPermissions(
            base_preset="custom",
            effective_policy=PermissionPolicy(
                level=PermissionLevel.TRUSTED,
                allowed_paths=[Path("/home/user/project/subdir")],
            ),
        )

        # Parent can grant subset paths
        assert parent.can_grant(child_subset) is True

        # Child requesting paths outside parent's scope
        child_outside = AgentPermissions(
            base_preset="custom",
            effective_policy=PermissionPolicy(
                level=PermissionLevel.TRUSTED,
                allowed_paths=[Path("/home/other")],
            ),
        )

        # Parent cannot grant paths outside its scope
        assert parent.can_grant(child_outside) is False


class TestPermissionDeltaApplication:
    """Tests for PermissionDelta application to permissions."""

    def test_apply_delta_disables_tools(self) -> None:
        """apply_delta should disable specified tools."""
        permissions = resolve_preset("trusted")
        delta = PermissionDelta(disable_tools=["read_file", "write_file"])

        new_permissions = permissions.apply_delta(delta)

        assert new_permissions.tool_permissions["read_file"].enabled is False
        assert new_permissions.tool_permissions["write_file"].enabled is False

    def test_apply_delta_enables_tools(self) -> None:
        """apply_delta should enable specified tools."""
        permissions = resolve_preset("worker")
        # Worker has write_file disabled by default

        delta = PermissionDelta(enable_tools=["write_file"])
        new_permissions = permissions.apply_delta(delta)

        assert new_permissions.tool_permissions["write_file"].enabled is True

    def test_apply_delta_adds_blocked_paths(self) -> None:
        """apply_delta should add blocked paths."""
        permissions = resolve_preset("trusted")
        delta = PermissionDelta(add_blocked_paths=[Path("/secret")])

        new_permissions = permissions.apply_delta(delta)

        assert Path("/secret") in new_permissions.effective_policy.blocked_paths

    def test_apply_delta_replaces_allowed_paths(self) -> None:
        """apply_delta with allowed_paths replaces base paths."""
        permissions = resolve_preset("sandboxed")
        # Sandboxed defaults to CWD

        delta = PermissionDelta(allowed_paths=[Path("/home/user/specific")])
        new_permissions = permissions.apply_delta(delta)

        assert new_permissions.effective_policy.allowed_paths == [Path("/home/user/specific")]


class TestNoParentPermissionsIsUnrestricted:
    """Agent created without parent_permissions has no ceiling."""

    @pytest.mark.asyncio
    async def test_no_parent_permissions_no_ceiling(self, tmp_path: Path) -> None:
        """Agent without parent_permissions should have no ceiling."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)

            # Create agent without parent_permissions
            agent = await pool.create(
                config=AgentConfig(agent_id="standalone", preset="trusted")
            )

            permissions = agent.services.get("permissions")

            # No ceiling should be set
            assert permissions.ceiling is None
            assert permissions.parent_agent_id is None

    @pytest.mark.asyncio
    async def test_yolo_without_parent_has_full_access(self, tmp_path: Path) -> None:
        """YOLO agent without parent has full access."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)

            agent = await pool.create(
                config=AgentConfig(agent_id="yolo-agent", preset="yolo")
            )

            permissions = agent.services.get("permissions")

            assert permissions.base_preset == "yolo"
            assert permissions.effective_policy.level == PermissionLevel.YOLO
            assert permissions.ceiling is None
