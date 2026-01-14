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
    from nexus3.core.permissions import AgentPermissions


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

    def get_tool_allowed_paths(self, tool_name: str) -> list[Path] | None:
        """Get effective allowed_paths for a specific tool.

        Resolves per-tool path overrides from ToolPermission, falling back
        to the general allowed_paths from the permission policy.

        Resolution order:
        1. Check permissions.tool_permissions[tool_name].allowed_paths
        2. If None (or no override), use permissions.effective_policy.allowed_paths
        3. If no permissions registered, fall back to "allowed_paths" service (for tests)

        Args:
            tool_name: The tool name to get allowed paths for.

        Returns:
            List of allowed Path objects, or None for unrestricted access.
            Empty list means deny all path access.
        """
        permissions: "AgentPermissions | None" = self.get("permissions")

        if permissions is None:
            # Fallback for tests that don't set up full permissions
            return self.get("allowed_paths")

        # Check for per-tool override
        tool_perm = permissions.tool_permissions.get(tool_name)
        if tool_perm is not None and tool_perm.allowed_paths is not None:
            return tool_perm.allowed_paths

        # Fall back to general allowed_paths from policy
        return permissions.effective_policy.allowed_paths
