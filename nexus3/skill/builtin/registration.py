"""Registration helpers for built-in skills."""

from nexus3.skill.builtin.append_file import append_file_factory
from nexus3.skill.builtin.bash import bash_safe_factory, shell_unsafe_factory
from nexus3.skill.builtin.concat_files import concat_files_factory
from nexus3.skill.builtin.copy_file import copy_file_factory
from nexus3.skill.builtin.edit_file import edit_file_factory
from nexus3.skill.builtin.edit_lines import edit_lines_factory
from nexus3.skill.builtin.file_info import file_info_factory
from nexus3.skill.builtin.git import git_factory
from nexus3.skill.builtin.glob_search import glob_factory
from nexus3.skill.builtin.grep import grep_factory
from nexus3.skill.builtin.list_directory import list_directory_factory
from nexus3.skill.builtin.mkdir import mkdir_factory
from nexus3.skill.builtin.nexus_cancel import nexus_cancel_factory
from nexus3.skill.builtin.nexus_create import nexus_create_factory
from nexus3.skill.builtin.nexus_destroy import nexus_destroy_factory
from nexus3.skill.builtin.nexus_send import nexus_send_factory
from nexus3.skill.builtin.nexus_shutdown import nexus_shutdown_factory
from nexus3.skill.builtin.nexus_status import nexus_status_factory
from nexus3.skill.builtin.patch import patch_factory
from nexus3.skill.builtin.read_file import read_file_factory
from nexus3.skill.builtin.regex_replace import regex_replace_factory
from nexus3.skill.builtin.rename import rename_factory
from nexus3.skill.builtin.run_python import run_python_factory
from nexus3.skill.builtin.sleep import sleep_skill_factory
from nexus3.skill.builtin.tail import tail_factory
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
    # File operations (read-only)
    registry.register("read_file", read_file_factory)
    registry.register("tail", tail_factory)
    registry.register("file_info", file_info_factory)
    registry.register("list_directory", list_directory_factory)
    registry.register("glob", glob_factory)
    registry.register("grep", grep_factory)
    registry.register("concat_files", concat_files_factory)

    # File operations (destructive)
    registry.register("write_file", write_file_factory)
    registry.register("edit_file", edit_file_factory)
    registry.register("edit_lines", edit_lines_factory)
    registry.register("append_file", append_file_factory)
    registry.register("regex_replace", regex_replace_factory)
    registry.register("patch", patch_factory)
    registry.register("copy_file", copy_file_factory)
    registry.register("mkdir", mkdir_factory)
    registry.register("rename", rename_factory)

    # Version control (permission-filtered internally)
    registry.register("git", git_factory)

    # Execution (high-risk, disabled in SANDBOXED)
    # bash_safe: shlex.split + subprocess_exec (no shell operators)
    # shell_UNSAFE: shell=True (pipes, redirects work, but injection-vulnerable)
    registry.register("bash_safe", bash_safe_factory)
    registry.register("shell_UNSAFE", shell_unsafe_factory)
    registry.register("run_python", run_python_factory)

    # Agent management
    registry.register("nexus_create", nexus_create_factory)
    registry.register("nexus_destroy", nexus_destroy_factory)
    registry.register("nexus_send", nexus_send_factory)
    registry.register("nexus_cancel", nexus_cancel_factory)
    registry.register("nexus_status", nexus_status_factory)
    registry.register("nexus_shutdown", nexus_shutdown_factory)

    # Utility
    registry.register("sleep", sleep_skill_factory)
