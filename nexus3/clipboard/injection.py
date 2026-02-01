"""Context injection for clipboard entries."""
from __future__ import annotations

from typing import TYPE_CHECKING

from nexus3.clipboard.types import ClipboardEntry

if TYPE_CHECKING:
    from nexus3.clipboard.manager import ClipboardManager


def format_clipboard_context(
    manager: ClipboardManager,
    max_entries: int = 10,
    show_source: bool = True,
) -> str | None:
    """Format clipboard entries for system prompt injection.

    Args:
        manager: ClipboardManager to list entries from
        max_entries: Maximum entries to show
        show_source: Include source path/lines info

    Returns:
        Formatted markdown string, or None if no entries
    """
    entries = manager.list_entries()
    if not entries:
        return None

    entries = entries[:max_entries]

    lines = [
        "## Available Clipboard Entries",
        "",
        "| Key | Scope | Lines | Description |",
        "|-----|-------|-------|-------------|",
    ]

    for entry in entries:
        desc = entry.short_description or ""
        if not desc and show_source and entry.source_path:
            desc = f"from {entry.source_path}"
            if entry.source_lines:
                desc += f":{entry.source_lines}"

        lines.append(
            f"| {entry.key} | {entry.scope.value} | {entry.line_count} | {desc} |"
        )

    lines.extend([
        "",
        'Use `paste(key="...")` to insert content. Use `clipboard_list(verbose=True)` to preview.',
    ])

    # Add note about expired entries if any
    expired_count = manager.count_expired()
    if expired_count > 0:
        lines.extend([
            "",
            f"*Note: {expired_count} expired entries pending cleanup. Use clipboard_list to review.*",
        ])

    return "\n".join(lines)


def format_time_ago(timestamp: float) -> str:
    """Format timestamp as relative time (e.g., '2m ago', '3d ago')."""
    import time

    delta = time.time() - timestamp
    if delta < 60:
        return "just now"
    elif delta < 3600:
        return f"{int(delta / 60)}m ago"
    elif delta < 86400:
        return f"{int(delta / 3600)}h ago"
    else:
        return f"{int(delta / 86400)}d ago"


def format_entry_detail(entry: ClipboardEntry, verbose: bool = False) -> str:
    """Format a single entry for clipboard_list output."""
    lines = []

    # Header: [scope] key (lines, size) - description
    size_str = _format_size(entry.byte_count)
    header = f"[{entry.scope.value}] {entry.key} ({entry.line_count} lines, {size_str})"
    if entry.short_description:
        header += f' - "{entry.short_description}"'
    lines.append(header)

    # Source and modification info
    meta_parts = []
    if entry.source_path:
        source = f"Source: {entry.source_path}"
        if entry.source_lines:
            source += f":{entry.source_lines}"
        meta_parts.append(source)

    meta_parts.append(f"Modified: {format_time_ago(entry.modified_at)}")
    if entry.modified_by_agent:
        meta_parts[-1] += f" by {entry.modified_by_agent}"

    lines.append("        " + " | ".join(meta_parts))

    # Tags if present
    if entry.tags:
        lines.append("        Tags: " + ", ".join(entry.tags))

    # Expiry info if set
    if entry.expires_at is not None:
        if entry.is_expired:
            lines.append("        [EXPIRED]")
        else:
            import time
            remaining = entry.expires_at - time.time()
            if remaining < 3600:
                lines.append(f"        Expires in: {int(remaining / 60)}m")
            else:
                lines.append(f"        Expires in: {int(remaining / 3600)}h")

    # Content preview if verbose
    if verbose:
        content_lines = entry.content.splitlines()
        preview_lines = []
        if len(content_lines) <= 6:
            preview_lines = content_lines
        else:
            preview_lines = content_lines[:3] + ["..."] + content_lines[-3:]

        lines.append("        ---")
        for pl in preview_lines:
            # Truncate long lines
            if len(pl) > 80:
                pl = pl[:77] + "..."
            lines.append("        " + pl)

    return "\n".join(lines)


def _format_size(byte_count: int) -> str:
    """Format byte count as human-readable size."""
    if byte_count < 1024:
        return f"{byte_count}B"
    elif byte_count < 1024 * 1024:
        return f"{byte_count / 1024:.1f}KB"
    else:
        return f"{byte_count / (1024 * 1024):.1f}MB"
