"""Permission enforcement for tool execution.

Arch A2 Integration: Uses PathResolver/PathDecisionEngine for consistent
path validation across all permission checks.

Fix 1.2: Multi-path confirmation using ToolPathSemantics for proper
handling of copy_file/rename destination paths.
"""

from __future__ import annotations

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
from nexus3.core.executable_identity import resolve_executable_identity
from nexus3.core.path_decision import PathDecisionEngine
from nexus3.core.presets import ToolPermission  # noqa: F401 - needed for P2
from nexus3.core.types import ToolResult
from nexus3.session.path_semantics import (
    extract_display_path,
    extract_tool_paths,
    extract_write_paths,
    has_explicit_semantics,
)
from nexus3.skill.builtin.concat_files import derive_concat_output_path

if TYPE_CHECKING:
    from nexus3.core.permissions import AgentPermissions
    from nexus3.core.types import ToolCall
    from nexus3.skill.services import ServiceContainer


# Tools that have execution cwd parameter
EXEC_TOOLS = frozenset({"exec", "shell_UNSAFE", "run_python", "git"})

# Tools that take agent_id as a target (for allowed_targets enforcement)
AGENT_TARGET_TOOLS = frozenset({"nexus_send", "nexus_status", "nexus_cancel", "nexus_destroy"})

# Tools that operate on paths
PATH_TOOLS = frozenset(
    {
        "read_file",
        "write_file",
        "edit_file",
        "edit_lines",
        "append_file",
        "tail",
        "file_info",
        "list_directory",
        "mkdir",
        "copy_file",
        "rename",
        "regex_replace",
        "patch",
        "glob",
        "grep",
        "copy",
        "cut",
        "paste",
        "clipboard_export",
        "clipboard_import",
        "clipboard_update",
        "concat_files",
    }
)


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


class _ToolEnabledAuthorizationAdapter:
    """Kernel adapter mirroring legacy per-tool enabled/disabled checks."""

    def authorize(self, request: AuthorizationRequest) -> AuthorizationDecision | None:
        if request.action != AuthorizationAction.TOOL_EXECUTE:
            return None
        if request.resource.resource_type != AuthorizationResourceType.TOOL:
            return None

        if bool(request.context.get("tool_explicitly_disabled", False)):
            return AuthorizationDecision.deny(request, reason="explicitly_disabled")

        return AuthorizationDecision.allow(request, reason="not_explicitly_disabled")


class _ToolPathAuthorizationAdapter:
    """Kernel adapter mirroring legacy path-access checks."""

    def authorize(self, request: AuthorizationRequest) -> AuthorizationDecision | None:
        if request.action != AuthorizationAction.TOOL_EXECUTE:
            return None
        if request.resource.resource_type != AuthorizationResourceType.PATH:
            return None

        if bool(request.context.get("path_allowed", False)):
            return AuthorizationDecision.allow(request, reason="path_allowed")
        return AuthorizationDecision.deny(request, reason="path_denied")


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
        self._enabled_authorization_kernel = AdapterAuthorizationKernel(
            adapters=(_ToolEnabledAuthorizationAdapter(),),
            default_allow=False,
        )
        self._target_authorization_kernel = AdapterAuthorizationKernel(
            adapters=(_AgentTargetAuthorizationAdapter(),),
            default_allow=False,
        )
        self._path_authorization_kernel = AdapterAuthorizationKernel(
            adapters=(_ToolPathAuthorizationAdapter(),),
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
        tool_explicitly_disabled = bool(tool_perm is not None and not tool_perm.enabled)
        legacy_error = f"Tool '{tool_name}' is disabled by permission policy"

        requester_id = self._services.get("agent_id") if self._services else None
        principal_id = requester_id if isinstance(requester_id, str) and requester_id else "unknown"
        kernel_request = AuthorizationRequest(
            action=AuthorizationAction.TOOL_EXECUTE,
            resource=AuthorizationResource(
                resource_type=AuthorizationResourceType.TOOL,
                identifier=tool_name,
            ),
            principal_id=principal_id,
            context={"tool_explicitly_disabled": tool_explicitly_disabled},
        )
        kernel_decision = self._enabled_authorization_kernel.authorize(kernel_request)
        if kernel_decision.allowed:
            return None
        return ToolResult(error=legacy_error)

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
        legacy_error = f"Tool '{tool_name}' is not allowed at current permission level"

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
        if kernel_decision.allowed:
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

        # Keep fail-open handling for malformed runtime shapes from untyped config sources.
        allowed: object = tool_perm.allowed_targets
        child_ids = self._services.get_child_agent_ids() if self._services else None

        # Handle special relationship-based restrictions
        deny_error = f"Tool '{tool_call.name}' cannot target agent '{target_agent_id}'"
        if allowed == "parent":
            deny_error = (
                f"Tool '{tool_call.name}' can only target parent agent "
                f"('{permissions.parent_agent_id or 'none'}')"
            )
            allowed_mode = "parent"

        elif allowed == "children":
            deny_error = f"Tool '{tool_call.name}' can only target child agents"
            allowed_mode = "children"

        elif allowed == "family":
            deny_error = f"Tool '{tool_call.name}' can only target parent or child agents"
            allowed_mode = "family"

        elif isinstance(allowed, list):
            allowed_mode = "explicit"
        else:
            allowed_mode = "unknown"

        requester_id = self._services.get("agent_id") if self._services else None
        principal_id = requester_id if isinstance(requester_id, str) and requester_id else "unknown"
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
        if kernel_decision.allowed:
            return None
        return ToolResult(error=deny_error)

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
        legacy_deny_error = (
            f"Tool '{tool_name}' cannot access path '{target_path}': {decision.reason_detail}"
        )
        forced_kernel_deny_error = (
            f"Tool '{tool_name}' cannot access path"
            f" '{target_path}': Access denied by permission policy"
        )

        requester_id = self._services.get("agent_id") if self._services else None
        principal_id = requester_id if isinstance(requester_id, str) and requester_id else "unknown"
        kernel_request = AuthorizationRequest(
            action=AuthorizationAction.TOOL_EXECUTE,
            resource=AuthorizationResource(
                resource_type=AuthorizationResourceType.PATH,
                identifier=str(target_path),
            ),
            principal_id=principal_id,
            context={"path_allowed": decision.allowed},
        )
        kernel_decision = self._path_authorization_kernel.authorize(kernel_request)
        if kernel_decision.allowed:
            return None

        if not decision.allowed:
            return ToolResult(error=legacy_deny_error)
        return ToolResult(error=forced_kernel_deny_error)

    def extract_target_paths(self, tool_call: ToolCall) -> list[Path]:
        """Extract ALL target paths from tool call arguments.

        Arch A2: Returns all read/write paths derived from the tool's path
        semantics so permission checks stay aligned with confirmation logic.
        """
        paths = extract_tool_paths(tool_call.name, tool_call.arguments)
        generated_output = self._extract_generated_concat_output_path(tool_call)
        if generated_output is not None and generated_output not in paths:
            paths.append(generated_output)
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
        if self._services:
            engine = PathDecisionEngine.from_services(self._services, tool_name=tool_call.name)
        else:
            engine = PathDecisionEngine(cwd=Path.cwd())

        decision = engine.check_cwd(cwd if isinstance(cwd, str) else None, tool_name=tool_call.name)
        if decision.allowed and decision.resolved_path:
            return decision.resolved_path
        return None

    def extract_exec_allowance_key(self, tool_call: ToolCall) -> str | None:
        """Extract the execution allowance identity for a tool call."""
        if tool_call.name == "run_python":
            return "run_python"

        if tool_call.name != "exec":
            return None

        program = tool_call.arguments.get("program")
        if not isinstance(program, str) or not program.strip():
            return None

        try:
            return resolve_executable_identity(
                program,
                cwd=self.extract_exec_cwd(tool_call),
            )
        except ValueError:
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
        exec_allowance_key = self.extract_exec_allowance_key(tool_call)

        # Get write paths (what will actually be modified)
        write_paths = self._extract_write_paths(tool_call)

        # Explicit read-only semantics mean there is no write target to confirm.
        if not write_paths:
            if has_explicit_semantics(tool_call.name):
                return False

            target_path = self.extract_target_path(tool_call)
            return permissions.effective_policy.requires_confirmation(
                tool_call.name,
                path=target_path,
                exec_cwd=exec_cwd,
                exec_allowance_key=exec_allowance_key,
                session_allowances=permissions.session_allowances,
            )

        # Check if ANY write path requires confirmation
        for write_path in write_paths:
            if permissions.effective_policy.requires_confirmation(
                tool_call.name,
                path=write_path,
                exec_cwd=exec_cwd,
                exec_allowance_key=exec_allowance_key,
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
        generated_output = self._extract_generated_concat_output_path(tool_call)
        display_path = generated_output or extract_display_path(tool_call.name, tool_call.arguments)
        write_paths = self._extract_write_paths(tool_call)
        return display_path, write_paths

    def _extract_write_paths(self, tool_call: ToolCall) -> list[Path]:
        """Extract write paths, including generated targets for special cases."""
        write_paths = extract_write_paths(tool_call.name, tool_call.arguments)
        generated_output = self._extract_generated_concat_output_path(tool_call)
        if generated_output is not None and generated_output not in write_paths:
            write_paths.append(generated_output)
        return write_paths

    def _extract_generated_concat_output_path(self, tool_call: ToolCall) -> Path | None:
        """Derive concat_files output path for confirmation and path checks."""
        if tool_call.name != "concat_files":
            return None

        dry_run = tool_call.arguments.get("dry_run", True)
        if not isinstance(dry_run, bool) or dry_run:
            return None

        extensions = tool_call.arguments.get("extensions")
        if not isinstance(extensions, list):
            return None
        if not extensions or any(not isinstance(ext, str) or not ext for ext in extensions):
            return None

        raw_path = tool_call.arguments.get("path", ".")
        if not isinstance(raw_path, str):
            return None

        output_format = tool_call.arguments.get("format", "plain")
        if not isinstance(output_format, str):
            output_format = "plain"

        try:
            if self._services:
                engine = PathDecisionEngine.from_services(
                    self._services,
                    tool_name=tool_call.name,
                )
                decision = engine.check_access(raw_path)
                if not decision.allowed or decision.resolved_path is None:
                    return None
                base_path = decision.resolved_path
            else:
                base_path = Path(raw_path).resolve()
        except Exception:
            return None

        return derive_concat_output_path(base_path, extensions, output_format)

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
