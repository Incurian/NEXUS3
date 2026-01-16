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
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from nexus3.core.identifiers import validate_tool_name
from nexus3.skill.base import Skill
from nexus3.skill.services import ServiceContainer

if TYPE_CHECKING:
    from nexus3.core.permissions import AgentPermissions

# Factory type: takes ServiceContainer, returns Skill
SkillFactory = Callable[[ServiceContainer], Skill]


@dataclass(frozen=True)
class SkillSpec:
    """Skill metadata specification - available without instantiation.

    Stores skill metadata (name, description, parameters) alongside the factory,
    enabling get_definitions() to return tool schemas without creating skill instances.

    Attributes:
        name: The skill's registered name.
        description: Human-readable description of what the skill does.
        parameters: JSON Schema for the skill's parameters.
        factory: Factory function that creates the skill instance.
    """

    name: str
    description: str
    parameters: dict[str, Any]
    factory: SkillFactory


class SkillRegistry:
    """Registry for available skills with factory-based instantiation.

    Skills are registered as SkillSpecs containing metadata and a factory.
    This allows get_definitions() to return tool schemas without instantiation.

    The registry uses lazy instantiation - skills are only created when
    first requested via get(). Instances are cached for subsequent calls.

    Attributes:
        _services: The ServiceContainer used for dependency injection.
        _specs: Dictionary mapping skill names to their SkillSpec metadata.
        _instances: Cache of instantiated skill instances.

    Example:
        def echo_factory(services: ServiceContainer) -> EchoSkill:
            return EchoSkill()

        registry = SkillRegistry()
        registry.register("echo", echo_factory, description="Echo a message", parameters={...})

        # Get definitions without instantiation:
        definitions = registry.get_definitions()

        # Instantiate on first use:
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
        self._specs: dict[str, SkillSpec] = {}
        self._instances: dict[str, Skill] = {}  # Lazy cache

    def register(
        self,
        name: str,
        factory: SkillFactory,
        *,
        description: str | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> None:
        """Register a skill factory with optional metadata.

        The factory will be called with the ServiceContainer when the skill
        is first requested. Re-registering a skill clears any cached instance.

        If description/parameters are provided, get_definitions() can return
        tool schemas without instantiating the skill. If not provided, they'll
        be fetched lazily on first access (triggering instantiation).

        Args:
            name: The name to register the skill under. This should match
                  the skill's name property.
            factory: A callable that takes a ServiceContainer and returns
                    a Skill instance.
            description: Optional skill description. If not provided, will be
                        fetched from skill instance on first access.
            parameters: Optional JSON Schema for parameters. If not provided,
                       will be fetched from skill instance on first access.

        Raises:
            ToolNameError: If the skill name is invalid (must be 1-64 chars,
                start with letter/underscore, contain only alphanumeric/_/-).
        """
        # Use centralized validation from nexus3.core.identifiers
        # allow_reserved=True because built-in skills may use reserved prefixes
        validate_tool_name(name, allow_reserved=True)

        # Clear cached instance if re-registering
        self._instances.pop(name, None)

        # Store spec (metadata may be empty initially for lazy resolution)
        self._specs[name] = SkillSpec(
            name=name,
            description=description or "",
            parameters=parameters or {},
            factory=factory,
        )

    def get(self, name: str) -> Skill | None:
        """Get a skill instance by name (lazy instantiation).

        On first call, the skill's factory is invoked with the ServiceContainer
        to create the instance. Subsequent calls return the cached instance.

        Args:
            name: The name of the skill to retrieve.

        Returns:
            The skill instance, or None if no skill is registered with that name.
        """
        if name in self._instances:
            return self._instances[name]

        spec = self._specs.get(name)
        if not spec:
            return None

        skill = spec.factory(self._services)
        self._instances[name] = skill
        return skill

    def get_definitions(self) -> list[dict[str, Any]]:
        """Get OpenAI-format tool definitions for all registered skills.

        Returns a list of tool definitions suitable for passing to an LLM API.
        Each definition includes the skill's name, description, and parameters
        schema.

        OPTIMIZATION: Uses SkillSpec metadata when available, avoiding skill
        instantiation. Falls back to instantiation only when metadata wasn't
        provided at registration time.

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
        for name, spec in self._specs.items():
            # Use spec metadata directly - no instantiation needed!
            if spec.description and spec.parameters:
                definitions.append({
                    "type": "function",
                    "function": {
                        "name": spec.name,
                        "description": spec.description,
                        "parameters": spec.parameters,
                    }
                })
            else:
                # Fallback: instantiate to get metadata (backwards compat)
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

        OPTIMIZATION: Uses SkillSpec metadata when available, avoiding skill
        instantiation. Falls back to instantiation only when metadata wasn't
        provided at registration time.

        Args:
            permissions: The agent's permissions containing tool_permissions
                with enabled/disabled status for each tool.

        Returns:
            List of tool definitions for enabled tools only.
            Disabled tools are completely omitted from the list.
        """
        definitions = []
        for name, spec in self._specs.items():
            # Check if tool is disabled in permissions
            tool_perm = permissions.tool_permissions.get(name)
            if tool_perm is not None and not tool_perm.enabled:
                # Tool is explicitly disabled - don't include definition
                continue

            # Use spec metadata directly - no instantiation needed!
            if spec.description and spec.parameters:
                definitions.append({
                    "type": "function",
                    "function": {
                        "name": spec.name,
                        "description": spec.description,
                        "parameters": spec.parameters,
                    }
                })
            else:
                # Fallback: instantiate to get metadata (backwards compat)
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
        return list(self._specs.keys())

    @property
    def services(self) -> ServiceContainer:
        """Access the service container.

        Returns:
            The ServiceContainer used for dependency injection.
        """
        return self._services
