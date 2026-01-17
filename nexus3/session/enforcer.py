"""Permission enforcement for tool execution.

Arch A2 Integration: Uses PathResolver/PathDecisionEngine for consistent
path validation across all permission checks.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from nexus3.core.path_decision import PathDecisionEngine
from nexus3.core.types import ToolResult

if TYPE_CHECKING:
    from nexus3.core.permissions import AgentPermissions
    from nexus3.core.policy import ToolPermission
    from nexus3.core.types import ToolCall
    from nexus3.skill.services import ServiceContainer


# Tools that have execution cwd parameter
EXEC_TOOLS = frozenset({"bash", "bash_safe", "shell_UNSAFE", "run_python", "git"})

# Tools that operate on paths
PATH_TOOLS = frozenset({
    "read_file", "write_file", "edit_file", "append_file", "tail",
    "file_info", "list_directory", "mkdir", "copy_file", "rename",
    "regex_replace", "glob", "grep",
})


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

    def check_all(
        self,
        tool_call: ToolCall,
        permissions: AgentPermissions | None,
    ) -> ToolResult | None:
        """Run all permission checks.

        Arch A2: Checks ALL paths in tool call (e.g., both source and
        destination for copy_file), not just the first one.

        Returns:
            ToolResult with error if any check fails, None if all pass.
        """
        if not permissions:
            return None  # No permissions = no restrictions

        # Check tool enabled
        error = self._check_enabled(tool_call.name, permissions)
        if error:
            return error

        # Check action allowed
        error = self._check_action_allowed(tool_call.name, permissions)
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
        """Check if action is allowed by policy level."""
        if not permissions.effective_policy.allows_action(tool_name):
            return ToolResult(error=f"Tool '{tool_name}' is not allowed at current permission level")
        return None

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
            allowed = tool_perm.allowed_paths if tool_perm and tool_perm.allowed_paths is not None else permissions.effective_policy.allowed_paths
            blocked = permissions.effective_policy.blocked_paths
            engine = PathDecisionEngine(
                allowed_paths=allowed,
                blocked_paths=blocked,
            )

        decision = engine.check_access(str(target_path))

        if not decision.allowed:
            return ToolResult(
                error=f"Tool '{tool_name}' cannot access path '{target_path}': {decision.reason_detail}"
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
        permissions: AgentPermissions | None,
    ) -> bool:
        """Check if tool call requires user confirmation."""
        if not permissions:
            return False

        # Special case: nexus_destroy on child agents doesn't need confirmation
        if self._should_skip_confirmation(tool_call):
            return False

        target_path = self.extract_target_path(tool_call)
        exec_cwd = self.extract_exec_cwd(tool_call)

        return permissions.effective_policy.requires_confirmation(
            tool_call.name,
            path=target_path,
            exec_cwd=exec_cwd,
            session_allowances=permissions.session_allowances,
        )

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
