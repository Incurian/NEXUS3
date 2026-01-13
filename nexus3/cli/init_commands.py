"""Init commands for setting up NEXUS3 configuration directories.

This module provides:
- `--init-global`: Initialize ~/.nexus3/ with default configuration
- `/init`: Initialize ./.nexus3/ for the current project
"""

from pathlib import Path

import nexus3

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
  "provider": {
    "_comment": "Override model settings for this project"
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
    return Path(nexus3.__file__).parent / "defaults"


def init_global(force: bool = False) -> tuple[bool, str]:
    """Initialize the global ~/.nexus3/ configuration directory.

    Copies default configuration files to the user's home directory.

    Args:
        force: If True, overwrite existing files. If False, skip if directory exists.

    Returns:
        Tuple of (success, message).
    """
    global_dir = Path.home() / ".nexus3"
    defaults_dir = get_defaults_dir()

    if global_dir.exists() and not force:
        return False, f"Directory already exists: {global_dir}\nUse --force to overwrite."

    try:
        global_dir.mkdir(parents=True, exist_ok=True)

        # Copy NEXUS.md from defaults if it exists, otherwise use minimal
        default_nexus = defaults_dir / "NEXUS.md"
        if default_nexus.exists():
            (global_dir / "NEXUS.md").write_text(
                default_nexus.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        else:
            (global_dir / "NEXUS.md").write_text(
                "# Personal Configuration\n\nYou are NEXUS3, an AI-powered CLI assistant.\n",
                encoding="utf-8",
            )

        # Copy config.json from defaults if it exists
        default_config = defaults_dir / "config.json"
        if default_config.exists():
            (global_dir / "config.json").write_text(
                default_config.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        else:
            (global_dir / "config.json").write_text("{}", encoding="utf-8")

        # Create empty mcp.json
        (global_dir / "mcp.json").write_text(MCP_JSON_TEMPLATE, encoding="utf-8")

        # Create sessions directory
        (global_dir / "sessions").mkdir(exist_ok=True)

        return True, f"Initialized global configuration at {global_dir}"

    except OSError as e:
        return False, f"Failed to create global config: {e}"


def init_local(cwd: Path | None = None, force: bool = False) -> tuple[bool, str]:
    """Initialize a local ./.nexus3/ configuration directory.

    Creates project-specific configuration files with templates.

    Args:
        cwd: Directory to initialize in. Defaults to Path.cwd().
        force: If True, overwrite existing files. If False, skip if directory exists.

    Returns:
        Tuple of (success, message).
    """
    target_dir = (cwd or Path.cwd()) / ".nexus3"

    if target_dir.exists() and not force:
        return False, f"Directory already exists: {target_dir}\nUse --force to overwrite."

    try:
        target_dir.mkdir(parents=True, exist_ok=True)

        # Create NEXUS.md template
        (target_dir / "NEXUS.md").write_text(NEXUS_MD_TEMPLATE, encoding="utf-8")

        # Create config.json template
        (target_dir / "config.json").write_text(CONFIG_JSON_TEMPLATE, encoding="utf-8")

        # Create empty mcp.json
        (target_dir / "mcp.json").write_text(MCP_JSON_TEMPLATE, encoding="utf-8")

        return True, f"Initialized project configuration at {target_dir}"

    except OSError as e:
        return False, f"Failed to create project config: {e}"
