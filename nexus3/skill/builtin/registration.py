"""Registration helpers for built-in skills."""

from nexus3.skill.builtin.nexus_cancel import nexus_cancel_factory
from nexus3.skill.builtin.nexus_create import nexus_create_factory
from nexus3.skill.builtin.nexus_destroy import nexus_destroy_factory
from nexus3.skill.builtin.nexus_send import nexus_send_factory
from nexus3.skill.builtin.nexus_shutdown import nexus_shutdown_factory
from nexus3.skill.builtin.nexus_status import nexus_status_factory
from nexus3.skill.builtin.read_file import read_file_factory
from nexus3.skill.builtin.sleep import sleep_skill_factory
from nexus3.skill.builtin.write_file import write_file_factory
from nexus3.skill.registry import SkillRegistry


def register_builtin_skills(registry: SkillRegistry) -> None:
    """Register all built-in skills with the registry.

    Args:
        registry: The SkillRegistry to register skills with

    Example:
        services = ServiceContainer()
        registry = SkillRegistry(services)
        register_builtin_skills(registry)
    """
    registry.register("read_file", read_file_factory)
    registry.register("write_file", write_file_factory)
    registry.register("sleep", sleep_skill_factory)
    registry.register("nexus_create", nexus_create_factory)
    registry.register("nexus_destroy", nexus_destroy_factory)
    registry.register("nexus_send", nexus_send_factory)
    registry.register("nexus_cancel", nexus_cancel_factory)
    registry.register("nexus_status", nexus_status_factory)
    registry.register("nexus_shutdown", nexus_shutdown_factory)
