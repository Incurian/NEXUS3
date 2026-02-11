"""Init commands for setting up NEXUS3 configuration directories.

This module provides:
- `--init-global`: Initialize ~/.nexus3/ with default configuration
- `/init`: Initialize ./.nexus3/ for the current project

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

# Template files
NEXUS_MD_TEMPLATE = """# Project Configuration

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
    """Initialize a local ./.nexus3/ configuration directory.

    Creates project-specific configuration files with templates.

    Args:
        cwd: Directory to initialize in. Defaults to Path.cwd().
        force: If True, overwrite existing files. If False, skip if directory exists.
        filename: Name of the instruction file to create (default: AGENTS.md).

    Returns:
        Tuple of (success, message).
    """
    target_dir = (cwd or Path.cwd()) / ".nexus3"

    if target_dir.exists() and not force:
        return False, (
            f"Directory already exists: {target_dir}\n"
            "Use /init --force to overwrite."
        )

    try:
        secure_mkdir(target_dir)

        # P1.8 SECURITY: Use _safe_write_text to prevent symlink attacks
        # Create instruction file template
        _safe_write_text(target_dir / filename, NEXUS_MD_TEMPLATE)

        # Create config.json template
        _safe_write_text(target_dir / "config.json", CONFIG_JSON_TEMPLATE)

        # Create empty mcp.json
        _safe_write_text(target_dir / "mcp.json", MCP_JSON_TEMPLATE)

        return True, f"Initialized project configuration at {target_dir}"

    except InitSymlinkError as e:
        return False, f"Security error: {e}"
    except OSError as e:
        return False, f"Failed to create project config: {e}"
