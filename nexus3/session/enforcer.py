"""Permission enforcement for tool execution."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

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

        # Check path restrictions
        target_path = self.extract_target_path(tool_call)
        if target_path:
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
        """Check path against sandbox and per-tool restrictions."""
        tool_perm = permissions.tool_permissions.get(tool_name)

        # Per-tool path restrictions take precedence
        if tool_perm and tool_perm.allowed_paths is not None:
            path_allowed = False
            for allowed_path in tool_perm.allowed_paths:
                try:
                    target_path.relative_to(allowed_path)
                    path_allowed = True
                    break
                except ValueError:
                    continue
            if not path_allowed:
                return ToolResult(
                    error=f"Tool '{tool_name}' cannot access path '{target_path}' - "
                    f"restricted to: {[str(p) for p in tool_perm.allowed_paths]}"
                )
        else:
            # Fall back to policy-level sandbox check
            if not permissions.effective_policy.can_write_path(target_path):
                return ToolResult(
                    error=f"Path '{target_path}' is outside the allowed sandbox"
                )

        return None

    def extract_target_path(self, tool_call: ToolCall) -> Path | None:
        """Extract target path from tool call arguments."""
        args = tool_call.arguments

        # Common path parameter names
        for key in ("path", "source", "destination"):
            if key in args and args[key]:
                return Path(args[key]).resolve()

        return None

    def extract_exec_cwd(self, tool_call: ToolCall) -> Path | None:
        """Extract execution cwd from tool call if applicable."""
        if tool_call.name not in EXEC_TOOLS:
            return None

        cwd = tool_call.arguments.get("cwd")
        if cwd:
            base = self._services.get_cwd() if self._services else Path.cwd()
            cwd_path = Path(cwd)
            if not cwd_path.is_absolute():
                cwd_path = base / cwd_path
            return cwd_path.resolve()

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
