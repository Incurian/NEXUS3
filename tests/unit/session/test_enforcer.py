"""Unit tests for nexus3.session.enforcer module.

Tests for PermissionEnforcer, particularly the target validation
for nexus_* tools (allowed_targets enforcement).
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nexus3.core.authorization_kernel import AuthorizationDecision
from nexus3.core.permissions import AgentPermissions
from nexus3.core.policy import PermissionLevel, PermissionPolicy
from nexus3.core.presets import ToolPermission
from nexus3.core.types import ToolCall
from nexus3.session.enforcer import AGENT_TARGET_TOOLS, PermissionEnforcer


class TestAgentTargetToolsConstant:
    """Tests for AGENT_TARGET_TOOLS constant."""

    def test_contains_nexus_send(self):
        """nexus_send is in AGENT_TARGET_TOOLS."""
        assert "nexus_send" in AGENT_TARGET_TOOLS

    def test_contains_nexus_status(self):
        """nexus_status is in AGENT_TARGET_TOOLS."""
        assert "nexus_status" in AGENT_TARGET_TOOLS

    def test_contains_nexus_cancel(self):
        """nexus_cancel is in AGENT_TARGET_TOOLS."""
        assert "nexus_cancel" in AGENT_TARGET_TOOLS

    def test_contains_nexus_destroy(self):
        """nexus_destroy is in AGENT_TARGET_TOOLS."""
        assert "nexus_destroy" in AGENT_TARGET_TOOLS

    def test_does_not_contain_nexus_create(self):
        """nexus_create is NOT in AGENT_TARGET_TOOLS (no agent_id param)."""
        assert "nexus_create" not in AGENT_TARGET_TOOLS

    def test_does_not_contain_nexus_shutdown(self):
        """nexus_shutdown is NOT in AGENT_TARGET_TOOLS (no agent_id param)."""
        assert "nexus_shutdown" not in AGENT_TARGET_TOOLS

    def test_is_frozenset(self):
        """AGENT_TARGET_TOOLS is a frozenset."""
        assert isinstance(AGENT_TARGET_TOOLS, frozenset)


class TestCheckTargetAllowedParent:
    """Tests for _check_target_allowed with allowed_targets='parent'."""

    def _make_permissions(
        self,
        parent_agent_id: str | None = None,
        allowed_targets: str | list[str] | None = None,
    ) -> AgentPermissions:
        """Create AgentPermissions with target restriction."""
        tool_permissions = {}
        if allowed_targets is not None:
            tool_permissions["nexus_send"] = ToolPermission(
                enabled=True, allowed_targets=allowed_targets
            )
        return AgentPermissions(
            base_preset="sandboxed",
            effective_policy=PermissionPolicy(
                level=PermissionLevel.SANDBOXED,
                allowed_paths=[Path("/sandbox")],
                blocked_paths=[],
                cwd=Path("/sandbox"),
            ),
            tool_permissions=tool_permissions,
            parent_agent_id=parent_agent_id,
        )

    def _make_tool_call(self, target_agent_id: str) -> ToolCall:
        """Create a nexus_send tool call."""
        return ToolCall(
            id="call-1",
            name="nexus_send",
            arguments={"agent_id": target_agent_id, "content": "Hello"},
        )

    def test_parent_allowed_when_target_matches_parent(self):
        """Target allowed when target_agent_id matches parent_agent_id."""
        enforcer = PermissionEnforcer()
        permissions = self._make_permissions(
            parent_agent_id="parent-agent",
            allowed_targets="parent",
        )
        tool_call = self._make_tool_call("parent-agent")

        result = enforcer._check_target_allowed(tool_call, permissions)
        assert result is None  # No error = allowed

    def test_parent_denied_when_target_not_parent(self):
        """Target denied when target_agent_id does not match parent_agent_id."""
        enforcer = PermissionEnforcer()
        permissions = self._make_permissions(
            parent_agent_id="parent-agent",
            allowed_targets="parent",
        )
        tool_call = self._make_tool_call("other-agent")

        result = enforcer._check_target_allowed(tool_call, permissions)
        assert result is not None
        assert result.error is not None
        assert "can only target parent agent" in result.error
        assert "'parent-agent'" in result.error

    def test_parent_denied_when_no_parent(self):
        """Target denied when agent has no parent (root agent)."""
        enforcer = PermissionEnforcer()
        permissions = self._make_permissions(
            parent_agent_id=None,  # Root agent
            allowed_targets="parent",
        )
        tool_call = self._make_tool_call("any-agent")

        result = enforcer._check_target_allowed(tool_call, permissions)
        assert result is not None
        assert result.error is not None
        assert "can only target parent agent" in result.error
        assert "'none'" in result.error


class TestCheckTargetAllowedChildren:
    """Tests for _check_target_allowed with allowed_targets='children'."""

    def _make_permissions(
        self,
        allowed_targets: str | list[str] | None = None,
    ) -> AgentPermissions:
        """Create AgentPermissions with target restriction."""
        tool_permissions = {}
        if allowed_targets is not None:
            tool_permissions["nexus_send"] = ToolPermission(
                enabled=True, allowed_targets=allowed_targets
            )
        return AgentPermissions(
            base_preset="trusted",
            effective_policy=PermissionPolicy(
                level=PermissionLevel.TRUSTED,
                allowed_paths=None,
                blocked_paths=[],
                cwd=Path("/project"),
            ),
            tool_permissions=tool_permissions,
        )

    def _make_tool_call(self, target_agent_id: str) -> ToolCall:
        """Create a nexus_send tool call."""
        return ToolCall(
            id="call-1",
            name="nexus_send",
            arguments={"agent_id": target_agent_id, "content": "Hello"},
        )

    def test_children_allowed_when_target_is_child(self):
        """Target allowed when target_agent_id is in child_ids."""
        services = MagicMock()
        services.get_child_agent_ids.return_value = {"child-1", "child-2"}
        enforcer = PermissionEnforcer(services=services)

        permissions = self._make_permissions(allowed_targets="children")
        tool_call = self._make_tool_call("child-1")

        result = enforcer._check_target_allowed(tool_call, permissions)
        assert result is None  # No error = allowed

    def test_children_denied_when_target_not_child(self):
        """Target denied when target_agent_id is not in child_ids."""
        services = MagicMock()
        services.get_child_agent_ids.return_value = {"child-1", "child-2"}
        enforcer = PermissionEnforcer(services=services)

        permissions = self._make_permissions(allowed_targets="children")
        tool_call = self._make_tool_call("not-a-child")

        result = enforcer._check_target_allowed(tool_call, permissions)
        assert result is not None
        assert result.error is not None
        assert "can only target child agents" in result.error

    def test_children_denied_when_no_children(self):
        """Target denied when agent has no children."""
        services = MagicMock()
        services.get_child_agent_ids.return_value = set()  # No children
        enforcer = PermissionEnforcer(services=services)

        permissions = self._make_permissions(allowed_targets="children")
        tool_call = self._make_tool_call("any-agent")

        result = enforcer._check_target_allowed(tool_call, permissions)
        assert result is not None
        assert result.error is not None
        assert "can only target child agents" in result.error

    def test_children_denied_when_no_services(self):
        """Target denied when services is None (no child tracking)."""
        enforcer = PermissionEnforcer(services=None)

        permissions = self._make_permissions(allowed_targets="children")
        tool_call = self._make_tool_call("any-agent")

        result = enforcer._check_target_allowed(tool_call, permissions)
        assert result is not None
        assert result.error is not None
        assert "can only target child agents" in result.error


class TestCheckTargetAllowedFamily:
    """Tests for _check_target_allowed with allowed_targets='family'."""

    def _make_permissions(
        self,
        parent_agent_id: str | None = None,
        allowed_targets: str | list[str] | None = None,
    ) -> AgentPermissions:
        """Create AgentPermissions with target restriction."""
        tool_permissions = {}
        if allowed_targets is not None:
            tool_permissions["nexus_send"] = ToolPermission(
                enabled=True, allowed_targets=allowed_targets
            )
        return AgentPermissions(
            base_preset="trusted",
            effective_policy=PermissionPolicy(
                level=PermissionLevel.TRUSTED,
                allowed_paths=None,
                blocked_paths=[],
                cwd=Path("/project"),
            ),
            tool_permissions=tool_permissions,
            parent_agent_id=parent_agent_id,
        )

    def _make_tool_call(self, target_agent_id: str) -> ToolCall:
        """Create a nexus_send tool call."""
        return ToolCall(
            id="call-1",
            name="nexus_send",
            arguments={"agent_id": target_agent_id, "content": "Hello"},
        )

    def test_family_allows_parent(self):
        """Family restriction allows targeting parent."""
        services = MagicMock()
        services.get_child_agent_ids.return_value = set()
        enforcer = PermissionEnforcer(services=services)

        permissions = self._make_permissions(
            parent_agent_id="parent-agent",
            allowed_targets="family",
        )
        tool_call = self._make_tool_call("parent-agent")

        result = enforcer._check_target_allowed(tool_call, permissions)
        assert result is None  # No error = allowed

    def test_family_allows_child(self):
        """Family restriction allows targeting children."""
        services = MagicMock()
        services.get_child_agent_ids.return_value = {"child-1", "child-2"}
        enforcer = PermissionEnforcer(services=services)

        permissions = self._make_permissions(
            parent_agent_id="parent-agent",
            allowed_targets="family",
        )
        tool_call = self._make_tool_call("child-1")

        result = enforcer._check_target_allowed(tool_call, permissions)
        assert result is None  # No error = allowed

    def test_family_denied_when_target_is_sibling(self):
        """Family restriction denies targeting siblings (not parent/child)."""
        services = MagicMock()
        services.get_child_agent_ids.return_value = {"child-1"}
        enforcer = PermissionEnforcer(services=services)

        permissions = self._make_permissions(
            parent_agent_id="parent-agent",
            allowed_targets="family",
        )
        tool_call = self._make_tool_call("sibling-agent")

        result = enforcer._check_target_allowed(tool_call, permissions)
        assert result is not None
        assert result.error is not None
        assert "can only target parent or child agents" in result.error


class TestCheckTargetAllowedExplicitList:
    """Tests for _check_target_allowed with explicit allowlist."""

    def _make_permissions(
        self,
        allowed_targets: str | list[str] | None = None,
    ) -> AgentPermissions:
        """Create AgentPermissions with target restriction."""
        tool_permissions = {}
        if allowed_targets is not None:
            tool_permissions["nexus_send"] = ToolPermission(
                enabled=True, allowed_targets=allowed_targets
            )
        return AgentPermissions(
            base_preset="trusted",
            effective_policy=PermissionPolicy(
                level=PermissionLevel.TRUSTED,
                allowed_paths=None,
                blocked_paths=[],
                cwd=Path("/project"),
            ),
            tool_permissions=tool_permissions,
        )

    def _make_tool_call(self, target_agent_id: str) -> ToolCall:
        """Create a nexus_send tool call."""
        return ToolCall(
            id="call-1",
            name="nexus_send",
            arguments={"agent_id": target_agent_id, "content": "Hello"},
        )

    def test_explicit_list_allows_listed_agent(self):
        """Target allowed when in explicit allowlist."""
        enforcer = PermissionEnforcer()
        permissions = self._make_permissions(
            allowed_targets=["coordinator", "logger", "worker-1"]
        )
        tool_call = self._make_tool_call("coordinator")

        result = enforcer._check_target_allowed(tool_call, permissions)
        assert result is None  # No error = allowed

    def test_explicit_list_denies_unlisted_agent(self):
        """Target denied when not in explicit allowlist."""
        enforcer = PermissionEnforcer()
        permissions = self._make_permissions(
            allowed_targets=["coordinator", "logger"]
        )
        tool_call = self._make_tool_call("hacker-agent")

        result = enforcer._check_target_allowed(tool_call, permissions)
        assert result is not None
        assert result.error is not None
        assert "cannot target agent 'hacker-agent'" in result.error


class TestCheckTargetAllowedNoRestriction:
    """Tests for _check_target_allowed with no restriction."""

    def _make_permissions(
        self,
        allowed_targets: str | list[str] | None = None,
    ) -> AgentPermissions:
        """Create AgentPermissions with optional target restriction."""
        tool_permissions = {}
        if allowed_targets is not None:
            tool_permissions["nexus_send"] = ToolPermission(
                enabled=True, allowed_targets=allowed_targets
            )
        return AgentPermissions(
            base_preset="trusted",
            effective_policy=PermissionPolicy(
                level=PermissionLevel.TRUSTED,
                allowed_paths=None,
                blocked_paths=[],
                cwd=Path("/project"),
            ),
            tool_permissions=tool_permissions,
        )

    def _make_tool_call(self, target_agent_id: str) -> ToolCall:
        """Create a nexus_send tool call."""
        return ToolCall(
            id="call-1",
            name="nexus_send",
            arguments={"agent_id": target_agent_id, "content": "Hello"},
        )

    def test_no_restriction_allows_any_target(self):
        """No restriction (allowed_targets=None) allows any target."""
        enforcer = PermissionEnforcer()
        permissions = self._make_permissions(allowed_targets=None)
        tool_call = self._make_tool_call("any-agent-at-all")

        result = enforcer._check_target_allowed(tool_call, permissions)
        assert result is None  # No error = allowed

    def test_no_tool_permission_allows_any_target(self):
        """No ToolPermission for tool allows any target."""
        enforcer = PermissionEnforcer()
        # Permissions with no nexus_send in tool_permissions
        permissions = AgentPermissions(
            base_preset="yolo",
            effective_policy=PermissionPolicy(
                level=PermissionLevel.YOLO,
                allowed_paths=None,
                blocked_paths=[],
                cwd=Path("/"),
            ),
            tool_permissions={},  # Empty - no restrictions
        )
        tool_call = self._make_tool_call("any-agent")

        result = enforcer._check_target_allowed(tool_call, permissions)
        assert result is None  # No error = allowed


class TestCheckTargetAllowedEdgeCases:
    """Edge case tests for _check_target_allowed."""

    def _make_permissions(
        self,
        parent_agent_id: str | None = None,
        allowed_targets: str | list[str] | None = None,
        tool_name: str = "nexus_send",
    ) -> AgentPermissions:
        """Create AgentPermissions with target restriction."""
        tool_permissions = {}
        if allowed_targets is not None:
            tool_permissions[tool_name] = ToolPermission(
                enabled=True, allowed_targets=allowed_targets
            )
        return AgentPermissions(
            base_preset="sandboxed",
            effective_policy=PermissionPolicy(
                level=PermissionLevel.SANDBOXED,
                allowed_paths=[Path("/sandbox")],
                blocked_paths=[],
                cwd=Path("/sandbox"),
            ),
            tool_permissions=tool_permissions,
            parent_agent_id=parent_agent_id,
        )

    def test_non_target_tool_bypasses_check(self):
        """Tools not in AGENT_TARGET_TOOLS bypass target check."""
        enforcer = PermissionEnforcer()
        permissions = self._make_permissions(allowed_targets="parent")

        # read_file is not in AGENT_TARGET_TOOLS
        tool_call = ToolCall(
            id="call-1",
            name="read_file",
            arguments={"path": "/file.txt"},
        )

        result = enforcer._check_target_allowed(tool_call, permissions)
        assert result is None  # No error - bypassed

    def test_empty_agent_id_bypasses_check(self):
        """Empty agent_id bypasses check (will fail later)."""
        enforcer = PermissionEnforcer()
        permissions = self._make_permissions(
            parent_agent_id="parent",
            allowed_targets="parent",
        )

        tool_call = ToolCall(
            id="call-1",
            name="nexus_send",
            arguments={"agent_id": "", "content": "Hello"},  # Empty
        )

        result = enforcer._check_target_allowed(tool_call, permissions)
        assert result is None  # Bypassed - will fail in skill execution

    def test_missing_agent_id_bypasses_check(self):
        """Missing agent_id bypasses check (will fail later)."""
        enforcer = PermissionEnforcer()
        permissions = self._make_permissions(
            parent_agent_id="parent",
            allowed_targets="parent",
        )

        tool_call = ToolCall(
            id="call-1",
            name="nexus_send",
            arguments={"content": "Hello"},  # No agent_id
        )

        result = enforcer._check_target_allowed(tool_call, permissions)
        assert result is None  # Bypassed - will fail in skill execution

    def test_nexus_status_target_check(self):
        """nexus_status also undergoes target check."""
        enforcer = PermissionEnforcer()
        permissions = self._make_permissions(
            parent_agent_id="parent-agent",
            allowed_targets="parent",
            tool_name="nexus_status",
        )

        # Target matches parent - should be allowed
        tool_call = ToolCall(
            id="call-1",
            name="nexus_status",
            arguments={"agent_id": "parent-agent"},
        )
        result = enforcer._check_target_allowed(tool_call, permissions)
        assert result is None

        # Target does not match parent - should be denied
        tool_call_bad = ToolCall(
            id="call-2",
            name="nexus_status",
            arguments={"agent_id": "other-agent"},
        )
        result_bad = enforcer._check_target_allowed(tool_call_bad, permissions)
        assert result_bad is not None
        assert "can only target parent agent" in result_bad.error

    def test_unknown_allowed_targets_shape_is_fail_open_via_kernel_path(self):
        """Malformed allowed_targets still allow, but only after kernel authorization."""
        services = MagicMock()
        services.get.return_value = "agent-1"
        services.get_child_agent_ids.return_value = {"child-1"}
        enforcer = PermissionEnforcer(services=services)
        permissions = self._make_permissions()
        permissions.tool_permissions["nexus_send"] = ToolPermission(
            enabled=True,
            allowed_targets={"unexpected": True},  # type: ignore[arg-type]
        )
        tool_call = ToolCall(
            id="call-1",
            name="nexus_send",
            arguments={"agent_id": "random-agent", "content": "Hello"},
        )

        captured_requests = []
        original_authorize = enforcer._target_authorization_kernel.authorize

        def capture_and_delegate(request):
            captured_requests.append(request)
            return original_authorize(request)

        enforcer._target_authorization_kernel.authorize = capture_and_delegate  # type: ignore[method-assign]

        result = enforcer._check_target_allowed(tool_call, permissions)

        assert result is None
        assert len(captured_requests) == 1
        assert captured_requests[0].context["allowed_targets_mode"] == "unknown"


class TestCheckAllWithTargetValidation:
    """Test that check_all integrates target validation."""

    def test_check_all_calls_target_check(self):
        """check_all includes target validation in its checks.

        Note: We use TRUSTED level because SANDBOXED blocks nexus_send
        at the policy level (SANDBOXED_DISABLED_TOOLS), which would fail
        before reaching target validation. In real usage, the sandboxed
        preset enables nexus_send via tool_permissions while the policy
        blocks it, but we're testing the enforcer's check_all flow.
        """
        enforcer = PermissionEnforcer()

        # Use TRUSTED level so nexus_send is allowed by policy,
        # then target restriction kicks in
        permissions = AgentPermissions(
            base_preset="trusted",
            effective_policy=PermissionPolicy(
                level=PermissionLevel.TRUSTED,
                allowed_paths=None,
                blocked_paths=[],
                cwd=Path("/project"),
            ),
            tool_permissions={
                "nexus_send": ToolPermission(enabled=True, allowed_targets="parent"),
            },
            parent_agent_id="parent-agent",
        )

        # Targeting parent - should pass all checks
        tool_call_good = ToolCall(
            id="call-1",
            name="nexus_send",
            arguments={"agent_id": "parent-agent", "content": "Hello"},
        )
        result = enforcer.check_all(tool_call_good, permissions)
        assert result is None

        # Targeting non-parent - should fail target check
        tool_call_bad = ToolCall(
            id="call-2",
            name="nexus_send",
            arguments={"agent_id": "other-agent", "content": "Hello"},
        )
        result_bad = enforcer.check_all(tool_call_bad, permissions)
        assert result_bad is not None
        assert "can only target parent agent" in result_bad.error


class TestTargetAuthorizationKernelEnforcement:
    """Tests for kernel-authoritative target authorization behavior."""

    def _make_permissions(self) -> AgentPermissions:
        return AgentPermissions(
            base_preset="trusted",
            effective_policy=PermissionPolicy(
                level=PermissionLevel.TRUSTED,
                allowed_paths=None,
                blocked_paths=[],
                cwd=Path("/project"),
            ),
            tool_permissions={
                "nexus_send": ToolPermission(enabled=True, allowed_targets="parent"),
            },
            parent_agent_id="parent-agent",
        )

    def _make_tool_call(self, target_agent_id: str) -> ToolCall:
        return ToolCall(
            id="call-1",
            name="nexus_send",
            arguments={"agent_id": target_agent_id, "content": "hello"},
        )

    def test_adapter_path_allows_parent_target(self) -> None:
        services = MagicMock()
        services.get.return_value = "agent-1"
        services.get_child_agent_ids.return_value = set()
        enforcer = PermissionEnforcer(services=services)
        permissions = self._make_permissions()
        tool_call = self._make_tool_call("parent-agent")

        result = enforcer._check_target_allowed(tool_call, permissions)

        assert result is None

    def test_forced_kernel_deny_is_authoritative_with_stable_wording(self) -> None:
        services = MagicMock()
        services.get.return_value = "agent-1"
        services.get_child_agent_ids.return_value = set()
        enforcer = PermissionEnforcer(services=services)
        permissions = self._make_permissions()
        tool_call = self._make_tool_call("parent-agent")

        def deny_request(request):
            return AuthorizationDecision.deny(request, reason="forced_deny")

        enforcer._target_authorization_kernel.authorize = deny_request  # type: ignore[method-assign]

        result = enforcer._check_target_allowed(tool_call, permissions)

        assert result is not None
        assert result.error == "Tool 'nexus_send' can only target parent agent ('parent-agent')"


class TestActionAuthorizationKernelEnforcement:
    """Tests for kernel-authoritative tool action authorization behavior."""

    def _make_permissions(self) -> AgentPermissions:
        return AgentPermissions(
            base_preset="sandboxed",
            effective_policy=PermissionPolicy(
                level=PermissionLevel.SANDBOXED,
                allowed_paths=[Path("/sandbox")],
                blocked_paths=[],
                cwd=Path("/sandbox"),
            ),
            tool_permissions={},
        )

    def test_adapter_path_preserves_legacy_deny_wording(self) -> None:
        enforcer = PermissionEnforcer()
        permissions = self._make_permissions()
        result = enforcer._check_action_allowed("nexus_send", permissions)

        assert result is not None
        assert result.error == "Tool 'nexus_send' is not allowed at current permission level"

    def test_forced_kernel_deny_is_authoritative_with_stable_wording(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        services = MagicMock()
        services.get.return_value = "agent-1"
        enforcer = PermissionEnforcer(services=services)
        permissions = self._make_permissions()
        permissions.tool_permissions["nexus_send"] = ToolPermission(enabled=True)

        def deny_request(request):
            return AuthorizationDecision.deny(request, reason="forced_deny")

        enforcer._action_authorization_kernel.authorize = deny_request  # type: ignore[method-assign]

        with caplog.at_level("WARNING", logger="nexus3.session.enforcer"):
            result = enforcer._check_action_allowed("nexus_send", permissions)

        assert result is not None
        assert result.error == "Tool 'nexus_send' is not allowed at current permission level"
        assert not any(
            "Tool action authorization shadow mismatch" in r.message
            for r in caplog.records
        )

    def test_adapter_path_allows_explicitly_enabled_tool(self) -> None:
        enforcer = PermissionEnforcer()
        permissions = self._make_permissions()
        permissions.tool_permissions["nexus_send"] = ToolPermission(enabled=True)

        result = enforcer._check_action_allowed("nexus_send", permissions)

        assert result is None


class TestEnabledAuthorizationKernelEnforcement:
    """Tests for kernel-authoritative tool enabled/disabled behavior."""

    def _make_permissions(self) -> AgentPermissions:
        return AgentPermissions(
            base_preset="sandboxed",
            effective_policy=PermissionPolicy(
                level=PermissionLevel.SANDBOXED,
                allowed_paths=[Path("/sandbox")],
                blocked_paths=[],
                cwd=Path("/sandbox"),
            ),
            tool_permissions={},
        )

    def test_adapter_path_preserves_legacy_deny_wording(self) -> None:
        enforcer = PermissionEnforcer()
        permissions = self._make_permissions()
        permissions.tool_permissions["nexus_send"] = ToolPermission(enabled=False)

        result = enforcer._check_enabled("nexus_send", permissions)

        assert result is not None
        assert result.error == "Tool 'nexus_send' is disabled by permission policy"

    def test_forced_kernel_deny_is_authoritative_with_stable_wording(self) -> None:
        enforcer = PermissionEnforcer()
        permissions = self._make_permissions()
        permissions.tool_permissions["nexus_send"] = ToolPermission(enabled=True)

        def deny_request(request):
            return AuthorizationDecision.deny(request, reason="forced_deny")

        enforcer._enabled_authorization_kernel.authorize = deny_request  # type: ignore[method-assign]

        result = enforcer._check_enabled("nexus_send", permissions)

        assert result is not None
        assert result.error == "Tool 'nexus_send' is disabled by permission policy"


class TestCheckAllOrderingWithEnabledChecks:
    """Tests for check_all ordering between enabled and action checks."""

    def test_disabled_message_precedes_action_denial(self) -> None:
        enforcer = PermissionEnforcer()
        permissions = AgentPermissions(
            base_preset="sandboxed",
            effective_policy=PermissionPolicy(
                level=PermissionLevel.SANDBOXED,
                allowed_paths=[Path("/sandbox")],
                blocked_paths=[],
                cwd=Path("/sandbox"),
            ),
            tool_permissions={"nexus_send": ToolPermission(enabled=False)},
        )
        tool_call = ToolCall(
            id="call-1",
            name="nexus_send",
            arguments={"agent_id": "agent-2", "content": "hello"},
        )

        def fail_if_called(_request):
            pytest.fail("action authorization should not run after enabled-check deny")

        enforcer._action_authorization_kernel.authorize = fail_if_called  # type: ignore[method-assign]

        result = enforcer.check_all(tool_call, permissions)

        assert result is not None
        assert result.error == "Tool 'nexus_send' is disabled by permission policy"
