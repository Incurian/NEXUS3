"""Skill-related error classes for NEXUS3."""

from nexus3.core.errors import NexusError


class SkillError(NexusError):
    """Base class for all skill-related errors."""


class SkillNotFoundError(SkillError):
    """Raised when a skill is not found in the registry."""

    def __init__(self, skill_name: str) -> None:
        self.skill_name = skill_name
        super().__init__(f"Skill not found: {skill_name}")


class SkillExecutionError(SkillError):
    """Raised when skill execution fails."""

    def __init__(self, skill_name: str, reason: str) -> None:
        self.skill_name = skill_name
        self.reason = reason
        super().__init__(f"Skill '{skill_name}' execution failed: {reason}")
