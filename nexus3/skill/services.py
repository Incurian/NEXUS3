"""Service container for skill dependency injection.

This module provides a simple dependency injection container that skills can use
to access shared services like AgentPool, Sandbox, token counters, etc.

The container is intentionally simple - just a typed dictionary wrapper with
get/register/has methods. No automatic resolution, no scopes, no lifecycle
management. Skills request what they need by name.

Example usage:
    # At application startup:
    services = ServiceContainer()
    services.register("agent_pool", AgentPool())
    services.register("sandbox", Sandbox(working_dir))

    # In a skill factory or skill initialization:
    pool = services.get("agent_pool")
    if pool is None:
        raise RuntimeError("agent_pool service required but not registered")

    # Type-safe access with require():
    sandbox = services.require("sandbox")  # Raises if not registered
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nexus3.core.permissions import AgentPermissions, PermissionLevel
    from nexus3.rpc.agent_api import DirectAgentAPI
    from nexus3.skill.vcs.config import GitLabConfig


@dataclass
class ServiceContainer:
    """Holds shared services for skill dependency injection.

    Services like AgentPool, Sandbox, etc. can be registered here
    and injected into skills that need them.

    This is a simple container - no automatic dependency resolution,
    no scopes, no lifecycle hooks. Just register services by name
    and retrieve them later.

    Attributes:
        _services: Internal dictionary mapping service names to instances.

    Example:
        services = ServiceContainer()
        services.register("agent_pool", my_agent_pool)

        # Later, in a skill factory:
        pool = services.get("agent_pool")

        # Or with require() for mandatory services:
        pool = services.require("agent_pool")  # Raises KeyError if missing
    """

    _services: dict[str, Any] = field(default_factory=dict)

    def get(self, name: str) -> Any:
        """Get a service by name.

        Args:
            name: The service name to look up.

        Returns:
            The registered service instance, or None if not registered.
        """
        return self._services.get(name)

    def require(self, name: str) -> Any:
        """Get a service by name, raising if not registered.

        Use this when a service is mandatory and the caller cannot
        proceed without it.

        Args:
            name: The service name to look up.

        Returns:
            The registered service instance.

        Raises:
            KeyError: If the service is not registered.
        """
        if name not in self._services:
            raise KeyError(f"Required service not registered: {name}")
        return self._services[name]

    def register(self, name: str, service: Any) -> None:
        """Register a service by name.

        Overwrites any existing service with the same name.

        Args:
            name: The name to register the service under.
            service: The service instance to register.
        """
        self._services[name] = service

    def has(self, name: str) -> bool:
        """Check if a service is registered.

        Args:
            name: The service name to check.

        Returns:
            True if the service is registered, False otherwise.
        """
        return name in self._services

    def unregister(self, name: str) -> Any:
        """Unregister a service by name.

        Args:
            name: The service name to unregister.

        Returns:
            The unregistered service instance, or None if not registered.
        """
        return self._services.pop(name, None)

    def clear(self) -> None:
        """Unregister all services."""
        self._services.clear()

    def names(self) -> list[str]:
        """Get all registered service names.

        Returns:
            List of registered service names.
        """
        return list(self._services.keys())

    # =========================================================================
    # Typed accessors for common services
    # =========================================================================

    def get_permissions(self) -> "AgentPermissions | None":
        """Get the agent's permissions.

        Returns:
            AgentPermissions object if registered, None otherwise.
        """
        return self.get("permissions")

    def get_cwd(self) -> Path:
        """Get the agent's working directory.

        Returns:
            Agent's cwd if set, otherwise the process current working directory.
        """
        cwd = self.get("cwd")
        if cwd is not None:
            return Path(cwd)
        return Path.cwd()

    def get_agent_api(self) -> "DirectAgentAPI | None":
        """Get the DirectAgentAPI for in-process agent communication.

        Returns:
            DirectAgentAPI if available, None otherwise.
        """
        return self.get("agent_api")

    def get_permission_level(self) -> "PermissionLevel | None":
        """Get the agent's permission level.

        Checks for explicit 'permission_level' first, then falls back to
        extracting from 'permissions' if available.

        Returns:
            The permission level, or None if not determinable.
        """
        # Check for explicit level first
        level = self.get("permission_level")
        if level is not None:
            return level

        # Fall back to extracting from permissions
        permissions = self.get_permissions()
        if permissions is not None:
            return permissions.effective_policy.level

        return None

    def get_tool_allowed_paths(self, tool_name: str | None = None) -> list[Path] | None:
        """Get effective allowed_paths for a specific tool.

        Resolves per-tool path overrides from ToolPermission, falling back
        to the general allowed_paths from the permission policy.

        P2.4 SECURITY: This method should be called even when tool_name is None
        to ensure the general allowed_paths are still enforced.

        Resolution order:
        1. Check permissions.tool_permissions[tool_name].allowed_paths (if tool_name given)
        2. If None (or no override), use permissions.effective_policy.allowed_paths
        3. If no permissions registered, fall back to "allowed_paths" service (for tests)

        Args:
            tool_name: The tool name to get allowed paths for. If None, returns
                       general allowed_paths (not per-tool overrides).

        Returns:
            List of allowed Path objects, or None for unrestricted access.
            Empty list means deny all path access.
        """
        permissions: AgentPermissions | None = self.get("permissions")

        if permissions is None:
            # Fallback for tests that don't set up full permissions
            return self.get("allowed_paths")

        # Check for per-tool override (only if tool_name provided)
        if tool_name is not None:
            tool_perm = permissions.tool_permissions.get(tool_name)
            if tool_perm is not None and tool_perm.allowed_paths is not None:
                return tool_perm.allowed_paths

        # Fall back to general allowed_paths from policy
        return permissions.effective_policy.allowed_paths

    def get_blocked_paths(self) -> list[Path]:
        """Get blocked paths from agent's permissions.

        P2.3 SECURITY: Blocked paths are ALWAYS enforced regardless of allowed_paths.
        This provides a deny-list that takes precedence over any allow-list.

        Returns:
            List of blocked Path objects, or empty list if none configured.
        """
        permissions: AgentPermissions | None = self.get("permissions")

        if permissions is None:
            # Fallback for tests that don't set up full permissions
            blocked = self.get("blocked_paths")
            return blocked if blocked is not None else []

        return permissions.effective_policy.blocked_paths

    def get_child_agent_ids(self) -> set[str] | None:
        """Get child agent IDs if set.

        Returns:
            Set of child agent IDs, or None if not registered.
        """
        return self.get("child_agent_ids")

    def get_mcp_registry(self) -> Any | None:
        """Get MCP registry if available.

        Returns:
            MCPServerRegistry instance if registered, None otherwise.
        """
        return self.get("mcp_registry")

    def get_gitlab_config(self) -> "GitLabConfig | None":
        """Get GitLab configuration if available.

        Returns:
            GitLabConfig object if registered, None otherwise.
        """
        from nexus3.skill.vcs.config import GitLabConfig

        config = self.get("gitlab_config")
        if isinstance(config, GitLabConfig):
            return config
        return None

    def get_session_allowances(self) -> dict[str, bool]:
        """Get session allowances for per-skill confirmations.

        Session allowances track user confirmations for skill+instance combinations,
        allowing the session to remember that a user has approved access to a
        particular service (e.g., GitLab instance) for the duration of the session.

        Returns:
            Dictionary mapping allowance keys to boolean values.
            Keys are typically in format "{skill_name}@{instance_host}".
            Empty dict if no allowances have been set.
        """
        allowances = self.get("session_allowances")
        if isinstance(allowances, dict):
            return allowances
        return {}

    def set_session_allowance(self, key: str, allowed: bool) -> None:
        """Set a session allowance for a skill+instance combination.

        This allows per-skill confirmation prompts to remember user decisions
        for the duration of the session.

        Args:
            key: Allowance key, typically in format "{skill_name}@{instance_host}"
            allowed: Whether access is allowed
        """
        allowances = self.get_session_allowances()
        allowances[key] = allowed
        self.register("session_allowances", allowances)
