"""Single-tool execution runtime helpers extracted from Session."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from nexus3.core.authorization_kernel import AdapterAuthorizationKernel
from nexus3.core.permissions import AgentPermissions, ConfirmationResult
from nexus3.core.types import ToolCall, ToolResult
from nexus3.core.validation import ValidationError, validate_tool_arguments
from nexus3.session.confirmation import ConfirmationController
from nexus3.session.permission_runtime import (
    handle_gitlab_permissions as handle_gitlab_permissions_runtime,
)
from nexus3.session.permission_runtime import (
    handle_mcp_permissions as handle_mcp_permissions_runtime,
)
from nexus3.session.tool_runtime import execute_skill as execute_skill_runtime

if TYPE_CHECKING:
    from nexus3.skill.base import Skill
    from nexus3.skill.services import ServiceContainer


ConfirmationCallback = Callable[[ToolCall, Path | None, Path], Awaitable[ConfirmationResult]]


class _PermissionEnforcer(Protocol):
    def check_all(
        self,
        tool_call: ToolCall,
        permissions: AgentPermissions,
    ) -> ToolResult | None: ...

    def requires_confirmation(
        self,
        tool_call: ToolCall,
        permissions: AgentPermissions,
    ) -> bool: ...

    def get_confirmation_context(
        self,
        tool_call: ToolCall,
    ) -> tuple[Path | None, list[Path]]: ...

    def extract_exec_cwd(self, tool_call: ToolCall) -> Path | None: ...

    def extract_exec_allowance_key(self, tool_call: ToolCall) -> str | None: ...

    def get_effective_timeout(
        self,
        tool_name: str,
        permissions: AgentPermissions | None,
        default_timeout: float,
    ) -> float: ...


class _ToolDispatcher(Protocol):
    def find_skill(self, tool_call: ToolCall) -> tuple[Skill | None, str | None]: ...


async def execute_single_tool(
    tool_call: ToolCall,
    *,
    services: ServiceContainer | None,
    enforcer: _PermissionEnforcer,
    confirmation: ConfirmationController,
    dispatcher: _ToolDispatcher,
    on_confirm: ConfirmationCallback | None,
    mcp_authorization_kernel: AdapterAuthorizationKernel,
    gitlab_authorization_kernel: AdapterAuthorizationKernel,
    skill_timeout: float,
    runtime_logger: logging.Logger,
) -> ToolResult:
    """Execute a single tool call with Session-equivalent behavior."""
    permissions = services.get_permissions() if services else None

    # Fail-closed: require permissions for tool execution (H3 fix)
    if permissions is None:
        return ToolResult(
            error="Tool execution denied: permissions not configured. "
            "This is a programming error - all Sessions should have permissions."
        )

    # 1. Resolve skill
    skill, mcp_server_name = dispatcher.find_skill(tool_call)

    # 2. Unknown skill check
    if not skill:
        runtime_logger.debug("Unknown skill requested: %s", tool_call.name)
        return ToolResult(error=f"Unknown skill: {tool_call.name}")

    # 3. Check for malformed/truncated/unresolved tool-call arguments
    raw = tool_call.raw_arguments
    if tool_call.has_unresolved_arguments and raw is not None:
        preview = raw[:200] + "..." if len(raw) > 200 else raw
        source = f" ({tool_call.source_format})" if tool_call.source_format else ""
        detail = tool_call.normalization_error or "Unable to normalize tool arguments"
        return ToolResult(
            error=(
                f"Tool call for {tool_call.name}{source} had unresolved arguments. "
                f"{detail}. Raw text: {preview}\n"
                f"Please retry the tool call with valid, complete object-shaped arguments."
            )
        )

    # 4. Permission checks (enabled, action allowed, path restrictions)
    error = enforcer.check_all(tool_call, permissions)
    if error:
        return error

    # 5. Check if confirmation needed
    if enforcer.requires_confirmation(tool_call, permissions):
        # Fix 1.2: Get display path and ALL write paths for multi-path tools
        display_path, write_paths = enforcer.get_confirmation_context(tool_call)
        exec_cwd = enforcer.extract_exec_cwd(tool_call)
        exec_allowance_key = enforcer.extract_exec_allowance_key(tool_call)
        agent_cwd = services.get_cwd() if services else Path.cwd()

        # Show confirmation for the write target (display_path)
        result = await confirmation.request(tool_call, display_path, agent_cwd, on_confirm)

        if result == ConfirmationResult.DENY:
            return ToolResult(error="Action cancelled by user")

        # Fix 1.2: Apply allowance to ALL write paths (e.g., destination for copy_file)
        if permissions and write_paths:
            for write_path in write_paths:
                confirmation.apply_result(
                    permissions,
                    result,
                    tool_call,
                    write_path,
                    exec_cwd,
                    exec_allowance_key,
                )
        elif permissions:
            # Fallback for tools without explicit write paths (e.g., exec tools)
            confirmation.apply_result(
                permissions,
                result,
                tool_call,
                display_path,
                exec_cwd,
                exec_allowance_key,
            )

    # 6. MCP permission check and confirmation (if MCP skill)
    if mcp_server_name and permissions:
        error = await handle_mcp_permissions_runtime(
            tool_call=tool_call,
            skill=skill,
            server_name=mcp_server_name,
            permissions=permissions,
            authorization_kernel=mcp_authorization_kernel,
            confirmation=confirmation,
            services=services,
            on_confirm=on_confirm,
        )
        if error:
            return error

    # 6b. GitLab permission check and confirmation (if GitLab skill)
    if tool_call.name.startswith("gitlab_") and permissions:
        error = await handle_gitlab_permissions_runtime(
            tool_call=tool_call,
            skill=skill,
            permissions=permissions,
            authorization_kernel=gitlab_authorization_kernel,
            confirmation=confirmation,
            services=services,
            on_confirm=on_confirm,
        )
        if error:
            return error

    # 7. Validate arguments
    try:
        args = validate_tool_arguments(
            tool_call.arguments,
            skill.parameters,
        )
    except ValidationError as e:
        return ToolResult(error=f"Invalid arguments for {tool_call.name}: {e.message}")

    # 7. Execute with timeout
    effective_timeout = enforcer.get_effective_timeout(tool_call.name, permissions, skill_timeout)

    return await execute_skill_runtime(
        skill=skill,
        args=args,
        timeout=effective_timeout,
        runtime_logger=runtime_logger,
    )
