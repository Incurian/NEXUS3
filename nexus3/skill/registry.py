"""Skill registry with factory-based instantiation and dependency injection.

This module provides the SkillRegistry class, which manages skill factories
and creates skill instances with dependency injection via ServiceContainer.

Skills are registered as factories (callables that take a ServiceContainer
and return a Skill instance), allowing for lazy instantiation and proper
dependency injection.

Example:
    from nexus3.skill.registry import SkillRegistry
    from nexus3.skill.services import ServiceContainer

    def echo_factory(services: ServiceContainer) -> EchoSkill:
        return EchoSkill()

    registry = SkillRegistry()
    registry.register("echo", echo_factory)

    skill = registry.get("echo")
    if skill:
        result = await skill.execute(message="hello")
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from nexus3.skill.base import Skill
from nexus3.skill.services import ServiceContainer

if TYPE_CHECKING:
    from nexus3.core.permissions import AgentPermissions

# Factory type: takes ServiceContainer, returns Skill
SkillFactory = Callable[[ServiceContainer], Skill]


class SkillRegistry:
    """Registry for available skills with factory-based instantiation.

    Skills are registered as factories that receive a ServiceContainer.
    This allows skills to receive their dependencies at instantiation time.

    The registry uses lazy instantiation - skills are only created when
    first requested via get(). Instances are cached for subsequent calls.

    Attributes:
        _services: The ServiceContainer used for dependency injection.
        _factories: Dictionary mapping skill names to their factory functions.
        _instances: Cache of instantiated skill instances.

    Example:
        def echo_factory(services: ServiceContainer) -> EchoSkill:
            return EchoSkill()

        registry = SkillRegistry()
        registry.register("echo", echo_factory)

        skill = registry.get("echo")
        result = await skill.execute(message="hello")
    """

    def __init__(self, services: ServiceContainer | None = None) -> None:
        """Initialize the skill registry.

        Args:
            services: Optional ServiceContainer for dependency injection.
                     If not provided, a new empty container is created.
        """
        self._services = services or ServiceContainer()
        self._factories: dict[str, SkillFactory] = {}
        self._instances: dict[str, Skill] = {}  # Lazy cache

    def register(self, name: str, factory: SkillFactory) -> None:
        """Register a skill factory.

        The factory will be called with the ServiceContainer when the skill
        is first requested. Re-registering a skill clears any cached instance.

        Args:
            name: The name to register the skill under. This should match
                  the skill's name property.
            factory: A callable that takes a ServiceContainer and returns
                    a Skill instance.
        """
        self._factories[name] = factory
        # Clear cached instance if re-registering
        self._instances.pop(name, None)

    def get(self, name: str) -> Skill | None:
        """Get a skill instance by name (lazy instantiation).

        On first call, the skill's factory is invoked with the ServiceContainer
        to create the instance. Subsequent calls return the cached instance.

        Args:
            name: The name of the skill to retrieve.

        Returns:
            The skill instance, or None if no skill is registered with that name.
        """
        if name not in self._instances:
            factory = self._factories.get(name)
            if factory:
                self._instances[name] = factory(self._services)
        return self._instances.get(name)

    def get_definitions(self) -> list[dict[str, Any]]:
        """Get OpenAI-format tool definitions for all registered skills.

        Returns a list of tool definitions suitable for passing to an LLM API.
        Each definition includes the skill's name, description, and parameters
        schema.

        Returns:
            List of tool definitions in OpenAI function calling format.
            Each definition has the structure:
            {
                "type": "function",
                "function": {
                    "name": "skill_name",
                    "description": "skill description",
                    "parameters": {...json schema...}
                }
            }
        """
        definitions = []
        for name in self._factories:
            skill = self.get(name)
            if skill:
                definitions.append({
                    "type": "function",
                    "function": {
                        "name": skill.name,
                        "description": skill.description,
                        "parameters": skill.parameters,
                    }
                })
        return definitions

    def get_definitions_for_permissions(
        self, permissions: AgentPermissions
    ) -> list[dict[str, Any]]:
        """Get tool definitions filtered by agent permissions.

        SECURITY: This method filters out disabled tools so they are not
        exposed to the LLM. Sandboxed agents should not see tools like
        nexus_create that they cannot use.

        Args:
            permissions: The agent's permissions containing tool_permissions
                with enabled/disabled status for each tool.

        Returns:
            List of tool definitions for enabled tools only.
            Disabled tools are completely omitted from the list.
        """
        definitions = []
        for name in self._factories:
            # Check if tool is disabled in permissions
            tool_perm = permissions.tool_permissions.get(name)
            if tool_perm is not None and not tool_perm.enabled:
                # Tool is explicitly disabled - don't include definition
                continue

            skill = self.get(name)
            if skill:
                definitions.append({
                    "type": "function",
                    "function": {
                        "name": skill.name,
                        "description": skill.description,
                        "parameters": skill.parameters,
                    }
                })
        return definitions

    @property
    def names(self) -> list[str]:
        """List registered skill names.

        Returns:
            List of all registered skill names.
        """
        return list(self._factories.keys())

    @property
    def services(self) -> ServiceContainer:
        """Access the service container.

        Returns:
            The ServiceContainer used for dependency injection.
        """
        return self._services
