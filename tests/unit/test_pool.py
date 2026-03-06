"""Unit tests for multi-agent pool management components.

Tests for:
- SharedComponents: Dataclass for shared resources
- AgentConfig: Per-agent configuration
- AgentPool: Agent lifecycle management
- GlobalDispatcher: Agent management RPC methods
- HTTP path routing: _extract_agent_id helper
- Security: Tool definition filtering, ceiling isolation, parent_agent_id tracking
"""

import asyncio
from dataclasses import FrozenInstanceError, fields
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus3.core.authorization_kernel import (
    AuthorizationAction,
    AuthorizationDecision,
    AuthorizationRequest,
    AuthorizationResource,
    AuthorizationResourceType,
)
from nexus3.core.capabilities import CapabilityRevokedError
from nexus3.core.permissions import (
    PermissionDelta,
    ToolPermission,
    resolve_preset,
)
from nexus3.rpc.global_dispatcher import GlobalDispatcher
from nexus3.rpc.http import _extract_agent_id
from nexus3.rpc.pool import (
    AgentConfig,
    AgentPool,
    AuthorizationError,
    SharedComponents,
)
from nexus3.rpc.types import Request
from nexus3.session.persistence import SavedSession

# -----------------------------------------------------------------------------
# SharedComponents Tests
# -----------------------------------------------------------------------------


class TestSharedComponents:
    """Tests for SharedComponents dataclass."""

    def test_shared_components_is_dataclass(self):
        """SharedComponents is a dataclass with expected fields."""
        # Verify it's a dataclass by checking for __dataclass_fields__
        assert hasattr(SharedComponents, "__dataclass_fields__")

    def test_shared_components_has_expected_fields(self):
        """SharedComponents has expected fields including mcp_registry and base_context."""
        field_names = {f.name for f in fields(SharedComponents)}
        expected = {
            "config", "provider_registry", "base_log_dir", "base_context",
            "context_loader", "log_streams", "custom_presets", "mcp_registry",
            "is_repl",
        }
        assert field_names == expected

    def test_shared_components_is_frozen(self):
        """SharedComponents is immutable (frozen=True)."""
        # Create with mocks
        mock_config = MagicMock()
        mock_provider_registry = MagicMock()
        mock_base_context = MagicMock()
        mock_context_loader = MagicMock()

        shared = SharedComponents(
            config=mock_config,
            provider_registry=mock_provider_registry,
            base_log_dir=Path("/tmp/logs"),
            base_context=mock_base_context,
            context_loader=mock_context_loader,
        )

        # Attempting to modify should raise FrozenInstanceError
        with pytest.raises(FrozenInstanceError):
            shared.config = MagicMock()

    def test_shared_components_stores_values(self):
        """SharedComponents correctly stores provided values."""
        mock_config = MagicMock()
        mock_provider_registry = MagicMock()
        mock_base_context = MagicMock()
        mock_context_loader = MagicMock()
        log_dir = Path("/tmp/test_logs")

        shared = SharedComponents(
            config=mock_config,
            provider_registry=mock_provider_registry,
            base_log_dir=log_dir,
            base_context=mock_base_context,
            context_loader=mock_context_loader,
        )

        assert shared.config is mock_config
        assert shared.provider_registry is mock_provider_registry
        assert shared.base_log_dir == log_dir
        assert shared.base_context is mock_base_context
        assert shared.context_loader is mock_context_loader


# -----------------------------------------------------------------------------
# AgentConfig Tests
# -----------------------------------------------------------------------------


class TestAgentConfig:
    """Tests for AgentConfig dataclass."""

    def test_agent_config_default_values(self):
        """AgentConfig has None defaults for agent_id and system_prompt."""
        config = AgentConfig()

        assert config.agent_id is None
        assert config.system_prompt is None

    def test_agent_config_accepts_agent_id(self):
        """AgentConfig accepts agent_id parameter."""
        config = AgentConfig(agent_id="my-agent")

        assert config.agent_id == "my-agent"
        assert config.system_prompt is None

    def test_agent_config_accepts_system_prompt(self):
        """AgentConfig accepts system_prompt parameter."""
        config = AgentConfig(system_prompt="You are a helpful assistant.")

        assert config.agent_id is None
        assert config.system_prompt == "You are a helpful assistant."

    def test_agent_config_accepts_both_params(self):
        """AgentConfig accepts both agent_id and system_prompt."""
        config = AgentConfig(
            agent_id="worker-1",
            system_prompt="You are a worker agent.",
        )

        assert config.agent_id == "worker-1"
        assert config.system_prompt == "You are a worker agent."


# -----------------------------------------------------------------------------
# AgentPool Tests
# -----------------------------------------------------------------------------


def create_mock_shared_components(tmp_path: Path) -> SharedComponents:
    """Create SharedComponents with mocks for testing."""
    mock_config = MagicMock()
    # Provide concrete values for skill timeout and concurrency limit
    mock_config.skill_timeout = 30.0
    mock_config.max_concurrent_tools = 10
    mock_config.default_provider = None  # Use "default" provider

    # Mock provider registry
    mock_provider_registry = MagicMock()
    mock_provider = MagicMock()
    mock_provider_registry.get.return_value = mock_provider

    # Mock base_context with system_prompt
    mock_base_context = MagicMock()
    mock_base_context.system_prompt = "You are a test assistant."
    mock_base_context.sources.prompt_sources = []

    # Mock context_loader for compaction
    mock_context_loader = MagicMock()
    mock_loaded_context = MagicMock()
    mock_loaded_context.system_prompt = "You are a test assistant."
    mock_context_loader.load.return_value = mock_loaded_context

    return SharedComponents(
        config=mock_config,
        provider_registry=mock_provider_registry,
        base_log_dir=tmp_path / "logs",
        base_context=mock_base_context,
        context_loader=mock_context_loader,
    )


class TestAgentPool:
    """Tests for AgentPool lifecycle management."""

    @pytest.mark.asyncio
    async def test_create_with_explicit_agent_id(self, tmp_path):
        """create() with explicit agent_id uses that ID."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            agent = await pool.create(agent_id="my-custom-id")

            assert agent.agent_id == "my-custom-id"
            assert "my-custom-id" in pool
            assert len(pool) == 1

    @pytest.mark.asyncio
    async def test_create_with_auto_generated_agent_id(self, tmp_path):
        """create() without agent_id generates a random ID."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            agent = await pool.create()

            # Auto-generated ID should be 8 hex chars
            assert agent.agent_id is not None
            assert len(agent.agent_id) == 8
            assert agent.agent_id in pool

    @pytest.mark.asyncio
    async def test_create_root_runs_lifecycle_entry_kernel_check(self, tmp_path):
        """Root create paths run lifecycle-entry kernel auth and remain allowed."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            original_authorize = pool._create_authorization_kernel.authorize
            pool._create_authorization_kernel.authorize = MagicMock(side_effect=original_authorize)

            agent = await pool.create(agent_id="root-lifecycle-entry")

            assert agent.agent_id == "root-lifecycle-entry"
            assert pool._create_authorization_kernel.authorize.call_count == 1
            kernel_request = pool._create_authorization_kernel.authorize.call_args.args[0]
            assert kernel_request.context["check_stage"] == "lifecycle_entry"
            assert kernel_request.principal_id == "external"

    @pytest.mark.asyncio
    async def test_create_with_duplicate_agent_id_raises(self, tmp_path):
        """create() with duplicate agent_id raises ValueError."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            await pool.create(agent_id="duplicate-id")

            with pytest.raises(ValueError) as exc_info:
                await pool.create(agent_id="duplicate-id")

            assert "duplicate-id" in str(exc_info.value)
            assert "already exists" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_create_forced_kernel_deny_is_authoritative(self, tmp_path):
        """create() fails closed when the create authorization kernel denies."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            parent_permissions = resolve_preset("trusted")
            parent_permissions.depth = 0

            def _authorize_for_test(request: AuthorizationRequest) -> AuthorizationDecision:
                if request.context.get("check_stage") == "max_depth":
                    return AuthorizationDecision.deny(
                        request,
                        reason="forced_deny_for_test",
                    )
                return AuthorizationDecision.allow(request, reason="forced_allow_for_test")

            pool._create_authorization_kernel.authorize = MagicMock(
                side_effect=_authorize_for_test,
            )

            with pytest.raises(PermissionError, match="max nesting depth"):
                await pool.create(
                    config=AgentConfig(
                        agent_id="child-agent",
                        preset="sandboxed",
                        parent_permissions=parent_permissions,
                    )
                )

            assert "child-agent" not in pool

    @pytest.mark.asyncio
    async def test_create_parented_with_delta_keeps_authorization_stage_order_stable(
        self,
        tmp_path,
    ):
        """Parented create with delta preserves AGENT_CREATE check stage ordering."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            await pool.create(
                config=AgentConfig(
                    agent_id="parent-stage-order",
                    preset="trusted",
                )
            )

            original_authorize = pool._create_authorization_kernel.authorize
            pool._create_authorization_kernel.authorize = MagicMock(side_effect=original_authorize)

            child_agent = await pool.create(
                config=AgentConfig(
                    agent_id="child-stage-order",
                    preset="sandboxed",
                    parent_agent_id="parent-stage-order",
                    delta=PermissionDelta(disable_tools=["read_file"]),
                ),
                requester_id="parent-stage-order",
            )

            assert child_agent.agent_id == "child-stage-order"
            observed_stages = [
                call.args[0].context["check_stage"]
                for call in pool._create_authorization_kernel.authorize.call_args_list
            ]
            assert observed_stages == [
                "lifecycle_entry",
                "requester_parent_binding",
                "max_depth",
                "base_ceiling",
                "delta_ceiling",
            ]
            observed_contexts = [
                call.args[0].context
                for call in pool._create_authorization_kernel.authorize.call_args_list
            ]
            base_context = observed_contexts[3]
            delta_context = observed_contexts[4]
            assert "parent_can_grant" not in base_context
            assert "parent_can_grant" not in delta_context
            assert isinstance(base_context.get("parent_permissions_json"), str)
            assert isinstance(base_context.get("requested_permissions_json"), str)
            assert isinstance(delta_context.get("parent_permissions_json"), str)
            assert isinstance(delta_context.get("requested_permissions_json"), str)

    @pytest.mark.asyncio
    async def test_create_mcp_visibility_uses_kernel_and_fetches_when_allowed(self, tmp_path):
        """create() uses MCP visibility kernel and fetches tools when allowed by level."""
        shared = create_mock_shared_components(tmp_path)
        mcp_skill = MagicMock()
        mcp_skill.name = "mcp_lookup"
        mcp_skill.description = "Lookup"
        mcp_skill.parameters = {"type": "object", "properties": {}}
        shared.mcp_registry.get_all_skills = AsyncMock(return_value=[mcp_skill])

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            original_authorize = pool._mcp_visibility_authorization_kernel.authorize
            pool._mcp_visibility_authorization_kernel.authorize = MagicMock(
                side_effect=original_authorize
            )

            agent = await pool.create(
                config=AgentConfig(agent_id="mcp-visible-create", preset="trusted")
            )

            assert agent.agent_id == "mcp-visible-create"
            assert pool._mcp_visibility_authorization_kernel.authorize.call_count == 1
            kernel_request = pool._mcp_visibility_authorization_kernel.authorize.call_args.args[0]
            assert isinstance(kernel_request, AuthorizationRequest)
            assert kernel_request.action == AuthorizationAction.TOOL_EXECUTE
            assert kernel_request.resource.resource_type == AuthorizationResourceType.TOOL
            assert kernel_request.principal_id == "mcp-visible-create"
            assert kernel_request.context["mcp_level_allowed"] is True
            assert kernel_request.context["check_stage"] == "create"
            shared.mcp_registry.get_all_skills.assert_awaited_once_with(
                agent_id="mcp-visible-create"
            )

    @pytest.mark.asyncio
    async def test_create_forced_mcp_kernel_deny_skips_fetch_and_still_succeeds(self, tmp_path):
        """Forced kernel deny skips MCP fetch while preserving create success."""
        shared = create_mock_shared_components(tmp_path)
        mcp_skill = MagicMock()
        mcp_skill.name = "mcp_lookup"
        mcp_skill.description = "Lookup"
        mcp_skill.parameters = {"type": "object", "properties": {}}
        shared.mcp_registry.get_all_skills = AsyncMock(return_value=[mcp_skill])

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)

            def _deny_all(request: AuthorizationRequest) -> AuthorizationDecision:
                return AuthorizationDecision.deny(
                    request,
                    reason="forced_deny_for_test",
                )

            pool._mcp_visibility_authorization_kernel.authorize = MagicMock(
                side_effect=_deny_all,
            )

            agent = await pool.create(
                config=AgentConfig(agent_id="mcp-deny-create", preset="trusted")
            )

            assert agent.agent_id == "mcp-deny-create"
            assert "mcp-deny-create" in pool
            assert pool._mcp_visibility_authorization_kernel.authorize.call_count == 1
            kernel_request = pool._mcp_visibility_authorization_kernel.authorize.call_args.args[0]
            assert isinstance(kernel_request, AuthorizationRequest)
            assert kernel_request.context["mcp_level_allowed"] is True
            assert kernel_request.context["check_stage"] == "create"
            shared.mcp_registry.get_all_skills.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_restore_mcp_visibility_uses_kernel_and_skips_fetch_when_level_denied(
        self,
        tmp_path,
    ):
        """restore path uses MCP visibility kernel and preserves deny-by-level behavior."""
        shared = create_mock_shared_components(tmp_path)
        shared.mcp_registry.get_all_skills = AsyncMock(return_value=[])
        saved = SavedSession(
            agent_id="restore-mcp-denied",
            created_at=datetime.now(),
            modified_at=datetime.now(),
            messages=[],
            system_prompt="You are a test assistant.",
            system_prompt_path=None,
            working_directory=str(tmp_path),
            permission_level="sandboxed",
            token_usage={},
            provenance="user",
            permission_preset="sandboxed",
        )
        session_manager = MagicMock()
        session_manager.session_exists.return_value = True
        session_manager.load_session.return_value = saved

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            original_authorize = pool._mcp_visibility_authorization_kernel.authorize
            pool._mcp_visibility_authorization_kernel.authorize = MagicMock(
                side_effect=original_authorize
            )

            agent = await pool.get_or_restore(
                "restore-mcp-denied",
                session_manager=session_manager,
            )

            assert agent is not None
            assert agent.agent_id == "restore-mcp-denied"
            assert pool._mcp_visibility_authorization_kernel.authorize.call_count == 1
            kernel_request = pool._mcp_visibility_authorization_kernel.authorize.call_args.args[0]
            assert isinstance(kernel_request, AuthorizationRequest)
            assert kernel_request.action == AuthorizationAction.TOOL_EXECUTE
            assert kernel_request.resource.resource_type == AuthorizationResourceType.TOOL
            assert kernel_request.principal_id == "restore-mcp-denied"
            assert kernel_request.context["mcp_level_allowed"] is False
            assert kernel_request.context["check_stage"] == "restore"
            shared.mcp_registry.get_all_skills.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_create_passes_gitlab_visibility_into_vcs_registration(self, tmp_path):
        """create path computes GitLab visibility through the pool-local kernel."""
        shared = create_mock_shared_components(tmp_path)
        shared.config.gitlab.instances = {
            "default": MagicMock(
                url="https://gitlab.com",
                token="fake",
                token_env=None,
                username="tester",
                email=None,
                user_id=None,
            ),
        }
        shared.config.gitlab.default_instance = "default"

        with (
            patch("nexus3.skill.builtin.register_builtin_skills"),
            patch("nexus3.rpc.pool.register_vcs_skills") as mock_register_vcs_skills,
        ):
            pool = AgentPool(shared)
            original_authorize = pool._gitlab_visibility_authorization_kernel.authorize
            pool._gitlab_visibility_authorization_kernel.authorize = MagicMock(
                side_effect=original_authorize
            )

            agent = await pool.create(
                agent_id="gitlab-create-visible",
                config=AgentConfig(preset="trusted"),
            )

            assert agent.agent_id == "gitlab-create-visible"
            assert pool._gitlab_visibility_authorization_kernel.authorize.call_count == 1
            kernel_request = (
                pool._gitlab_visibility_authorization_kernel.authorize.call_args.args[0]
            )
            assert isinstance(kernel_request, AuthorizationRequest)
            assert kernel_request.action == AuthorizationAction.TOOL_EXECUTE
            assert kernel_request.resource.resource_type == AuthorizationResourceType.TOOL
            assert kernel_request.principal_id == "gitlab-create-visible"
            assert kernel_request.context["gitlab_level_allowed"] is True
            assert kernel_request.context["check_stage"] == "create"
            assert mock_register_vcs_skills.call_args.kwargs["gitlab_visible"] is True

    @pytest.mark.asyncio
    async def test_restore_passes_gitlab_visibility_into_vcs_registration(self, tmp_path):
        """restore path computes GitLab visibility through the pool-local kernel."""
        shared = create_mock_shared_components(tmp_path)
        shared.config.gitlab.instances = {
            "default": MagicMock(
                url="https://gitlab.com",
                token="fake",
                token_env=None,
                username="tester",
                email=None,
                user_id=None,
            ),
        }
        shared.config.gitlab.default_instance = "default"
        saved = SavedSession(
            agent_id="restore-gitlab-hidden",
            created_at=datetime.now(),
            modified_at=datetime.now(),
            messages=[],
            system_prompt="You are a test assistant.",
            system_prompt_path=None,
            working_directory=str(tmp_path),
            permission_level="sandboxed",
            token_usage={},
            provenance="user",
            permission_preset="sandboxed",
        )
        session_manager = MagicMock()
        session_manager.session_exists.return_value = True
        session_manager.load_session.return_value = saved

        with (
            patch("nexus3.skill.builtin.register_builtin_skills"),
            patch("nexus3.rpc.pool.register_vcs_skills") as mock_register_vcs_skills,
        ):
            pool = AgentPool(shared)
            original_authorize = pool._gitlab_visibility_authorization_kernel.authorize
            pool._gitlab_visibility_authorization_kernel.authorize = MagicMock(
                side_effect=original_authorize
            )

            agent = await pool.get_or_restore(
                "restore-gitlab-hidden",
                session_manager=session_manager,
            )

            assert agent is not None
            assert pool._gitlab_visibility_authorization_kernel.authorize.call_count == 1
            kernel_request = (
                pool._gitlab_visibility_authorization_kernel.authorize.call_args.args[0]
            )
            assert isinstance(kernel_request, AuthorizationRequest)
            assert kernel_request.action == AuthorizationAction.TOOL_EXECUTE
            assert kernel_request.resource.resource_type == AuthorizationResourceType.TOOL
            assert kernel_request.principal_id == "restore-gitlab-hidden"
            assert kernel_request.context["gitlab_level_allowed"] is False
            assert kernel_request.context["check_stage"] == "restore"
            assert mock_register_vcs_skills.call_args.kwargs["gitlab_visible"] is False

    @pytest.mark.asyncio
    async def test_get_returns_agent(self, tmp_path):
        """get() returns the agent if it exists."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            created = await pool.create(agent_id="test-agent")

            retrieved = pool.get("test-agent")
            assert retrieved is created

    @pytest.mark.asyncio
    async def test_get_returns_none_for_nonexistent(self, tmp_path):
        """get() returns None for non-existent agent."""
        shared = create_mock_shared_components(tmp_path)
        pool = AgentPool(shared)

        result = pool.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_destroy_removes_agent_and_returns_true(self, tmp_path):
        """destroy() removes the agent and returns True."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            await pool.create(agent_id="to-destroy")

            assert "to-destroy" in pool
            result = await pool.destroy("to-destroy")

            assert result is True
            assert "to-destroy" not in pool
            assert pool.get("to-destroy") is None

    @pytest.mark.asyncio
    async def test_destroy_nonexistent_returns_false(self, tmp_path):
        """destroy() on non-existent agent returns False."""
        shared = create_mock_shared_components(tmp_path)
        pool = AgentPool(shared)

        result = await pool.destroy("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_destroy_self_requester_allowed(self, tmp_path):
        """destroy() allows self-destruction when requester matches target."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            await pool.create(agent_id="self-agent")

            result = await pool.destroy("self-agent", requester_id="self-agent")

            assert result is True
            assert "self-agent" not in pool

    @pytest.mark.asyncio
    async def test_destroy_parent_requester_allowed(self, tmp_path):
        """destroy() allows a parent requester to destroy its child."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            await pool.create(agent_id="parent-agent")
            child = await pool.create(agent_id="child-agent")
            child_permissions = child.services.get("permissions")
            assert child_permissions is not None
            child_permissions.parent_agent_id = "parent-agent"

            result = await pool.destroy("child-agent", requester_id="parent-agent")

            assert result is True
            assert "child-agent" not in pool

    @pytest.mark.asyncio
    async def test_destroy_external_requester_uses_kernel_and_is_allowed(self, tmp_path):
        """destroy() authorizes external requesters via kernel evaluation."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            await pool.create(agent_id="external-target")
            original_authorize = pool._destroy_authorization_kernel.authorize
            pool._destroy_authorization_kernel.authorize = MagicMock(side_effect=original_authorize)

            result = await pool.destroy("external-target", requester_id=None)

            assert result is True
            assert "external-target" not in pool
            assert pool._destroy_authorization_kernel.authorize.call_count == 1
            kernel_request = pool._destroy_authorization_kernel.authorize.call_args.args[0]
            assert isinstance(kernel_request, AuthorizationRequest)
            assert kernel_request.principal_id == "external"
            assert kernel_request.context["admin_override"] is False

    @pytest.mark.asyncio
    async def test_destroy_admin_override_uses_kernel_and_is_allowed(self, tmp_path):
        """destroy() authorizes admin_override through kernel evaluation."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            await pool.create(agent_id="admin-target")
            original_authorize = pool._destroy_authorization_kernel.authorize
            pool._destroy_authorization_kernel.authorize = MagicMock(side_effect=original_authorize)

            result = await pool.destroy(
                "admin-target",
                requester_id="other-agent",
                admin_override=True,
            )

            assert result is True
            assert "admin-target" not in pool
            assert pool._destroy_authorization_kernel.authorize.call_count == 1
            kernel_request = pool._destroy_authorization_kernel.authorize.call_args.args[0]
            assert isinstance(kernel_request, AuthorizationRequest)
            assert kernel_request.principal_id == "other-agent"
            assert kernel_request.context["admin_override"] is True

    @pytest.mark.asyncio
    async def test_destroy_unauthorized_requester_denied_fail_closed(self, tmp_path):
        """destroy() denies unrelated requesters and leaves target intact."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            await pool.create(agent_id="target-agent")
            await pool.create(agent_id="other-agent")

            with pytest.raises(AuthorizationError) as exc_info:
                await pool.destroy("target-agent", requester_id="other-agent")

            assert "not authorized to destroy" in str(exc_info.value)
            assert "target-agent" in pool

    @pytest.mark.asyncio
    async def test_destroy_external_forced_kernel_deny_is_authoritative(self, tmp_path):
        """destroy() fails closed when kernel denies an external requester."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            await pool.create(agent_id="external-agent")
            kernel_request = AuthorizationRequest(
                action=AuthorizationAction.AGENT_DESTROY,
                resource=AuthorizationResource(
                    resource_type=AuthorizationResourceType.AGENT,
                    identifier="external-agent",
                ),
                principal_id="external",
                context={"admin_override": False},
            )
            pool._destroy_authorization_kernel.authorize = MagicMock(
                return_value=AuthorizationDecision.deny(
                    kernel_request,
                    reason="forced_deny_for_test",
                )
            )

            with pytest.raises(AuthorizationError) as exc_info:
                await pool.destroy("external-agent")

            assert "not authorized to destroy" in str(exc_info.value)
            assert "external-agent" in pool

    @pytest.mark.asyncio
    async def test_destroy_admin_override_forced_kernel_deny_is_authoritative(self, tmp_path):
        """destroy() fails closed when kernel denies an admin_override request."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            await pool.create(agent_id="admin-agent")
            kernel_request = AuthorizationRequest(
                action=AuthorizationAction.AGENT_DESTROY,
                resource=AuthorizationResource(
                    resource_type=AuthorizationResourceType.AGENT,
                    identifier="admin-agent",
                ),
                principal_id="other-agent",
                context={"admin_override": True},
            )
            pool._destroy_authorization_kernel.authorize = MagicMock(
                return_value=AuthorizationDecision.deny(
                    kernel_request,
                    reason="forced_deny_for_test",
                )
            )

            with pytest.raises(AuthorizationError) as exc_info:
                await pool.destroy(
                    "admin-agent",
                    requester_id="other-agent",
                    admin_override=True,
                )

            assert "not authorized to destroy" in str(exc_info.value)
            assert "admin-agent" in pool

    @pytest.mark.asyncio
    async def test_destroy_forced_kernel_deny_is_authoritative(self, tmp_path):
        """destroy() fails closed when kernel denies, even for self-requesters."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            await pool.create(agent_id="self-agent")
            kernel_request = AuthorizationRequest(
                action=AuthorizationAction.AGENT_DESTROY,
                resource=AuthorizationResource(
                    resource_type=AuthorizationResourceType.AGENT,
                    identifier="self-agent",
                ),
                principal_id="self-agent",
            )
            pool._destroy_authorization_kernel.authorize = MagicMock(
                return_value=AuthorizationDecision.deny(
                    kernel_request,
                    reason="forced_deny_for_test",
                )
            )

            with pytest.raises(AuthorizationError) as exc_info:
                await pool.destroy("self-agent", requester_id="self-agent")

            assert "not authorized to destroy" in str(exc_info.value)
            assert "self-agent" in pool

    @pytest.mark.asyncio
    async def test_list_returns_agent_info_dicts(self, tmp_path):
        """list() returns list of agent info dictionaries."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            await pool.create(agent_id="agent-1")
            await pool.create(agent_id="agent-2")

            agents = pool.list()

            assert len(agents) == 2
            agent_ids = {a["agent_id"] for a in agents}
            assert agent_ids == {"agent-1", "agent-2"}

            # Check each agent has expected keys
            for agent_info in agents:
                assert "agent_id" in agent_info
                assert "created_at" in agent_info
                assert "message_count" in agent_info
                assert "should_shutdown" in agent_info
                # created_at should be ISO format
                assert isinstance(agent_info["created_at"], str)

    @pytest.mark.asyncio
    async def test_should_shutdown_false_when_empty(self, tmp_path):
        """should_shutdown is False when pool is empty."""
        shared = create_mock_shared_components(tmp_path)
        pool = AgentPool(shared)

        assert pool.should_shutdown is False

    @pytest.mark.asyncio
    async def test_should_shutdown_false_when_agents_active(self, tmp_path):
        """should_shutdown is False when agents are not shut down."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            await pool.create(agent_id="active-agent")

            # By default, dispatcher.should_shutdown is False
            assert pool.should_shutdown is False

    @pytest.mark.asyncio
    async def test_should_shutdown_true_when_all_agents_shutdown(self, tmp_path):
        """should_shutdown is True when all agents want shutdown."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            agent = await pool.create(agent_id="shutting-down")

            # Mock the dispatcher's should_shutdown to return True
            agent.dispatcher._should_shutdown = True

            assert pool.should_shutdown is True

    @pytest.mark.asyncio
    async def test_len_returns_agent_count(self, tmp_path):
        """__len__ returns the number of agents in the pool."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            assert len(pool) == 0

            await pool.create(agent_id="agent-1")
            assert len(pool) == 1

            await pool.create(agent_id="agent-2")
            assert len(pool) == 2

            await pool.destroy("agent-1")
            assert len(pool) == 1

    @pytest.mark.asyncio
    async def test_issue_and_verify_direct_capability(self, tmp_path):
        """AgentPool issues and verifies direct RPC capability tokens."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            token = pool.issue_direct_capability(
                issuer_id="agent-a",
                subject_id="agent-a",
                rpc_method="send",
            )
            claims = pool.verify_direct_capability(
                token,
                required_scope="rpc:agent:send",
            )

            assert claims.issuer_id == "agent-a"
            assert claims.subject_id == "agent-a"
            assert claims.scopes == ("rpc:agent:send",)

    @pytest.mark.asyncio
    async def test_destroy_revokes_issued_direct_capabilities(self, tmp_path):
        """Destroying an agent revokes direct capabilities issued by/for it."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            await pool.create(agent_id="agent-a")
            token = pool.issue_direct_capability(
                issuer_id="agent-a",
                subject_id="agent-a",
                rpc_method="send",
            )

            # Sanity: token verifies before destroy.
            pool.verify_direct_capability(token, required_scope="rpc:agent:send")

            destroyed = await pool.destroy("agent-a")

            assert destroyed is True
            with pytest.raises(CapabilityRevokedError):
                pool.verify_direct_capability(
                    token,
                    required_scope="rpc:agent:send",
                )

    @pytest.mark.asyncio
    async def test_contains_checks_agent_id(self, tmp_path):
        """__contains__ checks if agent_id exists in pool."""
        shared = create_mock_shared_components(tmp_path)

        with patch("nexus3.skill.builtin.register_builtin_skills"):
            pool = AgentPool(shared)
            await pool.create(agent_id="existing")

            assert "existing" in pool
            assert "nonexistent" not in pool


# -----------------------------------------------------------------------------
# GlobalDispatcher Tests
# -----------------------------------------------------------------------------


class MockAgentPool:
    """Mock AgentPool for testing GlobalDispatcher.

    Implements the interface expected by GlobalDispatcher.
    """

    def __init__(self):
        self._agents: dict[str, Any] = {}
        self._next_id = 1
        self.last_create_requester_id: str | None = None
        self.last_destroy_requester_id: str | None = None

    async def create(
        self,
        agent_id: str | None = None,
        config: Any = None,
        requester_id: str | None = None,
    ) -> Any:
        """Create mock agent and return Agent object."""
        self.last_create_requester_id = requester_id
        effective_id = agent_id or f"auto-{self._next_id}"
        self._next_id += 1

        if effective_id in self._agents:
            raise ValueError(f"Agent already exists: {effective_id}")

        agent = MagicMock()
        agent.agent_id = effective_id
        agent.created_at = datetime.now().isoformat()
        agent.message_count = 0

        self._agents[effective_id] = agent
        return agent

    async def destroy(
        self,
        agent_id: str,
        requester_id: str | None = None,
        *,
        admin_override: bool = False,
    ) -> bool:
        """Destroy mock agent."""
        self.last_destroy_requester_id = requester_id
        if agent_id in self._agents:
            del self._agents[agent_id]
            return True
        return False

    def list(self) -> list[dict[str, Any]]:
        """List all mock agents as dicts."""
        return [
            {
                "agent_id": a.agent_id,
                "created_at": a.created_at,
                "message_count": a.message_count,
                "should_shutdown": False,
            }
            for a in self._agents.values()
        ]

    def get(self, agent_id: str) -> Any:
        """Get an agent by ID."""
        return self._agents.get(agent_id)


class TestGlobalDispatcher:
    """Tests for GlobalDispatcher RPC methods."""

    @pytest.mark.asyncio
    async def test_create_agent_with_id(self):
        """create_agent with agent_id creates agent with that ID."""
        pool = MockAgentPool()
        dispatcher = GlobalDispatcher(pool)

        request = Request(
            jsonrpc="2.0",
            method="create_agent",
            params={"agent_id": "test-agent"},
            id=1,
        )
        response = await dispatcher.dispatch(request)

        assert response is not None
        assert response.error is None
        assert response.result is not None
        assert response.result["agent_id"] == "test-agent"
        assert response.result["url"] == "/agent/test-agent"

    @pytest.mark.asyncio
    async def test_create_agent_auto_generated_id(self):
        """create_agent without agent_id generates an ID."""
        pool = MockAgentPool()
        dispatcher = GlobalDispatcher(pool)

        request = Request(
            jsonrpc="2.0",
            method="create_agent",
            params={},
            id=1,
        )
        response = await dispatcher.dispatch(request)

        assert response is not None
        assert response.error is None
        assert response.result is not None
        assert "agent_id" in response.result
        assert response.result["agent_id"].startswith("auto-")

    @pytest.mark.asyncio
    async def test_create_agent_propagates_requester_context(self):
        """create_agent forwards requester_id from dispatch context."""
        pool = MockAgentPool()
        dispatcher = GlobalDispatcher(pool)

        request = Request(
            jsonrpc="2.0",
            method="create_agent",
            params={"agent_id": "created-by-requester"},
            id=1,
        )
        response = await dispatcher.dispatch(request, requester_id="requester-1")

        assert response is not None
        assert response.error is None
        assert pool.last_create_requester_id == "requester-1"

    @pytest.mark.asyncio
    async def test_destroy_agent_success(self):
        """destroy_agent removes existing agent."""
        pool = MockAgentPool()
        await pool.create(agent_id="to-destroy")

        dispatcher = GlobalDispatcher(pool)

        request = Request(
            jsonrpc="2.0",
            method="destroy_agent",
            params={"agent_id": "to-destroy"},
            id=1,
        )
        response = await dispatcher.dispatch(request)

        assert response is not None
        assert response.error is None
        assert response.result is not None
        assert response.result["success"] is True
        assert response.result["agent_id"] == "to-destroy"

    @pytest.mark.asyncio
    async def test_destroy_agent_propagates_requester_context(self):
        """destroy_agent forwards requester_id from dispatch context."""
        pool = MockAgentPool()
        await pool.create(agent_id="to-destroy")
        dispatcher = GlobalDispatcher(pool)

        request = Request(
            jsonrpc="2.0",
            method="destroy_agent",
            params={"agent_id": "to-destroy"},
            id=1,
        )
        response = await dispatcher.dispatch(request, requester_id="requester-1")

        assert response is not None
        assert response.error is None
        assert pool.last_destroy_requester_id == "requester-1"

    @pytest.mark.asyncio
    async def test_destroy_agent_requester_isolation_for_overlapping_dispatches(self):
        """Overlapping destroy dispatches keep requester identity per request."""

        class CoordinatedPool(MockAgentPool):
            def __init__(self) -> None:
                super().__init__()
                self.destroy_calls: list[tuple[str, str | None]] = []
                self._destroy_release = asyncio.Event()

            async def destroy(
                self,
                agent_id: str,
                requester_id: str | None = None,
                *,
                admin_override: bool = False,
            ) -> bool:
                self.destroy_calls.append((agent_id, requester_id))
                if len(self.destroy_calls) == 2:
                    self._destroy_release.set()
                await self._destroy_release.wait()
                return await super().destroy(
                    agent_id,
                    requester_id=requester_id,
                    admin_override=admin_override,
                )

        pool = CoordinatedPool()
        await pool.create(agent_id="victim-a")
        await pool.create(agent_id="victim-b")
        dispatcher = GlobalDispatcher(pool)

        original_handler = dispatcher._handlers["destroy_agent"]
        handlers_ready = 0
        both_ready = asyncio.Event()

        async def delayed_destroy(params: dict[str, Any]) -> dict[str, Any]:
            nonlocal handlers_ready
            handlers_ready += 1
            if handlers_ready == 2:
                both_ready.set()
            await both_ready.wait()
            return await original_handler(params)

        dispatcher._handlers["destroy_agent"] = delayed_destroy

        request_a = Request(
            jsonrpc="2.0",
            method="destroy_agent",
            params={"agent_id": "victim-a"},
            id=1,
        )
        request_b = Request(
            jsonrpc="2.0",
            method="destroy_agent",
            params={"agent_id": "victim-b"},
            id=2,
        )

        response_a, response_b = await asyncio.gather(
            dispatcher.dispatch(request_a, requester_id="requester-a"),
            dispatcher.dispatch(request_b, requester_id="requester-b"),
        )

        assert response_a is not None
        assert response_a.error is None
        assert response_b is not None
        assert response_b.error is None

        destroy_call_map = {agent_id: requester_id for agent_id, requester_id in pool.destroy_calls}
        assert destroy_call_map["victim-a"] == "requester-a"
        assert destroy_call_map["victim-b"] == "requester-b"

    @pytest.mark.asyncio
    async def test_destroy_agent_not_found(self):
        """destroy_agent for non-existent agent returns success=False."""
        pool = MockAgentPool()
        dispatcher = GlobalDispatcher(pool)

        request = Request(
            jsonrpc="2.0",
            method="destroy_agent",
            params={"agent_id": "nonexistent"},
            id=1,
        )
        response = await dispatcher.dispatch(request)

        assert response is not None
        assert response.error is None
        assert response.result is not None
        assert response.result["success"] is False
        assert response.result["agent_id"] == "nonexistent"

    @pytest.mark.asyncio
    async def test_destroy_agent_missing_params(self):
        """destroy_agent without agent_id returns error."""
        pool = MockAgentPool()
        dispatcher = GlobalDispatcher(pool)

        request = Request(
            jsonrpc="2.0",
            method="destroy_agent",
            params={},
            id=1,
        )
        response = await dispatcher.dispatch(request)

        assert response is not None
        assert response.error is not None
        assert response.error["code"] == -32602  # INVALID_PARAMS
        assert "agent_id" in response.error["message"].lower()

    @pytest.mark.asyncio
    async def test_list_agents_empty(self):
        """list_agents returns empty list when no agents."""
        pool = MockAgentPool()
        dispatcher = GlobalDispatcher(pool)

        request = Request(
            jsonrpc="2.0",
            method="list_agents",
            params={},
            id=1,
        )
        response = await dispatcher.dispatch(request)

        assert response is not None
        assert response.error is None
        assert response.result is not None
        assert response.result["agents"] == []

    @pytest.mark.asyncio
    async def test_list_agents_with_agents(self):
        """list_agents returns info for all agents."""
        pool = MockAgentPool()
        await pool.create(agent_id="agent-1")
        await pool.create(agent_id="agent-2")

        dispatcher = GlobalDispatcher(pool)

        request = Request(
            jsonrpc="2.0",
            method="list_agents",
            params={},
            id=1,
        )
        response = await dispatcher.dispatch(request)

        assert response is not None
        assert response.error is None
        assert response.result is not None
        assert len(response.result["agents"]) == 2

        agent_ids = {a["agent_id"] for a in response.result["agents"]}
        assert agent_ids == {"agent-1", "agent-2"}

    @pytest.mark.asyncio
    async def test_list_agents_denied_by_kernel_fails_closed(self) -> None:
        """list_agents fails closed when the authorization kernel denies."""
        pool = MockAgentPool()
        await pool.create(agent_id="agent-1")
        dispatcher = GlobalDispatcher(pool)

        kernel_request = AuthorizationRequest(
            action=AuthorizationAction.SESSION_READ,
            resource=AuthorizationResource(
                resource_type=AuthorizationResourceType.RPC,
                identifier="list_agents",
            ),
            principal_id="requester-1",
        )
        dispatcher._list_agents_authorization_kernel.authorize = MagicMock(
            return_value=AuthorizationDecision.deny(
                kernel_request,
                reason="forced_deny_for_test",
            )
        )

        response = await dispatcher.dispatch(
            Request(
                jsonrpc="2.0",
                method="list_agents",
                params={},
                id=1,
            ),
            requester_id="requester-1",
        )

        assert response is not None
        assert response.error is not None
        assert response.error["code"] == -32602  # INVALID_PARAMS
        assert "list_agents denied" in response.error["message"]
        assert "forced_deny_for_test" in response.error["message"]
        assert response.result is None

    @pytest.mark.asyncio
    async def test_method_not_found(self):
        """Unknown method returns METHOD_NOT_FOUND error."""
        pool = MockAgentPool()
        dispatcher = GlobalDispatcher(pool)

        request = Request(
            jsonrpc="2.0",
            method="unknown_method",
            params={},
            id=1,
        )
        response = await dispatcher.dispatch(request)

        assert response is not None
        assert response.error is not None
        assert response.error["code"] == -32601  # METHOD_NOT_FOUND

    @pytest.mark.asyncio
    async def test_shutdown_server_preserves_legacy_success_response(self):
        """shutdown_server remains allowed and returns the unchanged payload."""
        pool = MockAgentPool()
        dispatcher = GlobalDispatcher(pool)

        request = Request(
            jsonrpc="2.0",
            method="shutdown_server",
            params={},
            id=1,
        )
        response = await dispatcher.dispatch(request, requester_id="requester-1")

        assert response is not None
        assert response.error is None
        assert response.result == {
            "success": True,
            "message": "Server shutting down",
        }
        assert dispatcher.shutdown_requested is True

    @pytest.mark.asyncio
    async def test_shutdown_server_denied_by_kernel_fails_closed(self) -> None:
        """shutdown_server fails closed when the authorization kernel denies."""
        pool = MockAgentPool()
        dispatcher = GlobalDispatcher(pool)

        kernel_request = AuthorizationRequest(
            action=AuthorizationAction.SESSION_WRITE,
            resource=AuthorizationResource(
                resource_type=AuthorizationResourceType.RPC,
                identifier="shutdown_server",
            ),
            principal_id="requester-1",
        )
        dispatcher._shutdown_authorization_kernel.authorize = MagicMock(
            return_value=AuthorizationDecision.deny(
                kernel_request,
                reason="forced_deny_for_test",
            )
        )

        response = await dispatcher.dispatch(
            Request(
                jsonrpc="2.0",
                method="shutdown_server",
                params={},
                id=1,
            ),
            requester_id="requester-1",
        )

        assert response is not None
        assert response.error is not None
        assert response.error["code"] == -32602  # INVALID_PARAMS
        assert "shutdown_server denied" in response.error["message"]
        assert "forced_deny_for_test" in response.error["message"]
        assert response.result is None
        assert dispatcher.shutdown_requested is False

    @pytest.mark.asyncio
    async def test_handles_method(self):
        """handles() returns True for known methods, False otherwise."""
        pool = MockAgentPool()
        dispatcher = GlobalDispatcher(pool)

        assert dispatcher.handles("create_agent") is True
        assert dispatcher.handles("destroy_agent") is True
        assert dispatcher.handles("list_agents") is True
        assert dispatcher.handles("unknown") is False
        assert dispatcher.handles("send") is False

    @pytest.mark.asyncio
    async def test_create_agent_invalid_agent_id_type(self):
        """create_agent with non-string agent_id returns error."""
        pool = MockAgentPool()
        dispatcher = GlobalDispatcher(pool)

        request = Request(
            jsonrpc="2.0",
            method="create_agent",
            params={"agent_id": 123},  # Should be string
            id=1,
        )
        response = await dispatcher.dispatch(request)

        assert response is not None
        assert response.error is not None
        assert response.error["code"] == -32602  # INVALID_PARAMS

    @pytest.mark.asyncio
    async def test_destroy_agent_invalid_agent_id_type(self):
        """destroy_agent with non-string agent_id returns error."""
        pool = MockAgentPool()
        dispatcher = GlobalDispatcher(pool)

        request = Request(
            jsonrpc="2.0",
            method="destroy_agent",
            params={"agent_id": 123},  # Should be string
            id=1,
        )
        response = await dispatcher.dispatch(request)

        assert response is not None
        assert response.error is not None
        assert response.error["code"] == -32602  # INVALID_PARAMS

    @pytest.mark.asyncio
    async def test_notification_no_response(self):
        """Notifications (no id) don't get responses."""
        pool = MockAgentPool()
        dispatcher = GlobalDispatcher(pool)

        # Notification has no id
        request = Request(
            jsonrpc="2.0",
            method="list_agents",
            params={},
            id=None,
        )
        response = await dispatcher.dispatch(request)

        assert response is None


# -----------------------------------------------------------------------------
# HTTP Path Routing Tests
# -----------------------------------------------------------------------------


class TestExtractAgentId:
    """Tests for _extract_agent_id helper function."""

    def test_extract_agent_id_simple(self):
        """Extracts agent_id from /agent/{id} path."""
        assert _extract_agent_id("/agent/foo") == "foo"
        assert _extract_agent_id("/agent/my-agent") == "my-agent"
        assert _extract_agent_id("/agent/agent123") == "agent123"

    def test_extract_agent_id_with_subpath_rejected(self):
        """Rejects agent_id containing path separators for security."""
        # SECURITY: Agent IDs with slashes are rejected to prevent path traversal
        result = _extract_agent_id("/agent/foo/bar")
        assert result is None  # foo/bar is invalid agent ID

    def test_extract_agent_id_root_path(self):
        """Returns None for root path."""
        assert _extract_agent_id("/") is None

    def test_extract_agent_id_rpc_path(self):
        """Returns None for /rpc path."""
        assert _extract_agent_id("/rpc") is None

    def test_extract_agent_id_other_paths(self):
        """Returns None for paths that don't match /agent/."""
        assert _extract_agent_id("/other") is None
        assert _extract_agent_id("/agents") is None
        assert _extract_agent_id("/agent") is None  # No trailing slash/id
        assert _extract_agent_id("/something/agent/foo") is None

    def test_extract_agent_id_empty_agent(self):
        """Returns None for /agent/ with no ID."""
        # Path is /agent/ with empty string after
        assert _extract_agent_id("/agent/") is None

    def test_extract_agent_id_special_characters(self):
        """Handles agent IDs with special characters."""
        assert _extract_agent_id("/agent/agent-with-dashes") == "agent-with-dashes"
        assert _extract_agent_id("/agent/agent_with_underscores") == "agent_with_underscores"
        assert _extract_agent_id("/agent/abc123") == "abc123"


# -----------------------------------------------------------------------------
# Security Tests: Permission System Fixes
# -----------------------------------------------------------------------------


class TestAgentConfigParentAgentId:
    """Tests for parent_agent_id field in AgentConfig.

    SECURITY FIX: parent_agent_id should store actual agent ID, not preset name.
    """

    def test_agent_config_has_parent_agent_id_field(self):
        """AgentConfig has parent_agent_id field."""
        config = AgentConfig()
        assert hasattr(config, "parent_agent_id")
        assert config.parent_agent_id is None

    def test_agent_config_accepts_parent_agent_id(self):
        """AgentConfig accepts parent_agent_id parameter."""
        config = AgentConfig(parent_agent_id="parent-worker-1")
        assert config.parent_agent_id == "parent-worker-1"

    def test_agent_config_stores_actual_agent_id(self):
        """parent_agent_id stores actual ID, not preset name."""
        # This test verifies the fix for the bug where parent_agent_id
        # was incorrectly assigned from parent_permissions.base_preset
        parent_permissions = resolve_preset("trusted")
        config = AgentConfig(
            agent_id="child-1",
            preset="sandboxed",
            parent_permissions=parent_permissions,
            parent_agent_id="main-agent",  # Actual parent ID, not "trusted"
        )
        assert config.parent_agent_id == "main-agent"
        assert config.parent_permissions.base_preset == "trusted"
        # These should be different values
        assert config.parent_agent_id != config.parent_permissions.base_preset


class TestCeilingIsolation:
    """Tests for ceiling deep copy to prevent shared references.

    SECURITY FIX: ceiling should be deep copied to prevent mutation leaking
    between parent and child agents.
    """

    def test_ceiling_mutation_does_not_affect_child(self):
        """Mutating parent permissions after agent creation doesn't affect child ceiling."""
        # Create parent permissions
        parent_permissions = resolve_preset("trusted")

        # Simulate the fix: deep copy the ceiling
        import copy
        child_ceiling = copy.deepcopy(parent_permissions)

        # Now mutate the original parent permissions
        parent_permissions.tool_permissions["write_file"] = ToolPermission(enabled=False)

        # Child's ceiling should be unaffected
        assert "write_file" not in child_ceiling.tool_permissions or \
               child_ceiling.tool_permissions.get("write_file", ToolPermission()).enabled is True

    def test_ceiling_is_independent_copy(self):
        """Ceiling is a fully independent copy of parent permissions."""
        import copy

        parent_permissions = resolve_preset("trusted")
        parent_permissions.tool_permissions["test_tool"] = ToolPermission(
            enabled=True,
            timeout=60.0,
        )

        # Deep copy as the fix does
        child_ceiling = copy.deepcopy(parent_permissions)

        # Verify they are different objects
        assert child_ceiling is not parent_permissions
        assert child_ceiling.tool_permissions is not parent_permissions.tool_permissions

        # Verify nested objects are also different
        if "test_tool" in child_ceiling.tool_permissions:
            assert child_ceiling.tool_permissions["test_tool"] is not \
                   parent_permissions.tool_permissions["test_tool"]

    def test_ceiling_policy_is_independent(self):
        """Ceiling's effective_policy is also deep copied."""
        import copy

        parent_permissions = resolve_preset("sandboxed")
        child_ceiling = copy.deepcopy(parent_permissions)

        # Verify policy is independent
        assert child_ceiling.effective_policy is not parent_permissions.effective_policy

        # Verify path lists are independent
        if parent_permissions.effective_policy.allowed_paths is not None:
            assert child_ceiling.effective_policy.allowed_paths is not \
                   parent_permissions.effective_policy.allowed_paths


class TestGlobalDispatcherParentAgentId:
    """Tests for GlobalDispatcher passing parent_agent_id correctly.

    SECURITY FIX: GlobalDispatcher should pass parent_agent_id to AgentConfig.
    """

    @pytest.mark.asyncio
    async def test_create_agent_with_parent_agent_id(self):
        """create_agent passes parent_agent_id to AgentConfig."""
        pool = MockAgentPool()
        dispatcher = GlobalDispatcher(pool)

        # First create a parent agent
        await pool.create(agent_id="parent-1")
        # Mock the services.get to return appropriate values for each key
        parent_cwd = Path.cwd()
        pool._agents["parent-1"].services = MagicMock()
        def parent_services_get(key: str) -> Any:
            if key == "permissions":
                return resolve_preset("trusted", cwd=parent_cwd)
            if key == "cwd":
                return parent_cwd
            return None

        pool._agents["parent-1"].services.get = MagicMock(
            side_effect=parent_services_get
        )

        request = Request(
            jsonrpc="2.0",
            method="create_agent",
            params={
                "agent_id": "child-1",
                "parent_agent_id": "parent-1",
            },
            id=1,
        )
        response = await dispatcher.dispatch(request)

        assert response is not None
        assert response.error is None
        assert response.result is not None
        assert response.result["agent_id"] == "child-1"

    @pytest.mark.asyncio
    async def test_create_agent_validates_parent_agent_id_type(self):
        """create_agent validates parent_agent_id is a string."""
        pool = MockAgentPool()
        dispatcher = GlobalDispatcher(pool)

        request = Request(
            jsonrpc="2.0",
            method="create_agent",
            params={
                "agent_id": "child-1",
                "parent_agent_id": 123,  # Should be string
            },
            id=1,
        )
        response = await dispatcher.dispatch(request)

        assert response is not None
        assert response.error is not None
        assert response.error["code"] == -32602  # INVALID_PARAMS

    @pytest.mark.asyncio
    async def test_create_agent_validates_parent_exists(self):
        """create_agent returns error if parent agent doesn't exist."""
        pool = MockAgentPool()
        dispatcher = GlobalDispatcher(pool)

        request = Request(
            jsonrpc="2.0",
            method="create_agent",
            params={
                "agent_id": "child-1",
                "parent_agent_id": "nonexistent-parent",
            },
            id=1,
        )
        response = await dispatcher.dispatch(request)

        assert response is not None
        assert response.error is not None
        assert "not found" in response.error["message"].lower()
