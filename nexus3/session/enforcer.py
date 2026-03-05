"""Permission enforcement for tool execution.

Arch A2 Integration: Uses PathResolver/PathDecisionEngine for consistent
path validation across all permission checks.

Fix 1.2: Multi-path confirmation using ToolPathSemantics for proper
handling of copy_file/rename destination paths.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from nexus3.core.authorization_kernel import (
    AdapterAuthorizationKernel,
    AuthorizationAction,
    AuthorizationDecision,
    AuthorizationRequest,
    AuthorizationResource,
    AuthorizationResourceType,
)
from nexus3.core.path_decision import PathDecisionEngine
from nexus3.core.presets import ToolPermission  # noqa: F401 - needed for P2
from nexus3.core.types import ToolResult
from nexus3.session.path_semantics import (
    extract_display_path,
    extract_write_paths,
)

if TYPE_CHECKING:
    from nexus3.core.permissions import AgentPermissions
    from nexus3.core.types import ToolCall
    from nexus3.skill.services import ServiceContainer


# Tools that have execution cwd parameter
EXEC_TOOLS = frozenset({"bash", "bash_safe", "shell_UNSAFE", "run_python", "git"})

# Tools that take agent_id as a target (for allowed_targets enforcement)
AGENT_TARGET_TOOLS = frozenset({
    "nexus_send", "nexus_status", "nexus_cancel", "nexus_destroy"
})

# Tools that operate on paths
PATH_TOOLS = frozenset({
    "read_file", "write_file", "edit_file", "append_file", "tail",
    "file_info", "list_directory", "mkdir", "copy_file", "rename",
    "regex_replace", "glob", "grep",
})

logger = logging.getLogger(__name__)


class _AgentTargetAuthorizationAdapter:
    """Kernel adapter mirroring legacy target-restriction checks."""

    def authorize(self, request: AuthorizationRequest) -> AuthorizationDecision | None:
        if request.action != AuthorizationAction.AGENT_TARGET:
            return None
        if request.resource.resource_type != AuthorizationResourceType.AGENT:
            return None

        mode = request.context.get("allowed_targets_mode")
        target_agent_id = request.resource.identifier
        caller_parent_agent_id = request.context.get("caller_parent_agent_id")
        target_in_child_set = bool(request.context.get("target_in_child_set", False))
        target_in_explicit_allowlist = bool(
            request.context.get("target_in_explicit_allowlist", False)
        )

        if mode == "parent":
            if (
                isinstance(caller_parent_agent_id, str)
                and caller_parent_agent_id
                and target_agent_id == caller_parent_agent_id
            ):
                return AuthorizationDecision.allow(request, reason="parent_allowed")
            return AuthorizationDecision.deny(request, reason="not_parent")

        if mode == "children":
            if target_in_child_set:
                return AuthorizationDecision.allow(request, reason="child_allowed")
            return AuthorizationDecision.deny(request, reason="not_child")

        if mode == "family":
            if (
                isinstance(caller_parent_agent_id, str)
                and caller_parent_agent_id
                and target_agent_id == caller_parent_agent_id
            ):
                return AuthorizationDecision.allow(request, reason="parent_allowed")
            if target_in_child_set:
                return AuthorizationDecision.allow(request, reason="child_allowed")
            return AuthorizationDecision.deny(request, reason="not_family")

        if mode == "explicit":
            if target_in_explicit_allowlist:
                return AuthorizationDecision.allow(request, reason="explicit_allowed")
            return AuthorizationDecision.deny(request, reason="not_in_allowlist")

        return AuthorizationDecision.allow(request, reason="unknown_mode_fail_open")


class _ToolActionAuthorizationAdapter:
    """Kernel adapter mirroring legacy tool action-allowance checks."""

    def authorize(self, request: AuthorizationRequest) -> AuthorizationDecision | None:
        if request.action != AuthorizationAction.TOOL_EXECUTE:
            return None
        if request.resource.resource_type != AuthorizationResourceType.TOOL:
            return None

        if bool(request.context.get("tool_explicitly_enabled", False)):
            return AuthorizationDecision.allow(request, reason="explicit_enabled")

        if bool(request.context.get("policy_allows_action", False)):
            return AuthorizationDecision.allow(request, reason="policy_allowed")

        return AuthorizationDecision.deny(request, reason="policy_denied")


class PermissionEnforcer:
    """Enforces permission policies for tool execution.

    Centralizes all permission-related checks:
    - Tool enabled/disabled
    - Action allowed by policy
    - Path restrictions (sandbox, per-tool)
    - Timeout overrides
    """

    def __init__(self, services: ServiceContainer | None = None) -> None:
        self._services = services
        self._action_authorization_kernel = AdapterAuthorizationKernel(
            adapters=(_ToolActionAuthorizationAdapter(),),
            default_allow=False,
        )
        self._target_authorization_kernel = AdapterAuthorizationKernel(
            adapters=(_AgentTargetAuthorizationAdapter(),),
            default_allow=False,
        )

    def check_all(
        self,
        tool_call: ToolCall,
        permissions: AgentPermissions,
    ) -> ToolResult | None:
        """Run all permission checks.

        Arch A2: Checks ALL paths in tool call (e.g., both source and
        destination for copy_file), not just the first one.

        Args:
            tool_call: The tool call to check.
            permissions: Agent permissions (required, non-optional).

        Returns:
            ToolResult with error if any check fails, None if all pass.
        """
        # Check tool enabled
        error = self._check_enabled(tool_call.name, permissions)
        if error:
            return error

        # Check action allowed
        error = self._check_action_allowed(tool_call.name, permissions)
        if error:
            return error

        # Check target agent allowed (for nexus_* tools)
        error = self._check_target_allowed(tool_call, permissions)
        if error:
            return error

        # Check path restrictions for ALL paths in tool call
        for target_path in self.extract_target_paths(tool_call):
            error = self._check_path_allowed(tool_call.name, target_path, permissions)
            if error:
                return error

        return None

    def _check_enabled(
        self,
        tool_name: str,
        permissions: AgentPermissions,
    ) -> ToolResult | None:
        """Check if tool is enabled."""
        tool_perm = permissions.tool_permissions.get(tool_name)
        if tool_perm and not tool_perm.enabled:
            return ToolResult(error=f"Tool '{tool_name}' is disabled by permission policy")
        return None

    def _check_action_allowed(
        self,
        tool_name: str,
        permissions: AgentPermissions,
    ) -> ToolResult | None:
        """Check if action is allowed by policy level.

        Tool permissions can override policy-level restrictions:
        If a tool is explicitly enabled in tool_permissions (enabled=True),
        it bypasses SANDBOXED_DISABLED_TOOLS. This allows the sandboxed preset
        to enable nexus_send with restrictions (allowed_targets="parent").
        """
        tool_perm = permissions.tool_permissions.get(tool_name)
        tool_explicitly_enabled = bool(tool_perm is not None and tool_perm.enabled)
        policy_allows_action = bool(permissions.effective_policy.allows_action(tool_name))

        if tool_explicitly_enabled:
            legacy_allowed = True
            legacy_reason = "explicit_enabled"
        elif policy_allows_action:
            legacy_allowed = True
            legacy_reason = "policy_allowed"
        else:
            legacy_allowed = False
            legacy_reason = "policy_denied"
        legacy_error = (
            f"Tool '{tool_name}' is not allowed at current permission level"
        )

        requester_id = self._services.get("agent_id") if self._services else None
        principal_id = requester_id if isinstance(requester_id, str) and requester_id else "unknown"

        kernel_request = AuthorizationRequest(
            action=AuthorizationAction.TOOL_EXECUTE,
            resource=AuthorizationResource(
                resource_type=AuthorizationResourceType.TOOL,
                identifier=tool_name,
            ),
            principal_id=principal_id,
            context={
                "tool_explicitly_enabled": tool_explicitly_enabled,
                "policy_allows_action": policy_allows_action,
            },
        )
        kernel_decision = self._action_authorization_kernel.authorize(kernel_request)
        if kernel_decision.allowed != legacy_allowed:
            logger.warning(
                "Tool action authorization shadow mismatch for tool=%s requester=%s",
                tool_name,
                principal_id,
                extra={
                    "event": "tool_action_auth_shadow_mismatch",
                    "tool_name": tool_name,
                    "requester_id": principal_id,
                    "legacy_allowed": legacy_allowed,
                    "legacy_reason": legacy_reason,
                    "kernel_allowed": kernel_decision.allowed,
                    "kernel_reason": kernel_decision.reason,
                },
            )

        if legacy_allowed:
            return None
        return ToolResult(error=legacy_error)

    def _check_target_allowed(
        self,
        tool_call: ToolCall,
        permissions: AgentPermissions,
    ) -> ToolResult | None:
        """Check if target agent is allowed by tool permission.

        For nexus_* tools, validates the agent_id argument against
        the tool's allowed_targets restriction.

        Args:
            tool_call: The tool call to check.
            permissions: Agent permissions.

        Returns:
            ToolResult with error if target not allowed, None if allowed.
        """
        if tool_call.name not in AGENT_TARGET_TOOLS:
            return None

        tool_perm = permissions.tool_permissions.get(tool_call.name)
        if not tool_perm or tool_perm.allowed_targets is None:
            return None  # No restriction

        target_agent_id = tool_call.arguments.get("agent_id", "")
        if not target_agent_id:
            return None  # Will fail later with "no agent_id provided"

        allowed = tool_perm.allowed_targets
        child_ids = self._services.get_child_agent_ids() if self._services else None

        # Handle special relationship-based restrictions
        if allowed == "parent":
            legacy_allowed = (
                permissions.parent_agent_id is not None
                and target_agent_id == permissions.parent_agent_id
            )
            legacy_reason = "parent_allowed" if legacy_allowed else "not_parent"
            legacy_error = (
                f"Tool '{tool_call.name}' can only target parent agent "
                f"('{permissions.parent_agent_id or 'none'}')"
            )

        elif allowed == "children":
            legacy_allowed = bool(child_ids and target_agent_id in child_ids)
            legacy_reason = "child_allowed" if legacy_allowed else "not_child"
            legacy_error = f"Tool '{tool_call.name}' can only target child agents"

        elif allowed == "family":
            legacy_allowed = (
                (
                    permissions.parent_agent_id is not None
                    and target_agent_id == permissions.parent_agent_id
                )
                or bool(child_ids and target_agent_id in child_ids)
            )
            legacy_reason = "family_allowed" if legacy_allowed else "not_family"
            legacy_error = f"Tool '{tool_call.name}' can only target parent or child agents"

        elif isinstance(allowed, list):
            legacy_allowed = target_agent_id in allowed
            legacy_reason = "explicit_allowed" if legacy_allowed else "not_in_allowlist"
            legacy_error = f"Tool '{tool_call.name}' cannot target agent '{target_agent_id}'"

        else:
            return None  # Unknown restriction type, allow (fail-open for forward compat)

        requester_id = self._services.get("agent_id") if self._services else None
        principal_id = requester_id if isinstance(requester_id, str) and requester_id else "unknown"
        allowed_mode = allowed if isinstance(allowed, str) else "explicit"
        kernel_request = AuthorizationRequest(
            action=AuthorizationAction.AGENT_TARGET,
            resource=AuthorizationResource(
                resource_type=AuthorizationResourceType.AGENT,
                identifier=target_agent_id,
            ),
            principal_id=principal_id,
            context={
                "allowed_targets_mode": allowed_mode,
                "caller_parent_agent_id": permissions.parent_agent_id or "",
                "target_in_child_set": bool(child_ids and target_agent_id in child_ids),
                "target_in_explicit_allowlist": bool(
                    isinstance(allowed, list) and target_agent_id in allowed
                ),
            },
        )
        kernel_decision = self._target_authorization_kernel.authorize(kernel_request)
        if kernel_decision.allowed != legacy_allowed:
            logger.warning(
                "Target authorization shadow mismatch for tool=%s target=%s",
                tool_call.name,
                target_agent_id,
                extra={
                    "event": "target_auth_shadow_mismatch",
                    "tool_name": tool_call.name,
                    "target_agent_id": target_agent_id,
                    "requester_id": principal_id,
                    "legacy_allowed": legacy_allowed,
                    "legacy_reason": legacy_reason,
                    "kernel_allowed": kernel_decision.allowed,
                    "kernel_reason": kernel_decision.reason,
                },
            )

        if legacy_allowed:
            return None
        return ToolResult(error=legacy_error)

    def _check_path_allowed(
        self,
        tool_name: str,
        target_path: Path,
        permissions: AgentPermissions,
    ) -> ToolResult | None:
        """Check path against sandbox and per-tool restrictions.

        Arch A2: Uses PathDecisionEngine for consistent path validation
        that includes blocked_paths enforcement.
        """
        # Use PathDecisionEngine for consistent path decisions
        if self._services:
            engine = PathDecisionEngine.from_services(self._services, tool_name=tool_name)
        else:
            # Fallback without services - use policy paths directly
            tool_perm = permissions.tool_permissions.get(tool_name)
            allowed = (
                tool_perm.allowed_paths
                if tool_perm and tool_perm.allowed_paths is not None
                else permissions.effective_policy.allowed_paths
            )
            blocked = permissions.effective_policy.blocked_paths
            engine = PathDecisionEngine(
                allowed_paths=allowed,
                blocked_paths=blocked,
            )

        decision = engine.check_access(str(target_path))

        if not decision.allowed:
            return ToolResult(
                error=f"Tool '{tool_name}' cannot access path"
                f" '{target_path}': {decision.reason_detail}"
            )

        return None

    def extract_target_paths(self, tool_call: ToolCall) -> list[Path]:
        """Extract ALL target paths from tool call arguments.

        Arch A2: Returns all paths that should be validated, including
        both source and destination for copy/rename operations.

        NOTE: Paths are returned WITHOUT .resolve() so that PathDecisionEngine
        can resolve them consistently against the agent's CWD (not process CWD).
        """
        args = tool_call.arguments
        paths: list[Path] = []

        # Common path parameter names - return raw Path objects
        # PathDecisionEngine.check_access() will handle resolution
        for key in ("path", "source", "destination"):
            if key in args and args[key]:
                paths.append(Path(args[key]))

        return paths

    def extract_target_path(self, tool_call: ToolCall) -> Path | None:
        """Extract first target path from tool call arguments.

        Legacy method for backwards compatibility. Prefer extract_target_paths().
        """
        paths = self.extract_target_paths(tool_call)
        return paths[0] if paths else None

    def extract_exec_cwd(self, tool_call: ToolCall) -> Path | None:
        """Extract execution cwd from tool call if applicable.

        Arch A2: Uses PathDecisionEngine for consistent cwd resolution.
        """
        if tool_call.name not in EXEC_TOOLS:
            return None

        cwd = tool_call.arguments.get("cwd")
        if cwd:
            # Use PathDecisionEngine for consistent resolution
            if self._services:
                engine = PathDecisionEngine.from_services(self._services, tool_name=tool_call.name)
            else:
                engine = PathDecisionEngine(cwd=Path.cwd())

            decision = engine.check_cwd(cwd, tool_name=tool_call.name)
            if decision.allowed and decision.resolved_path:
                return decision.resolved_path

        return None

    def requires_confirmation(
        self,
        tool_call: ToolCall,
        permissions: AgentPermissions,
    ) -> bool:
        """Check if tool call requires user confirmation.

        Fix 1.2: Checks ALL write paths, not just the first one. For multi-path
        tools like copy_file/rename, if the destination requires confirmation,
        this returns True.

        Args:
            tool_call: The tool call to check.
            permissions: Agent permissions (required, non-optional).

        Returns:
            True if confirmation is required for ANY write path, False otherwise.
        """
        # Special case: nexus_destroy on child agents doesn't need confirmation
        if self._should_skip_confirmation(tool_call):
            return False

        exec_cwd = self.extract_exec_cwd(tool_call)

        # Get write paths (what will actually be modified)
        write_paths = extract_write_paths(tool_call.name, tool_call.arguments)

        # If no write paths, fall back to old behavior (check first target path)
        if not write_paths:
            target_path = self.extract_target_path(tool_call)
            return permissions.effective_policy.requires_confirmation(
                tool_call.name,
                path=target_path,
                exec_cwd=exec_cwd,
                session_allowances=permissions.session_allowances,
            )

        # Check if ANY write path requires confirmation
        for write_path in write_paths:
            if permissions.effective_policy.requires_confirmation(
                tool_call.name,
                path=write_path,
                exec_cwd=exec_cwd,
                session_allowances=permissions.session_allowances,
            ):
                return True

        return False

    def get_confirmation_context(
        self,
        tool_call: ToolCall,
    ) -> tuple[Path | None, list[Path]]:
        """Get display path and all write paths for confirmation.

        Fix 1.2: Returns both the path to show in UI and all paths that need
        allowances applied.

        Args:
            tool_call: The tool call to get context for.

        Returns:
            Tuple of (display_path, write_paths) where:
            - display_path: Path to show in confirmation UI (typically write target)
            - write_paths: All paths that allowances should be applied to
        """
        display_path = extract_display_path(tool_call.name, tool_call.arguments)
        write_paths = extract_write_paths(tool_call.name, tool_call.arguments)
        return display_path, write_paths

    def _should_skip_confirmation(self, tool_call: ToolCall) -> bool:
        """Check if confirmation should be skipped (e.g., destroying child agents)."""
        if tool_call.name != "nexus_destroy":
            return False

        target_agent_id = tool_call.arguments.get("agent_id")
        if not target_agent_id or not self._services:
            return False

        child_ids = self._services.get_child_agent_ids()
        return child_ids is not None and target_agent_id in child_ids

    def get_effective_timeout(
        self,
        tool_name: str,
        permissions: AgentPermissions | None,
        default_timeout: float,
    ) -> float:
        """Get effective timeout for a tool (per-tool override or default)."""
        if not permissions:
            return default_timeout

        tool_perm = permissions.tool_permissions.get(tool_name)
        if tool_perm and tool_perm.timeout is not None:
            return tool_perm.timeout

        return default_timeout
