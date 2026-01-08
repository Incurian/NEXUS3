"""Built-in skills for NEXUS3."""

from nexus3.skill.builtin.nexus_cancel import nexus_cancel_factory
from nexus3.skill.builtin.nexus_send import nexus_send_factory
from nexus3.skill.builtin.nexus_shutdown import nexus_shutdown_factory
from nexus3.skill.builtin.nexus_status import nexus_status_factory
from nexus3.skill.builtin.registration import register_builtin_skills

__all__ = [
    "register_builtin_skills",
    "nexus_send_factory",
    "nexus_cancel_factory",
    "nexus_status_factory",
    "nexus_shutdown_factory",
]
