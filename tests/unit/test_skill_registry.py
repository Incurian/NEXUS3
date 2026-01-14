"""Unit tests for the skill system: ServiceContainer, SkillRegistry, and EchoSkill."""

import pytest

from nexus3.core.permissions import (
    AgentPermissions,
    PermissionLevel,
    PermissionPolicy,
    ToolPermission,
)
from nexus3.core.types import ToolResult
from nexus3.skill import ServiceContainer, SkillRegistry
from nexus3.skill.builtin.echo import EchoSkill, echo_skill_factory


class TestServiceContainer:
    """Tests for ServiceContainer."""

    def test_register_and_get_service(self):
        """Services can be registered and retrieved."""
        container = ServiceContainer()
        container.register("my_service", "service_value")

        result = container.get("my_service")
        assert result == "service_value"

    def test_get_nonexistent_returns_none(self):
        """get() returns None for unregistered services."""
        container = ServiceContainer()

        result = container.get("nonexistent")
        assert result is None

    def test_has_service(self):
        """has() returns True for registered services, False otherwise."""
        container = ServiceContainer()
        container.register("exists", "value")

        assert container.has("exists") is True
        assert container.has("does_not_exist") is False

    def test_require_returns_registered_service(self):
        """require() returns the service when registered."""
        container = ServiceContainer()
        container.register("required_service", "important_value")

        result = container.require("required_service")
        assert result == "important_value"

    def test_require_raises_on_missing(self):
        """require() raises KeyError for unregistered services."""
        container = ServiceContainer()

        with pytest.raises(KeyError) as exc_info:
            container.require("missing_service")

        assert "missing_service" in str(exc_info.value)

    def test_unregister_removes_service(self):
        """unregister() removes the service and returns it."""
        container = ServiceContainer()
        container.register("temp", "temp_value")

        result = container.unregister("temp")
        assert result == "temp_value"
        assert container.has("temp") is False

    def test_unregister_nonexistent_returns_none(self):
        """unregister() returns None for unregistered services."""
        container = ServiceContainer()

        result = container.unregister("nonexistent")
        assert result is None

    def test_clear_removes_all_services(self):
        """clear() removes all registered services."""
        container = ServiceContainer()
        container.register("a", 1)
        container.register("b", 2)

        container.clear()
        assert container.has("a") is False
        assert container.has("b") is False
        assert container.names() == []

    def test_names_returns_registered_names(self):
        """names() returns a list of all registered service names."""
        container = ServiceContainer()
        container.register("alpha", 1)
        container.register("beta", 2)

        names = container.names()
        assert set(names) == {"alpha", "beta"}

    def test_register_overwrites_existing(self):
        """Registering the same name overwrites the previous service."""
        container = ServiceContainer()
        container.register("key", "original")
        container.register("key", "updated")

        assert container.get("key") == "updated"


class TestServiceContainerToolAllowedPaths:
    """Tests for ServiceContainer.get_tool_allowed_paths() per-tool path resolution."""

    def test_returns_fallback_when_no_permissions(self):
        """Falls back to 'allowed_paths' service when no permissions object."""
        from pathlib import Path

        container = ServiceContainer()
        container.register("allowed_paths", [Path("/sandbox")])

        result = container.get_tool_allowed_paths("write_file")
        assert result == [Path("/sandbox")]

    def test_returns_none_when_nothing_configured(self):
        """Returns None when neither permissions nor allowed_paths configured."""
        container = ServiceContainer()

        result = container.get_tool_allowed_paths("write_file")
        assert result is None

    def test_returns_general_allowed_paths_when_no_tool_override(self):
        """Returns effective_policy.allowed_paths when no per-tool override."""
        from pathlib import Path

        container = ServiceContainer()
        permissions = AgentPermissions(
            base_preset="sandboxed",
            effective_policy=PermissionPolicy(
                level=PermissionLevel.SANDBOXED,
                allowed_paths=[Path("/sandbox")],
            ),
            tool_permissions={},  # No per-tool overrides
        )
        container.register("permissions", permissions)

        result = container.get_tool_allowed_paths("read_file")
        assert result == [Path("/sandbox")]

    def test_returns_per_tool_allowed_paths_when_set(self):
        """Returns per-tool allowed_paths when override exists."""
        from pathlib import Path

        container = ServiceContainer()
        permissions = AgentPermissions(
            base_preset="sandboxed",
            effective_policy=PermissionPolicy(
                level=PermissionLevel.SANDBOXED,
                allowed_paths=[Path("/sandbox")],  # General sandbox
            ),
            tool_permissions={
                "write_file": ToolPermission(
                    enabled=True,
                    allowed_paths=[Path("/sandbox/output")],  # More restrictive
                ),
            },
        )
        container.register("permissions", permissions)

        # write_file should use its per-tool override
        result = container.get_tool_allowed_paths("write_file")
        assert result == [Path("/sandbox/output")]

        # read_file has no override, should use general allowed_paths
        result = container.get_tool_allowed_paths("read_file")
        assert result == [Path("/sandbox")]

    def test_per_tool_none_means_inherit(self):
        """Per-tool allowed_paths=None means inherit from policy."""
        from pathlib import Path

        container = ServiceContainer()
        permissions = AgentPermissions(
            base_preset="sandboxed",
            effective_policy=PermissionPolicy(
                level=PermissionLevel.SANDBOXED,
                allowed_paths=[Path("/sandbox")],
            ),
            tool_permissions={
                "write_file": ToolPermission(
                    enabled=True,
                    allowed_paths=None,  # Explicitly None = inherit
                ),
            },
        )
        container.register("permissions", permissions)

        # Should inherit from policy even though ToolPermission exists
        result = container.get_tool_allowed_paths("write_file")
        assert result == [Path("/sandbox")]

    def test_per_tool_empty_list_means_deny_all(self):
        """Per-tool allowed_paths=[] means deny all paths."""
        from pathlib import Path

        container = ServiceContainer()
        permissions = AgentPermissions(
            base_preset="sandboxed",
            effective_policy=PermissionPolicy(
                level=PermissionLevel.SANDBOXED,
                allowed_paths=[Path("/sandbox")],
            ),
            tool_permissions={
                "write_file": ToolPermission(
                    enabled=True,
                    allowed_paths=[],  # Empty = deny all
                ),
            },
        )
        container.register("permissions", permissions)

        # Empty list means tool cannot access any paths
        result = container.get_tool_allowed_paths("write_file")
        assert result == []


class TestSkillRegistry:
    """Tests for SkillRegistry."""

    def test_register_and_get_skill(self):
        """Skills can be registered and retrieved."""
        registry = SkillRegistry()
        registry.register("echo", echo_skill_factory)

        skill = registry.get("echo")
        assert skill is not None
        assert skill.name == "echo"

    def test_get_unknown_skill_returns_none(self):
        """get() returns None for unregistered skills."""
        registry = SkillRegistry()

        result = registry.get("nonexistent_skill")
        assert result is None

    def test_get_definitions_format(self):
        """get_definitions() returns OpenAI-format tool definitions."""
        registry = SkillRegistry()
        registry.register("echo", echo_skill_factory)

        definitions = registry.get_definitions()

        assert len(definitions) == 1
        definition = definitions[0]

        # Check top-level structure
        assert definition["type"] == "function"
        assert "function" in definition

        # Check function details
        func = definition["function"]
        assert func["name"] == "echo"
        assert "description" in func
        assert "parameters" in func

        # Check parameters structure
        params = func["parameters"]
        assert params["type"] == "object"
        assert "message" in params["properties"]
        assert "message" in params["required"]

    def test_lazy_instantiation(self):
        """Skill factory is called only once (lazy, cached)."""
        call_count = []

        def counting_factory(services: ServiceContainer) -> EchoSkill:
            call_count.append(1)
            return EchoSkill()

        registry = SkillRegistry()
        registry.register("echo", counting_factory)

        # Factory not called yet
        assert len(call_count) == 0

        # First get() calls factory
        skill1 = registry.get("echo")
        assert len(call_count) == 1
        assert skill1 is not None

        # Second get() returns cached instance
        skill2 = registry.get("echo")
        assert len(call_count) == 1  # Still 1, not called again
        assert skill2 is skill1  # Same instance

    def test_names_property(self):
        """names property returns list of registered skill names."""
        registry = SkillRegistry()

        assert registry.names == []

        registry.register("echo", echo_skill_factory)
        registry.register("other", echo_skill_factory)

        assert set(registry.names) == {"echo", "other"}

    def test_services_property(self):
        """services property returns the ServiceContainer."""
        services = ServiceContainer()
        services.register("test", "value")
        registry = SkillRegistry(services)

        assert registry.services is services
        assert registry.services.get("test") == "value"

    def test_creates_default_services_if_none_provided(self):
        """SkillRegistry creates a ServiceContainer if none provided."""
        registry = SkillRegistry()

        assert registry.services is not None
        assert isinstance(registry.services, ServiceContainer)

    def test_reregister_clears_cached_instance(self):
        """Re-registering a skill clears the cached instance."""
        call_count = []

        def factory_v1(services: ServiceContainer) -> EchoSkill:
            call_count.append("v1")
            return EchoSkill()

        def factory_v2(services: ServiceContainer) -> EchoSkill:
            call_count.append("v2")
            return EchoSkill()

        registry = SkillRegistry()
        registry.register("echo", factory_v1)
        skill1 = registry.get("echo")
        assert call_count == ["v1"]

        # Re-register with new factory
        registry.register("echo", factory_v2)
        skill2 = registry.get("echo")
        assert call_count == ["v1", "v2"]
        assert skill2 is not skill1

    def test_factory_receives_services(self):
        """Skill factory receives the ServiceContainer."""
        received_services = []

        def capturing_factory(services: ServiceContainer) -> EchoSkill:
            received_services.append(services)
            return EchoSkill()

        services = ServiceContainer()
        services.register("custom", "data")
        registry = SkillRegistry(services)
        registry.register("echo", capturing_factory)

        registry.get("echo")

        assert len(received_services) == 1
        assert received_services[0] is services
        assert received_services[0].get("custom") == "data"

    def test_get_definitions_with_multiple_skills(self):
        """get_definitions() returns definitions for all skills."""

        def other_skill_factory(services: ServiceContainer):
            # Create a simple mock skill
            class OtherSkill:
                @property
                def name(self) -> str:
                    return "other"

                @property
                def description(self) -> str:
                    return "Another test skill"

                @property
                def parameters(self) -> dict:
                    return {"type": "object", "properties": {}}

                async def execute(self, **kwargs):
                    return ToolResult(output="other")

            return OtherSkill()

        registry = SkillRegistry()
        registry.register("echo", echo_skill_factory)
        registry.register("other", other_skill_factory)

        definitions = registry.get_definitions()

        assert len(definitions) == 2
        names = {d["function"]["name"] for d in definitions}
        assert names == {"echo", "other"}


class TestEchoSkill:
    """Tests for EchoSkill."""

    def test_echo_skill_properties(self):
        """EchoSkill has correct name, description, and parameters."""
        skill = EchoSkill()

        assert skill.name == "echo"
        assert "echo" in skill.description.lower()

        params = skill.parameters
        assert params["type"] == "object"
        assert "message" in params["properties"]
        assert params["properties"]["message"]["type"] == "string"
        assert "message" in params["required"]

    @pytest.mark.asyncio
    async def test_echo_skill_execute(self):
        """EchoSkill.execute() echoes the message back."""
        skill = EchoSkill()

        result = await skill.execute(message="Hello, world!")

        assert isinstance(result, ToolResult)
        assert result.success is True
        assert result.output == "Hello, world!"
        assert result.error == ""

    @pytest.mark.asyncio
    async def test_echo_skill_execute_empty_message(self):
        """EchoSkill.execute() handles empty message."""
        skill = EchoSkill()

        result = await skill.execute(message="")

        assert result.success is True
        assert result.output == ""

    @pytest.mark.asyncio
    async def test_echo_skill_execute_default_message(self):
        """EchoSkill.execute() uses empty string as default message."""
        skill = EchoSkill()

        result = await skill.execute()

        assert result.success is True
        assert result.output == ""

    @pytest.mark.asyncio
    async def test_echo_skill_execute_ignores_extra_kwargs(self):
        """EchoSkill.execute() ignores extra keyword arguments."""
        skill = EchoSkill()

        result = await skill.execute(message="test", extra_arg="ignored")

        assert result.success is True
        assert result.output == "test"


class TestEchoSkillFactory:
    """Tests for echo_skill_factory."""

    def test_factory_returns_echo_skill(self):
        """echo_skill_factory() returns an EchoSkill instance."""
        services = ServiceContainer()

        skill = echo_skill_factory(services)

        assert isinstance(skill, EchoSkill)
        assert skill.name == "echo"

    def test_factory_ignores_services(self):
        """echo_skill_factory() doesn't require any services."""
        # Empty services should work fine
        services = ServiceContainer()
        skill = echo_skill_factory(services)
        assert skill is not None

        # Services with data should also work
        services_with_data = ServiceContainer()
        services_with_data.register("some_service", "value")
        skill2 = echo_skill_factory(services_with_data)
        assert skill2 is not None


class TestSkillRegistryPermissionFiltering:
    """Tests for get_definitions_for_permissions() method.

    SECURITY: These tests verify that disabled tools are not exposed to the LLM.
    """

    def _create_test_skill_factory(self, name: str, desc: str):
        """Helper to create a test skill factory."""
        def factory(services: ServiceContainer):
            class TestSkill:
                @property
                def name(self) -> str:
                    return name

                @property
                def description(self) -> str:
                    return desc

                @property
                def parameters(self) -> dict:
                    return {"type": "object", "properties": {}}

                async def execute(self, **kwargs):
                    return ToolResult(output=name)

            return TestSkill()
        return factory

    def test_all_tools_enabled_by_default(self):
        """When no tools are disabled, all definitions are returned."""
        registry = SkillRegistry()
        registry.register("echo", echo_skill_factory)
        registry.register("tool1", self._create_test_skill_factory("tool1", "Test tool 1"))
        registry.register("tool2", self._create_test_skill_factory("tool2", "Test tool 2"))

        # Permissions with no disabled tools
        policy = PermissionPolicy(level=PermissionLevel.TRUSTED)
        permissions = AgentPermissions(
            base_preset="trusted",
            effective_policy=policy,
            tool_permissions={},  # All enabled by default
        )

        definitions = registry.get_definitions_for_permissions(permissions)

        assert len(definitions) == 3
        names = {d["function"]["name"] for d in definitions}
        assert names == {"echo", "tool1", "tool2"}

    def test_disabled_tool_not_in_definitions(self):
        """Disabled tools are excluded from definitions."""
        registry = SkillRegistry()
        registry.register("echo", echo_skill_factory)
        registry.register("write_file", self._create_test_skill_factory("write_file", "Write file"))
        registry.register("read_file", self._create_test_skill_factory("read_file", "Read file"))

        # Permissions with write_file disabled
        policy = PermissionPolicy(level=PermissionLevel.TRUSTED)
        permissions = AgentPermissions(
            base_preset="trusted",
            effective_policy=policy,
            tool_permissions={"write_file": ToolPermission(enabled=False)},
        )

        definitions = registry.get_definitions_for_permissions(permissions)

        # write_file should be excluded
        names = {d["function"]["name"] for d in definitions}
        assert "write_file" not in names
        assert "echo" in names
        assert "read_file" in names
        assert len(definitions) == 2

    def test_multiple_disabled_tools(self):
        """Multiple disabled tools are all excluded."""
        registry = SkillRegistry()
        registry.register("echo", echo_skill_factory)
        registry.register("nexus_create", self._create_test_skill_factory("nexus_create", "Create agent"))
        registry.register("nexus_destroy", self._create_test_skill_factory("nexus_destroy", "Destroy agent"))
        registry.register("nexus_send", self._create_test_skill_factory("nexus_send", "Send message"))
        registry.register("read_file", self._create_test_skill_factory("read_file", "Read file"))

        # Sandboxed preset typically disables nexus tools
        policy = PermissionPolicy(level=PermissionLevel.SANDBOXED)
        permissions = AgentPermissions(
            base_preset="sandboxed",
            effective_policy=policy,
            tool_permissions={
                "nexus_create": ToolPermission(enabled=False),
                "nexus_destroy": ToolPermission(enabled=False),
                "nexus_send": ToolPermission(enabled=False),
            },
        )

        definitions = registry.get_definitions_for_permissions(permissions)

        names = {d["function"]["name"] for d in definitions}
        assert "nexus_create" not in names
        assert "nexus_destroy" not in names
        assert "nexus_send" not in names
        assert "echo" in names
        assert "read_file" in names
        assert len(definitions) == 2

    def test_enabled_true_explicitly_is_included(self):
        """Tools explicitly marked enabled=True are included."""
        registry = SkillRegistry()
        registry.register("echo", echo_skill_factory)
        registry.register("tool1", self._create_test_skill_factory("tool1", "Test tool"))

        policy = PermissionPolicy(level=PermissionLevel.TRUSTED)
        permissions = AgentPermissions(
            base_preset="trusted",
            effective_policy=policy,
            tool_permissions={"tool1": ToolPermission(enabled=True)},  # Explicitly enabled
        )

        definitions = registry.get_definitions_for_permissions(permissions)

        names = {d["function"]["name"] for d in definitions}
        assert "tool1" in names
        assert "echo" in names

    def test_all_tools_disabled_returns_empty(self):
        """If all tools are disabled, empty list is returned."""
        registry = SkillRegistry()
        registry.register("echo", echo_skill_factory)
        registry.register("tool1", self._create_test_skill_factory("tool1", "Test tool"))

        policy = PermissionPolicy(level=PermissionLevel.SANDBOXED)
        permissions = AgentPermissions(
            base_preset="worker",
            effective_policy=policy,
            tool_permissions={
                "echo": ToolPermission(enabled=False),
                "tool1": ToolPermission(enabled=False),
            },
        )

        definitions = registry.get_definitions_for_permissions(permissions)

        assert definitions == []

    def test_tool_not_in_registry_permissions_ignored(self):
        """Permissions for tools not in registry are ignored."""
        registry = SkillRegistry()
        registry.register("echo", echo_skill_factory)

        # Disable a tool that doesn't exist in registry
        policy = PermissionPolicy(level=PermissionLevel.TRUSTED)
        permissions = AgentPermissions(
            base_preset="trusted",
            effective_policy=policy,
            tool_permissions={"nonexistent_tool": ToolPermission(enabled=False)},
        )

        definitions = registry.get_definitions_for_permissions(permissions)

        # Should just include echo, nonexistent_tool is ignored
        assert len(definitions) == 1
        assert definitions[0]["function"]["name"] == "echo"

    def test_sandboxed_agent_cannot_see_nexus_create(self):
        """SECURITY: Sandboxed agents should not see nexus_create in tool definitions.

        This is the key security test - we want to ensure that agents with
        restricted permissions cannot even see tools they're not allowed to use.
        """
        from nexus3.core.permissions import resolve_preset

        registry = SkillRegistry()
        registry.register("read_file", self._create_test_skill_factory("read_file", "Read file"))
        registry.register("write_file", self._create_test_skill_factory("write_file", "Write file"))
        registry.register("nexus_create", self._create_test_skill_factory("nexus_create", "Create agent"))
        registry.register("nexus_send", self._create_test_skill_factory("nexus_send", "Send message"))

        # Get sandboxed permissions which has nexus tools disabled
        permissions = resolve_preset("sandboxed")

        definitions = registry.get_definitions_for_permissions(permissions)

        names = {d["function"]["name"] for d in definitions}
        # Sandboxed agents should not see nexus_create or nexus_send
        assert "nexus_create" not in names
        assert "nexus_send" not in names
        # But should see file tools
        assert "read_file" in names
        assert "write_file" in names
