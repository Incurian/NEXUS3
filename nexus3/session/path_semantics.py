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
    "write_file": ToolPathSemantics(write_keys=("path",), display_key="path"),
    "mkdir": ToolPathSemantics(write_keys=("path",), display_key="path"),
    # Read+write tools (modify existing files)
    "edit_file": ToolPathSemantics(read_keys=("path",), write_keys=("path",), display_key="path"),
    "edit_lines": ToolPathSemantics(read_keys=("path",), write_keys=("path",), display_key="path"),
    "append_file": ToolPathSemantics(read_keys=("path",), write_keys=("path",), display_key="path"),
    "regex_replace": ToolPathSemantics(
        read_keys=("path",), write_keys=("path",), display_key="path"
    ),
    "patch": ToolPathSemantics(
        read_keys=("path", "target", "diff_file"), write_keys=("path", "target"), display_key="path"
    ),
    "copy": ToolPathSemantics(read_keys=("source",)),
    "cut": ToolPathSemantics(read_keys=("source",), write_keys=("source",), display_key="source"),
    "paste": ToolPathSemantics(read_keys=("target",), write_keys=("target",), display_key="target"),
    "clipboard_export": ToolPathSemantics(write_keys=("path",), display_key="path"),
    "clipboard_import": ToolPathSemantics(read_keys=("path",)),
    "clipboard_update": ToolPathSemantics(read_keys=("source",)),
    "gitlab_artifact": ToolPathSemantics(write_keys=("output_path",), display_key="output_path"),
    "concat_files": ToolPathSemantics(read_keys=("path",)),
    # Multi-path tools (source=read, destination=write)
    "copy_file": ToolPathSemantics(
        read_keys=("source",),
        write_keys=("destination",),
        display_key="destination",  # Confirmation shows write target
    ),
    "rename": ToolPathSemantics(
        read_keys=("source",), write_keys=("destination",), display_key="destination"
    ),
    # Read-only tools (no write component)
    "read_file": ToolPathSemantics(read_keys=("path",)),
    "tail": ToolPathSemantics(read_keys=("path",)),
    "file_info": ToolPathSemantics(read_keys=("path",)),
    "list_directory": ToolPathSemantics(read_keys=("path",)),
    "glob": ToolPathSemantics(read_keys=("path",)),
    "search_text": ToolPathSemantics(read_keys=("path",)),
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
        tool_name, ToolPathSemantics(read_keys=("path",), write_keys=("path",), display_key="path")
    )


def has_explicit_semantics(tool_name: str) -> bool:
    """Return True when a tool has a registered semantics entry."""
    return tool_name in TOOL_PATH_SEMANTICS


def _extract_paths_for_keys(args: dict[str, Any], keys: tuple[str, ...]) -> list[Path]:
    """Extract unique raw path arguments in key order."""
    paths: list[Path] = []
    seen: set[str] = set()

    for key in keys:
        raw_value = args.get(key)
        if not raw_value:
            continue
        if not isinstance(raw_value, str):
            continue
        if raw_value in seen:
            continue
        seen.add(raw_value)
        paths.append(Path(raw_value))

    return paths


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
    return _extract_paths_for_keys(args, semantics.write_keys)


def extract_tool_paths(tool_name: str, args: dict[str, Any]) -> list[Path]:
    """Extract all unique read/write paths for permission checks."""
    semantics = get_semantics(tool_name)
    ordered_keys = semantics.read_keys + tuple(
        key for key in semantics.write_keys if key not in semantics.read_keys
    )
    return _extract_paths_for_keys(args, ordered_keys)


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

    write_paths = extract_write_paths(tool_name, args)
    if write_paths:
        return write_paths[0]

    return None
