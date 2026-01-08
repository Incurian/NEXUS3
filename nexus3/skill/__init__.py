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

from nexus3.skill.base import BaseSkill, Skill
from nexus3.skill.errors import SkillError, SkillExecutionError, SkillNotFoundError
from nexus3.skill.registry import SkillFactory, SkillRegistry
from nexus3.skill.services import ServiceContainer

__all__ = [
    # Protocol and base
    "Skill",
    "BaseSkill",
    # Registry
    "SkillRegistry",
    "SkillFactory",
    # Services
    "ServiceContainer",
    # Errors
    "SkillError",
    "SkillNotFoundError",
    "SkillExecutionError",
]
