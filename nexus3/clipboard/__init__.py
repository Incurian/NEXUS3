"""Clipboard system for NEXUS3 agents."""
from nexus3.clipboard.injection import format_clipboard_context, format_entry_detail
from nexus3.clipboard.manager import ClipboardManager
from nexus3.clipboard.storage import ClipboardStorage
from nexus3.clipboard.types import (
    CLIPBOARD_PRESETS,
    ClipboardEntry,
    ClipboardPermissions,
    ClipboardScope,
    ClipboardTag,
    InsertionMode,
    MAX_ENTRY_SIZE_BYTES,
    WARN_ENTRY_SIZE_BYTES,
)

__all__ = [
    "ClipboardManager",
    "ClipboardStorage",
    "ClipboardEntry",
    "ClipboardPermissions",
    "ClipboardScope",
    "ClipboardTag",
    "InsertionMode",
    "CLIPBOARD_PRESETS",
    "MAX_ENTRY_SIZE_BYTES",
    "WARN_ENTRY_SIZE_BYTES",
    "format_clipboard_context",
    "format_entry_detail",
]
