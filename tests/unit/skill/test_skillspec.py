"""Tests for SkillSpec and registry no-instantiation behavior."""

import pytest

from nexus3.core.types import ToolResult
from nexus3.skill.registry import SkillRegistry, SkillSpec
from nexus3.skill.services import ServiceContainer


class TestSkillSpecNoInstantiation:
    """Verify get_definitions() doesn't instantiate when metadata provided."""

    def test_get_definitions_with_metadata_no_instantiation(self):
        """When description/parameters provided, no factory call needed."""
        call_count = []

        def counting_factory(services: ServiceContainer) -> object:
            call_count.append(1)
            # Return a mock skill
            class MockSkill:
                name = "test_skill"
                description = "Test"
                parameters = {"type": "object", "properties": {}}

                async def execute(self, **kwargs):
                    return ToolResult(output="ok")

            return MockSkill()

        registry = SkillRegistry()
        registry.register(
            "test_skill",
            counting_factory,
            description="Test skill",
            parameters={"type": "object", "properties": {}},
        )

        # get_definitions should NOT call factory
        definitions = registry.get_definitions()

        assert len(call_count) == 0, "Factory should not be called when metadata provided"
        assert len(definitions) == 1
        assert definitions[0]["function"]["name"] == "test_skill"

    def test_get_definitions_without_metadata_triggers_instantiation(self):
        """When no metadata provided, factory is called to get it."""
        call_count = []

        def counting_factory(services: ServiceContainer) -> object:
            call_count.append(1)

            class MockSkill:
                name = "lazy_skill"
                description = "Lazy test"
                parameters = {"type": "object", "properties": {}}

                async def execute(self, **kwargs):
                    return ToolResult(output="ok")

            return MockSkill()

        registry = SkillRegistry()

        # Register WITHOUT metadata
        registry.register("lazy_skill", counting_factory)

        # get_definitions should call factory to get metadata
        definitions = registry.get_definitions()

        assert len(call_count) == 1, "Factory should be called when no metadata"
        assert len(definitions) == 1

    def test_skillspec_dataclass(self):
        """SkillSpec is a frozen dataclass with expected fields."""
        spec = SkillSpec(
            name="test",
            description="A test skill",
            parameters={"type": "object"},
            factory=lambda s: None,  # type: ignore
        )

        assert spec.name == "test"
        assert spec.description == "A test skill"
        assert spec.parameters == {"type": "object"}

        # Should be frozen
        with pytest.raises(AttributeError):
            spec.name = "changed"  # type: ignore

    def test_get_definitions_for_permissions_with_metadata_no_instantiation(self):
        """get_definitions_for_permissions() also uses metadata optimization."""
        from nexus3.core.permissions import (
            AgentPermissions,
            PermissionLevel,
            PermissionPolicy,
        )

        call_count = []

        def counting_factory(services: ServiceContainer) -> object:
            call_count.append(1)

            class MockSkill:
                name = "perm_skill"
                description = "Permission test"
                parameters = {"type": "object", "properties": {}}

                async def execute(self, **kwargs):
                    return ToolResult(output="ok")

            return MockSkill()

        registry = SkillRegistry()
        registry.register(
            "perm_skill",
            counting_factory,
            description="Permission test skill",
            parameters={"type": "object", "properties": {}},
        )

        # Create permissions with no disabled tools
        permissions = AgentPermissions(
            base_preset="trusted",
            effective_policy=PermissionPolicy(level=PermissionLevel.TRUSTED),
            tool_permissions={},
        )

        # get_definitions_for_permissions should NOT call factory
        definitions = registry.get_definitions_for_permissions(permissions)

        assert len(call_count) == 0, "Factory should not be called when metadata provided"
        assert len(definitions) == 1
        assert definitions[0]["function"]["name"] == "perm_skill"

    def test_multiple_skills_metadata_no_instantiation(self):
        """Multiple skills with metadata should not trigger any instantiation."""
        call_counts = {"skill1": [], "skill2": [], "skill3": []}

        def make_factory(skill_name: str):
            def factory(services: ServiceContainer):
                call_counts[skill_name].append(1)

                class MockSkill:
                    name = skill_name
                    description = f"{skill_name} description"
                    parameters = {"type": "object", "properties": {}}

                    async def execute(self, **kwargs):
                        return ToolResult(output=skill_name)

                return MockSkill()

            return factory

        registry = SkillRegistry()
        for name in ["skill1", "skill2", "skill3"]:
            registry.register(
                name,
                make_factory(name),
                description=f"{name} description",
                parameters={"type": "object", "properties": {}},
            )

        # get_definitions should NOT call any factories
        definitions = registry.get_definitions()

        assert len(definitions) == 3
        for name in ["skill1", "skill2", "skill3"]:
            assert (
                len(call_counts[name]) == 0
            ), f"Factory for {name} should not be called"

    def test_partial_metadata_triggers_instantiation(self):
        """If only description provided (no parameters), factory is called."""
        call_count = []

        def counting_factory(services: ServiceContainer) -> object:
            call_count.append(1)

            class MockSkill:
                name = "partial_skill"
                description = "Partial metadata"
                parameters = {"type": "object", "properties": {"x": {"type": "string"}}}

                async def execute(self, **kwargs):
                    return ToolResult(output="ok")

            return MockSkill()

        registry = SkillRegistry()
        # Register with only description, no parameters
        registry.register(
            "partial_skill",
            counting_factory,
            description="Has description",
            parameters=None,  # Missing parameters
        )

        # get_definitions should call factory because parameters is missing
        definitions = registry.get_definitions()

        assert len(call_count) == 1, "Factory should be called when parameters missing"
        assert len(definitions) == 1

    def test_empty_description_triggers_instantiation(self):
        """Empty description triggers instantiation to get real metadata."""
        call_count = []

        def counting_factory(services: ServiceContainer) -> object:
            call_count.append(1)

            class MockSkill:
                name = "empty_desc_skill"
                description = "Real description from skill"
                parameters = {"type": "object", "properties": {}}

                async def execute(self, **kwargs):
                    return ToolResult(output="ok")

            return MockSkill()

        registry = SkillRegistry()
        # Register with empty description
        registry.register(
            "empty_desc_skill",
            counting_factory,
            description="",  # Empty description
            parameters={"type": "object", "properties": {}},
        )

        # get_definitions should call factory because description is empty
        definitions = registry.get_definitions()

        assert (
            len(call_count) == 1
        ), "Factory should be called when description is empty"
        assert len(definitions) == 1

    def test_empty_parameters_triggers_instantiation(self):
        """Empty parameters dict triggers instantiation to get real metadata."""
        call_count = []

        def counting_factory(services: ServiceContainer) -> object:
            call_count.append(1)

            class MockSkill:
                name = "empty_params_skill"
                description = "Has description"
                parameters = {"type": "object", "properties": {"x": {"type": "int"}}}

                async def execute(self, **kwargs):
                    return ToolResult(output="ok")

            return MockSkill()

        registry = SkillRegistry()
        # Register with empty parameters dict
        registry.register(
            "empty_params_skill",
            counting_factory,
            description="Has description",
            parameters={},  # Empty parameters
        )

        # get_definitions should call factory because parameters is empty
        definitions = registry.get_definitions()

        assert (
            len(call_count) == 1
        ), "Factory should be called when parameters is empty"
        assert len(definitions) == 1


class TestSkillSpecIntegration:
    """Integration tests for SkillSpec with real skill registration patterns."""

    def test_registry_caches_instance_after_get(self):
        """After calling get(), subsequent calls return cached instance."""
        call_count = []

        def counting_factory(services: ServiceContainer) -> object:
            call_count.append(1)

            class MockSkill:
                name = "cached_skill"
                description = "Cached test"
                parameters = {"type": "object", "properties": {}}

                async def execute(self, **kwargs):
                    return ToolResult(output="ok")

            return MockSkill()

        registry = SkillRegistry()
        registry.register(
            "cached_skill",
            counting_factory,
            description="Cached test",
            parameters={"type": "object", "properties": {}},
        )

        # First get_definitions shouldn't instantiate
        registry.get_definitions()
        assert len(call_count) == 0

        # First get() should instantiate
        skill1 = registry.get("cached_skill")
        assert len(call_count) == 1
        assert skill1 is not None

        # Second get() should return cached
        skill2 = registry.get("cached_skill")
        assert len(call_count) == 1  # Still 1
        assert skill2 is skill1

    def test_re_registering_clears_cache_not_metadata(self):
        """Re-registering skill clears cached instance but new metadata takes effect."""
        call_count = {"v1": [], "v2": []}

        def v1_factory(services: ServiceContainer):
            call_count["v1"].append(1)

            class V1Skill:
                name = "versioned_skill"
                description = "V1"
                parameters = {"type": "object", "properties": {}}

                async def execute(self, **kwargs):
                    return ToolResult(output="v1")

            return V1Skill()

        def v2_factory(services: ServiceContainer):
            call_count["v2"].append(1)

            class V2Skill:
                name = "versioned_skill"
                description = "V2"
                parameters = {"type": "object", "properties": {"new": {"type": "string"}}}

                async def execute(self, **kwargs):
                    return ToolResult(output="v2")

            return V2Skill()

        registry = SkillRegistry()

        # Register v1 with metadata
        registry.register(
            "versioned_skill",
            v1_factory,
            description="V1 description",
            parameters={"type": "object", "properties": {}},
        )

        # Get skill (instantiates)
        skill1 = registry.get("versioned_skill")
        assert len(call_count["v1"]) == 1

        # Re-register with v2
        registry.register(
            "versioned_skill",
            v2_factory,
            description="V2 description",
            parameters={"type": "object", "properties": {"new": {"type": "string"}}},
        )

        # Definitions should use new metadata without instantiation
        definitions = registry.get_definitions()
        assert len(call_count["v2"]) == 0  # Not instantiated yet
        assert definitions[0]["function"]["description"] == "V2 description"

        # Getting skill should instantiate v2
        skill2 = registry.get("versioned_skill")
        assert len(call_count["v2"]) == 1
        assert skill2 is not skill1
