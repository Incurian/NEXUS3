"""Tool path semantics for confirmation and allowance logic.

Defines which arguments represent read paths vs write paths for each tool.
This enables:
1. Confirmation based on write targets (what's actually dangerous)
2. Allowances applied to write paths only
3. Display-friendly path for confirmation UI

Fix 1.2: Multi-Path Confirmation with ToolPathSemantics (C2)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ToolPathSemantics:
    """Defines which paths are read vs write for confirmation/allowance logic.

    Attributes:
        read_keys: Argument names that represent read-only paths.
        write_keys: Argument names that represent paths that will be modified.
        display_key: Which path to show in confirmation UI (typically the write target).
    """
    read_keys: tuple[str, ...] = field(default_factory=tuple)
    write_keys: tuple[str, ...] = field(default_factory=tuple)
    display_key: str | None = None


# Registry of tool path semantics
# Tools not listed here get sensible defaults (path as read+write)
TOOL_PATH_SEMANTICS: dict[str, ToolPathSemantics] = {
    # Write-only tools (no read component)
    "write_file": ToolPathSemantics(
        write_keys=("path",),
        display_key="path"
    ),
    "mkdir": ToolPathSemantics(
        write_keys=("path",),
        display_key="path"
    ),

    # Read+write tools (modify existing files)
    "edit_file": ToolPathSemantics(
        read_keys=("path",),
        write_keys=("path",),
        display_key="path"
    ),
    "append_file": ToolPathSemantics(
        read_keys=("path",),
        write_keys=("path",),
        display_key="path"
    ),
    "regex_replace": ToolPathSemantics(
        read_keys=("path",),
        write_keys=("path",),
        display_key="path"
    ),

    # Multi-path tools (source=read, destination=write)
    "copy_file": ToolPathSemantics(
        read_keys=("source",),
        write_keys=("destination",),
        display_key="destination"  # Confirmation shows write target
    ),
    "rename": ToolPathSemantics(
        read_keys=("source",),
        write_keys=("destination",),
        display_key="destination"
    ),

    # Read-only tools (no write component)
    "read_file": ToolPathSemantics(read_keys=("path",)),
    "tail": ToolPathSemantics(read_keys=("path",)),
    "file_info": ToolPathSemantics(read_keys=("path",)),
    "list_directory": ToolPathSemantics(read_keys=("path",)),
    "glob": ToolPathSemantics(read_keys=("path",)),
    "grep": ToolPathSemantics(read_keys=("path",)),
}


def get_semantics(tool_name: str) -> ToolPathSemantics:
    """Get path semantics for a tool.

    Returns semantics from registry if defined, otherwise defaults to treating
    'path' as both read and write target (safe default for unknown tools).

    Args:
        tool_name: Name of the tool.

    Returns:
        ToolPathSemantics for the tool.
    """
    return TOOL_PATH_SEMANTICS.get(
        tool_name,
        ToolPathSemantics(
            read_keys=("path",),
            write_keys=("path",),
            display_key="path"
        )
    )


def extract_write_paths(tool_name: str, args: dict[str, Any]) -> list[Path]:
    """Extract paths that will be written to.

    For multi-path tools like copy_file and rename, this returns the destination
    paths (what will be modified), not the source paths.

    Args:
        tool_name: Name of the tool.
        args: Tool call arguments.

    Returns:
        List of Path objects for write targets. May be empty for read-only tools.
    """
    semantics = get_semantics(tool_name)
    paths: list[Path] = []

    for key in semantics.write_keys:
        if key in args and args[key]:
            paths.append(Path(args[key]))

    return paths


def extract_display_path(tool_name: str, args: dict[str, Any]) -> Path | None:
    """Extract the path to show in confirmation UI.

    For multi-path tools, this typically returns the write target (destination)
    since that's what the user needs to approve.

    Args:
        tool_name: Name of the tool.
        args: Tool call arguments.

    Returns:
        Path to display in confirmation, or None if not applicable.
    """
    semantics = get_semantics(tool_name)
    key = semantics.display_key

    if key and key in args and args[key]:
        return Path(args[key])

    return None
