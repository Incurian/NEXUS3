from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nexus3.ide.connection import Diagnostic, EditorInfo

_MAX_IDE_CONTEXT_LENGTH = 800


def format_ide_context(
    ide_name: str,
    open_editors: list[EditorInfo] | None = None,
    diagnostics: list[Diagnostic] | None = None,
    *,
    inject_diagnostics: bool = True,
    inject_open_editors: bool = True,
    max_diagnostics: int = 50,
) -> str | None:
    """Format IDE state for system prompt injection.

    Returns formatted string (max 800 chars), or None if nothing to inject.
    """
    lines = [f"IDE connected: {ide_name}"]

    if inject_open_editors and open_editors:
        names = [Path(e.file_path).name for e in open_editors[:10]]
        lines.append(f"  Open tabs: {', '.join(names)}")

    if inject_diagnostics and diagnostics:
        errors = [d for d in diagnostics if d.severity == "error"]
        warnings = [d for d in diagnostics if d.severity == "warning"]
        if errors or warnings:
            parts = []
            if errors:
                parts.append(f"{len(errors)} errors")
            if warnings:
                parts.append(f"{len(warnings)} warnings")
            lines.append(f"  Diagnostics: {', '.join(parts)}")
            for d in errors[:max_diagnostics]:
                lines.append(f"    {Path(d.file_path).name}:{d.line}: {d.message}")

    if len(lines) <= 1:
        return None

    result = "\n".join(lines)
    if len(result) > _MAX_IDE_CONTEXT_LENGTH:
        result = result[: _MAX_IDE_CONTEXT_LENGTH - 3] + "..."
    return result
