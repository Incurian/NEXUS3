"""MCP-specific permission checks.

These functions determine whether an agent can use MCP tools and if
confirmation is required for MCP server access.

Security model:
- Only TRUSTED and YOLO agents can use MCP tools
- SANDBOXED agents cannot access external tool providers
- TRUSTED agents require consent prompt when connecting to MCP servers
- Once allowed, server can be in "allow all" mode or per-tool confirmation
"""

from nexus3.core.permissions import AgentPermissions, PermissionLevel


def can_use_mcp(permissions: AgentPermissions | None) -> bool:
    """Check if agent can use MCP tools.

    Args:
        permissions: Agent permissions or None (unrestricted).

    Returns:
        True if MCP is allowed (YOLO/TRUSTED or no permissions).
        False for SANDBOXED (no external tools).
    """
    if permissions is None:
        return True
    level = permissions.effective_policy.level
    return level in (PermissionLevel.YOLO, PermissionLevel.TRUSTED)


def requires_mcp_confirmation(
    permissions: AgentPermissions | None,
    server_name: str,
    session_allowances: set[str],
) -> bool:
    """Check if MCP server access requires user confirmation.

    Args:
        permissions: Agent permissions or None (no confirmation).
        server_name: MCP server name (e.g., 'github').
        session_allowances: Session-specific allowances (e.g., {'mcp:github'}).

    Returns:
        False if no confirmation needed:
            - No permissions (unrestricted)
            - YOLO level
            - Server already allowed in session_allowances
        True otherwise (prompt for 'allow all tools').
    """
    if permissions is None:
        return False
    if permissions.effective_policy.level == PermissionLevel.YOLO:
        return False
    mcp_key = f"mcp:{server_name}"
    if mcp_key in session_allowances:
        return False
    return True
