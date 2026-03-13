"""Init commands for setting up NEXUS3 configuration directories.

This module provides:
- `--init-global`: Initialize ~/.nexus3/ with default configuration
- `/init`: Initialize local project config under ./.nexus3/ and create a
  project instruction file in the current working directory

SECURITY: All file writes check for symlinks to prevent symlink attacks (P1.8).
"""

from pathlib import Path

from nexus3.core.constants import get_defaults_dir as _get_defaults_dir
from nexus3.core.constants import get_nexus_dir
from nexus3.core.secure_io import secure_mkdir


class InitSymlinkError(Exception):
    """Raised when init would overwrite a symlink (security violation)."""

    pass


def _safe_write_text(path: Path, content: str) -> None:
    """Write text to a file, refusing to follow symlinks.

    P1.8 SECURITY FIX: Prevents symlink attacks where an attacker creates
    a symlink at the target path to trick init into overwriting arbitrary files.

    Args:
        path: Path to write to.
        content: Content to write.

    Raises:
        InitSymlinkError: If the path is a symlink.
    """
    if path.is_symlink():
        raise InitSymlinkError(
            f"Refusing to overwrite symlink at {path}: potential attack"
        )
    path.write_text(content, encoding="utf-8")


def _path_exists_or_is_symlink(path: Path) -> bool:
    """Return True for regular existing paths and dangling symlinks."""
    return path.exists() or path.is_symlink()


# Template files
GENERIC_INSTRUCTION_TEMPLATE = """# Project Configuration

## Overview
<!-- Describe this project and how the agent should approach it -->

## Key Files
<!-- List important files and their purposes -->

## Conventions
<!-- Project-specific conventions, coding standards, etc. -->

## Notes
<!-- Any other context the agent should know -->
"""

CONFIG_JSON_TEMPLATE = """{
  "_comment": "Project-specific NEXUS3 configuration. All fields optional - extends global config.",
  "default_model": null,
  "providers": {
    "_comment": "Add project-specific provider configs here"
  },
  "permissions": {
    "_comment": "Project-specific permission overrides"
  }
}
"""

MCP_JSON_TEMPLATE = """{
  "servers": []
}
"""


def _read_text_if_not_symlink(path: Path) -> str | None:
    """Read a regular file as UTF-8, ignoring missing paths and symlinks."""
    if path.is_symlink() or not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def _get_project_instruction_template(filename: str) -> str:
    """Resolve the template content for a local project instruction file."""
    if filename == "AGENTS.md":
        user_agents = _read_text_if_not_symlink(get_nexus_dir() / "AGENTS.md")
        if user_agents is not None:
            return user_agents

        default_agents = _read_text_if_not_symlink(get_defaults_dir() / "AGENTS.md")
        if default_agents is not None:
            return default_agents

    return GENERIC_INSTRUCTION_TEMPLATE


def get_defaults_dir() -> Path:
    """Get the path to the defaults directory in the package."""
    return _get_defaults_dir()


def init_global(force: bool = False) -> tuple[bool, str]:
    """Initialize the global ~/.nexus3/ configuration directory.

    Copies default configuration files to the user's home directory.

    Args:
        force: If True, overwrite existing files. If False, skip if directory exists.

    Returns:
        Tuple of (success, message).
    """
    global_dir = get_nexus_dir()
    defaults_dir = get_defaults_dir()

    if global_dir.exists() and not force:
        return False, (
            f"Directory already exists: {global_dir}\n"
            "Use --init-global-force (CLI) or /init --global --force (REPL) to overwrite."
        )

    try:
        secure_mkdir(global_dir)

        # Copy NEXUS.md from defaults if it exists, otherwise use minimal
        # P1.8 SECURITY: Use _safe_write_text to prevent symlink attacks
        default_nexus = defaults_dir / "NEXUS.md"
        if default_nexus.exists():
            _safe_write_text(
                global_dir / "NEXUS.md",
                default_nexus.read_text(encoding="utf-8"),
            )
        else:
            _safe_write_text(
                global_dir / "NEXUS.md",
                "# Personal Configuration\n\nYou are NEXUS3, an AI-powered CLI assistant.\n",
            )

        # Copy AGENTS.md project-template seed from defaults if it exists.
        # Local /init uses this user-editable copy when creating project AGENTS.md.
        default_agents = _read_text_if_not_symlink(defaults_dir / "AGENTS.md")
        if default_agents is not None:
            _safe_write_text(global_dir / "AGENTS.md", default_agents)
        else:
            _safe_write_text(global_dir / "AGENTS.md", GENERIC_INSTRUCTION_TEMPLATE)

        # Copy config.json from defaults if it exists
        default_config = defaults_dir / "config.json"
        if default_config.exists():
            _safe_write_text(
                global_dir / "config.json",
                default_config.read_text(encoding="utf-8"),
            )
        else:
            _safe_write_text(global_dir / "config.json", "{}")

        # Create empty mcp.json
        _safe_write_text(global_dir / "mcp.json", MCP_JSON_TEMPLATE)

        # Create sessions directory with secure permissions
        secure_mkdir(global_dir / "sessions")

        return True, f"Initialized global configuration at {global_dir}"

    except InitSymlinkError as e:
        return False, f"Security error: {e}"
    except OSError as e:
        return False, f"Failed to create global config: {e}"


def init_local(
    cwd: Path | None = None,
    force: bool = False,
    filename: str = "AGENTS.md",
) -> tuple[bool, str]:
    """Initialize local project configuration files.

    Creates project-specific configuration files under `./.nexus3/` and writes
    the instruction markdown file into the project root for discoverability.

    Args:
        cwd: Directory to initialize in. Defaults to Path.cwd().
        force: If True, overwrite existing files. If False, fail if any target
            file already exists.
        filename: Name of the instruction file to create (default: AGENTS.md).

    Returns:
        Tuple of (success, message).
    """
    project_dir = cwd or Path.cwd()
    target_dir = project_dir / ".nexus3"
    instruction_path = project_dir / filename
    config_path = target_dir / "config.json"
    mcp_path = target_dir / "mcp.json"

    if target_dir.is_symlink():
        return False, (
            f"Security error: refusing to use symlinked config directory at {target_dir}"
        )
    if target_dir.exists() and not target_dir.is_dir():
        return False, (
            f"Failed to create project config: {target_dir} exists and is not a directory"
        )

    if not force:
        existing_paths = [
            path
            for path in (instruction_path, config_path, mcp_path)
            if _path_exists_or_is_symlink(path)
        ]
        if existing_paths:
            existing_list = "\n".join(f"- {path}" for path in existing_paths)
            return False, (
                f"Configuration already exists:\n{existing_list}\n"
                "Use /init --force to overwrite."
            )

    try:
        secure_mkdir(target_dir)

        # P1.8 SECURITY: Use _safe_write_text to prevent symlink attacks.
        # The instruction file lives at the project root for easier discovery.
        _safe_write_text(
            instruction_path,
            _get_project_instruction_template(filename),
        )

        # Create config.json template
        _safe_write_text(config_path, CONFIG_JSON_TEMPLATE)

        # Create empty mcp.json
        _safe_write_text(mcp_path, MCP_JSON_TEMPLATE)

        return True, (
            f"Initialized project configuration in {target_dir} and created "
            f"{instruction_path}"
        )

    except InitSymlinkError as e:
        return False, f"Security error: {e}"
    except OSError as e:
        return False, f"Failed to create project config: {e}"
