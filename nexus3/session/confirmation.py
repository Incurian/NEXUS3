"""User confirmation handling for tool execution."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

from nexus3.core.permissions import ConfirmationResult

if TYPE_CHECKING:
    from nexus3.core.permissions import AgentPermissions
    from nexus3.core.types import ToolCall

# Type alias for confirmation callback
ConfirmationCallback = Callable[["ToolCall", Path | None, Path], Awaitable[ConfirmationResult]]


class ConfirmationController:
    """Handles user confirmation requests and allowance updates.

    Manages the flow of:
    1. Requesting user confirmation via callback
    2. Applying confirmation results to session allowances
    """

    async def request(
        self,
        tool_call: ToolCall,
        target_path: Path | None,
        agent_cwd: Path,
        callback: ConfirmationCallback | None,
    ) -> ConfirmationResult:
        """Request user confirmation for a tool call.

        Args:
            tool_call: The tool being executed.
            target_path: Target path if applicable.
            agent_cwd: Agent's working directory.
            callback: UI callback for confirmation prompt.

        Returns:
            ConfirmationResult from user (DENY if no callback).
        """
        if callback is None:
            return ConfirmationResult.DENY

        return await callback(tool_call, target_path, agent_cwd)

    @staticmethod
    def apply_result(
        permissions: AgentPermissions,
        result: ConfirmationResult,
        tool_call: ToolCall,
        target_path: Path | None,
        exec_cwd: Path | None,
    ) -> None:
        """Apply confirmation result to session allowances.

        Updates permissions.session_allowances based on the user's choice.

        Args:
            permissions: Agent permissions to update.
            result: The user's confirmation choice.
            tool_call: The tool call that was confirmed.
            target_path: Target path if applicable.
            exec_cwd: Execution cwd if applicable.
        """
        if result == ConfirmationResult.DENY:
            return  # Nothing to update

        if result == ConfirmationResult.ALLOW_ONCE:
            return  # No persistent allowance

        if result == ConfirmationResult.ALLOW_FILE and target_path:
            permissions.add_file_allowance(target_path)

        elif result == ConfirmationResult.ALLOW_WRITE_DIRECTORY and target_path:
            permissions.add_directory_allowance(target_path.parent)

        elif result == ConfirmationResult.ALLOW_EXEC_CWD and exec_cwd:
            permissions.add_exec_cwd_allowance(tool_call.name, exec_cwd)

        elif result == ConfirmationResult.ALLOW_EXEC_GLOBAL:
            permissions.add_exec_global_allowance(tool_call.name)

    @staticmethod
    def apply_mcp_result(
        permissions: AgentPermissions,
        result: ConfirmationResult,
        tool_name: str,
        server_name: str,
    ) -> None:
        """Apply MCP-specific confirmation result.

        Args:
            permissions: Agent permissions to update.
            result: The user's confirmation choice.
            tool_name: MCP tool name.
            server_name: MCP server name.
        """
        if result == ConfirmationResult.DENY:
            return

        if result == ConfirmationResult.ALLOW_ONCE:
            return

        # ALLOW_FILE = allow this specific tool
        if result == ConfirmationResult.ALLOW_FILE:
            permissions.session_allowances.add_mcp_tool(tool_name)

        # ALLOW_EXEC_GLOBAL = allow all tools from this server
        elif result == ConfirmationResult.ALLOW_EXEC_GLOBAL:
            permissions.session_allowances.add_mcp_server(server_name)
