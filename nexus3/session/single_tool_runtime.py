"""Single-tool execution runtime helpers extracted from Session."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

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
from nexus3.skill.argument_normalization import normalize_empty_optional_string

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


def _rewrite_tool_call(
    tool_call: ToolCall,
    *,
    name: str | None = None,
    arguments: dict[str, Any] | None = None,
    meta_updates: dict[str, Any] | None = None,
) -> ToolCall:
    """Return a copied ToolCall with updated fields when normalization changes it."""
    meta = dict(tool_call.meta)
    if meta_updates:
        meta.update(meta_updates)
    return ToolCall(
        id=tool_call.id,
        name=name or tool_call.name,
        arguments=arguments if arguments is not None else tool_call.arguments,
        meta=meta,
    )


def _mark_compat_validation_error(tool_call: ToolCall, message: str) -> ToolCall:
    """Record a compatibility-normalization error for early fail-closed handling."""
    return _rewrite_tool_call(
        tool_call,
        meta_updates={"compat_validation_error": message},
    )


def _normalize_edit_file_batch_compat_arguments(
    arguments: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Strip harmless legacy batch placeholders before schema validation.

    Historical `edit_file(edits=[...])` callers sometimes sent top-level
    single-edit placeholders such as `old_string=""`, `new_string=""`, or
    `replace_all=false`. Keep those calls working without re-exposing the
    legacy dual-mode surface in the public schema.
    """
    normalized = dict(arguments)
    changed = False

    if normalized.get("old_string") in ("", None):
        if "old_string" in normalized:
            normalized.pop("old_string")
            changed = True

    if normalized.get("new_string") in ("", None):
        if "new_string" in normalized:
            normalized.pop("new_string")
            changed = True

    if normalized.get("replace_all") is False:
        normalized.pop("replace_all")
        changed = True

    return normalized, changed


def _normalize_edit_lines_batch_compat_arguments(
    arguments: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Strip harmless legacy single-edit placeholders before batch validation."""
    normalized = dict(arguments)
    changed = False

    if normalized.get("start_line") is None and "start_line" in normalized:
        normalized.pop("start_line")
        changed = True

    if normalized.get("end_line") is None and "end_line" in normalized:
        normalized.pop("end_line")
        changed = True

    if normalized.get("new_content") in ("", None):
        if "new_content" in normalized:
            normalized.pop("new_content")
            changed = True

    return normalized, changed


def _normalize_patch_tool_call(tool_call: ToolCall) -> ToolCall:
    """Map patch aliases and source selectors onto canonical public contracts."""
    if tool_call.name not in {"patch", "patch_from_file"}:
        return tool_call

    arguments = dict(tool_call.arguments)
    meta = dict(tool_call.meta)
    changed = False
    target_alias_used = False

    path_value = normalize_empty_optional_string(arguments.get("path"))
    target_value = normalize_empty_optional_string(arguments.get("target"))

    if path_value is None and "path" in arguments:
        arguments.pop("path")
        changed = True
    elif path_value is not None:
        arguments["path"] = path_value

    if target_value is None and "target" in arguments:
        arguments.pop("target")
        changed = True
    elif target_value is not None:
        if path_value is None:
            arguments["path"] = target_value
            path_value = target_value
            target_alias_used = True
            changed = True
        elif path_value != target_value:
            return _mark_compat_validation_error(
                tool_call,
                "patch path and target must match when both are provided",
            )
        arguments.pop("target", None)
        changed = True

    diff_value = normalize_empty_optional_string(arguments.get("diff"))
    diff_file_value = normalize_empty_optional_string(arguments.get("diff_file"))

    if diff_value is None and "diff" in arguments:
        arguments.pop("diff")
        changed = True
    elif diff_value is not None:
        arguments["diff"] = diff_value

    if diff_file_value is None and "diff_file" in arguments:
        arguments.pop("diff_file")
        changed = True
    elif diff_file_value is not None:
        arguments["diff_file"] = diff_file_value

    if "diff" in arguments and "diff_file" in arguments:
        return _mark_compat_validation_error(
            tool_call,
            "Cannot provide both 'diff' and 'diff_file'. Use one or the other.",
        )

    normalized_name = tool_call.name
    if "diff_file" in arguments and tool_call.name == "patch":
        normalized_name = "patch_from_file"
        meta["compat_tool_alias_from"] = "patch"
        changed = True

    if target_alias_used:
        meta["compat_argument_alias_target"] = "path"

    if not changed:
        return tool_call

    return _rewrite_tool_call(
        tool_call,
        name=normalized_name,
        arguments=arguments,
        meta_updates=meta,
    )


def _normalize_read_file_tool_call(tool_call: ToolCall) -> ToolCall:
    """Normalize read_file alias windows onto canonical offset/limit arguments."""
    if tool_call.name != "read_file":
        return tool_call

    arguments = dict(tool_call.arguments)
    if "start_line" not in arguments and "end_line" not in arguments:
        return tool_call

    from nexus3.skill.builtin.read_file import _resolve_line_window

    for key in ("offset", "limit", "start_line", "end_line"):
        value = arguments.get(key)
        if value is not None and not isinstance(value, int):
            return _mark_compat_validation_error(
                tool_call,
                f"read_file {key} must be an integer",
            )

    try:
        effective_offset, effective_limit = _resolve_line_window(
            arguments.get("offset"),
            arguments.get("limit"),
            arguments.get("start_line"),
            arguments.get("end_line"),
        )
    except ValueError as exc:
        return _mark_compat_validation_error(tool_call, str(exc))

    arguments.pop("start_line", None)
    arguments.pop("end_line", None)
    arguments["offset"] = effective_offset
    if effective_limit is not None:
        arguments["limit"] = effective_limit

    return _rewrite_tool_call(
        tool_call,
        arguments=arguments,
        meta_updates={"compat_argument_alias_window": "offset_limit"},
    )


def _normalize_outline_tool_call(tool_call: ToolCall) -> ToolCall:
    """Normalize outline parser aliases onto the canonical parser argument."""
    if tool_call.name != "outline":
        return tool_call

    arguments = dict(tool_call.arguments)
    if "file_type" not in arguments and "language" not in arguments:
        return tool_call

    file_type = arguments.get("file_type")
    language = arguments.get("language")
    parser = arguments.get("parser", "")

    for key, value in (
        ("file_type", file_type),
        ("language", language),
        ("parser", parser),
    ):
        if value is not None and value != "" and not isinstance(value, str):
            return _mark_compat_validation_error(
                tool_call,
                f"outline {key} must be a string",
            )

    from nexus3.skill.builtin.outline import _resolve_parser_override

    resolved, error = _resolve_parser_override(
        file_type if isinstance(file_type, str) else "",
        language if isinstance(language, str) else "",
        parser if isinstance(parser, str) else "",
    )
    if error is not None:
        return _mark_compat_validation_error(tool_call, error)

    arguments.pop("file_type", None)
    arguments.pop("language", None)
    if resolved is not None:
        arguments["parser"] = resolved

    return _rewrite_tool_call(
        tool_call,
        arguments=arguments,
        meta_updates={"compat_argument_alias_parser": "parser"},
    )


def _normalize_tool_call_for_execution(tool_call: ToolCall) -> ToolCall:
    """Map legacy tool-call aliases and placeholders onto the live contract."""
    tool_call = _normalize_patch_tool_call(tool_call)
    tool_call = _normalize_read_file_tool_call(tool_call)
    tool_call = _normalize_outline_tool_call(tool_call)

    if tool_call.name in {"edit_file", "edit_file_batch"}:
        arguments = tool_call.arguments
        compat_from = tool_call.meta.get("compat_tool_alias_from")
        normalized_arguments = arguments
        meta = dict(tool_call.meta)
        changed = False

        if isinstance(arguments.get("edits"), list):
            if tool_call.name == "edit_file":
                compat_from = "edit_file"
                changed = True
            normalized_arguments, stripped_placeholders = (
                _normalize_edit_file_batch_compat_arguments(arguments)
            )
            changed = changed or stripped_placeholders

            if changed:
                if compat_from == "edit_file":
                    meta["compat_tool_alias_from"] = "edit_file"
                if stripped_placeholders:
                    meta["compat_normalized_legacy_placeholders"] = True
                return ToolCall(
                    id=tool_call.id,
                    name="edit_file_batch",
                    arguments=normalized_arguments,
                    meta=meta,
                )

    if tool_call.name in {"edit_lines", "edit_lines_batch"}:
        arguments = tool_call.arguments
        meta = dict(tool_call.meta)
        changed = False

        if isinstance(arguments.get("edits"), list):
            normalized_arguments, stripped_placeholders = (
                _normalize_edit_lines_batch_compat_arguments(arguments)
            )
            changed = stripped_placeholders or tool_call.name == "edit_lines"

            if changed:
                meta["compat_tool_alias_from"] = "edit_lines"
                if stripped_placeholders:
                    meta["compat_normalized_legacy_placeholders"] = True
                return ToolCall(
                    id=tool_call.id,
                    name="edit_lines_batch",
                    arguments=normalized_arguments,
                    meta=meta,
                )

    return tool_call


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
    tool_call = _normalize_tool_call_for_execution(tool_call)
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

    compat_validation_error = tool_call.meta.get("compat_validation_error")
    if isinstance(compat_validation_error, str) and compat_validation_error:
        return ToolResult(error=compat_validation_error)

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
