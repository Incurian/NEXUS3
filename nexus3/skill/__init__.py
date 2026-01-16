"""Skill (tool) system for NEXUS3.

This module provides the skill infrastructure for tool execution:
- Skill protocol for implementing tools
- SkillRegistry for managing available skills
- ServiceContainer for dependency injection
- Built-in skills (echo, etc.)

Example:
    from nexus3.skill import SkillRegistry, ServiceContainer
    from nexus3.skill.builtin import register_builtin_skills

    services = ServiceContainer()
    registry = SkillRegistry(services)
    register_builtin_skills(registry)

    # Get tool definitions for LLM
    tools = registry.get_definitions()
"""

from nexus3.skill.base import (
    BaseSkill,
    ExecutionSkill,
    FileSkill,
    FilteredCommandSkill,
    NexusSkill,
    Skill,
    execution_skill_factory,
    file_skill_factory,
    filtered_command_skill_factory,
    nexus_skill_factory,
)
from nexus3.skill.errors import SkillError, SkillExecutionError, SkillNotFoundError
from nexus3.skill.registry import SkillFactory, SkillRegistry, SkillSpec
from nexus3.skill.services import ServiceContainer

__all__ = [
    # Protocol and base classes
    "Skill",
    "BaseSkill",
    "FileSkill",
    "NexusSkill",
    "ExecutionSkill",
    "FilteredCommandSkill",
    # Factory decorators
    "file_skill_factory",
    "nexus_skill_factory",
    "execution_skill_factory",
    "filtered_command_skill_factory",
    # Registry
    "SkillRegistry",
    "SkillFactory",
    "SkillSpec",
    # Services
    "ServiceContainer",
    # Errors
    "SkillError",
    "SkillNotFoundError",
    "SkillExecutionError",
]
