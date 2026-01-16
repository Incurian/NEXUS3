"""MCP-specific permission checks.

These functions determine whether an agent can use MCP tools and if
confirmation is required for MCP server access.

Security model:
- Only TRUSTED and YOLO agents can use MCP tools
- SANDBOXED agents cannot access external tool providers
- TRUSTED agents require consent prompt when connecting to MCP servers
- Once allowed, server can be in "allow all" mode or per-tool confirmation

P2.11 SECURITY: can_use_mcp() denies access by default when permissions is None.
This prevents MCP access for agents without explicit permission configuration.
"""

import logging

from nexus3.core.permissions import AgentPermissions, PermissionLevel

logger = logging.getLogger(__name__)


def can_use_mcp(permissions: AgentPermissions | None) -> bool:
    """Check if agent can use MCP tools.

    P2.11 SECURITY: Denies access by default when permissions is None.
    This ensures agents must have explicit permission configuration to
    use MCP tools, preventing accidental exposure.

    Args:
        permissions: Agent permissions. If None, MCP access is denied.

    Returns:
        True if MCP is allowed (YOLO/TRUSTED with explicit permissions).
        False for SANDBOXED, or if no permissions set.
    """
    if permissions is None:
        logger.debug("MCP access denied: no permissions configured (P2.11 deny-by-default)")
        return False
    level = permissions.effective_policy.level
    return level in (PermissionLevel.YOLO, PermissionLevel.TRUSTED)


def requires_mcp_confirmation(
    permissions: AgentPermissions | None,
    server_name: str,
    session_allowances: set[str],
) -> bool:
    """Check if MCP server access requires user confirmation.

    P2.11 SECURITY: Requires confirmation by default when permissions is None.
    This is defense-in-depth - if can_use_mcp() is bypassed, we still prompt.

    Args:
        permissions: Agent permissions. If None, confirmation required.
        server_name: MCP server name (e.g., 'github').
        session_allowances: Session-specific allowances (e.g., {'mcp:github'}).

    Returns:
        False if no confirmation needed:
            - YOLO level
            - Server already allowed in session_allowances
        True otherwise (prompt for 'allow all tools', or if no permissions).
    """
    if permissions is None:
        # P2.11 SECURITY: Defense-in-depth - require confirmation if no permissions
        logger.debug("MCP confirmation required: no permissions configured (P2.11 deny-by-default)")
        return True
    if permissions.effective_policy.level == PermissionLevel.YOLO:
        return False
    mcp_key = f"mcp:{server_name}"
    if mcp_key in session_allowances:
        return False
    return True
