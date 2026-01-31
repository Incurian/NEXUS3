"""Clipboard system types and dataclasses."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


class ClipboardScope(Enum):
    """Clipboard entry scope levels."""

    AGENT = "agent"  # In-memory, session-only
    PROJECT = "project"  # <agent_cwd>/.nexus3/clipboard.db
    SYSTEM = "system"  # ~/.nexus3/clipboard.db


class InsertionMode(Enum):
    """How to insert clipboard content into target file."""

    AFTER_LINE = "after_line"
    BEFORE_LINE = "before_line"
    REPLACE_LINES = "replace_lines"
    AT_MARKER_REPLACE = "at_marker_replace"
    AT_MARKER_AFTER = "at_marker_after"
    AT_MARKER_BEFORE = "at_marker_before"
    APPEND = "append"
    PREPEND = "prepend"


@dataclass
class ClipboardTag:
    """A tag for organizing clipboard entries."""

    id: int
    name: str
    description: str | None = None
    created_at: float = 0.0


@dataclass
class ClipboardEntry:
    """A single clipboard entry."""

    key: str
    scope: ClipboardScope
    content: str
    line_count: int
    byte_count: int
    short_description: str | None = None
    source_path: str | None = None  # Original file path
    source_lines: str | None = None  # "50-150" or None
    created_at: float = 0.0  # Unix timestamp
    modified_at: float = 0.0  # Unix timestamp
    created_by_agent: str | None = None
    modified_by_agent: str | None = None
    expires_at: float | None = None  # Unix timestamp for TTL expiry (None = permanent)
    ttl_seconds: int | None = None  # TTL in seconds (informational)
    tags: list[str] = field(default_factory=list)  # Tag names

    @classmethod
    def from_content(
        cls,
        key: str,
        scope: ClipboardScope,
        content: str,
        *,
        short_description: str | None = None,
        source_path: str | None = None,
        source_lines: str | None = None,
        agent_id: str | None = None,
        ttl_seconds: int | None = None,
        tags: list[str] | None = None,
    ) -> ClipboardEntry:
        """Create entry from content, computing line/byte counts."""
        import time

        now = time.time()
        expires_at = now + ttl_seconds if ttl_seconds is not None else None
        return cls(
            key=key,
            scope=scope,
            content=content,
            line_count=content.count("\n")
            + (1 if content and not content.endswith("\n") else 0),
            byte_count=len(content.encode("utf-8")),
            short_description=short_description,
            source_path=source_path,
            source_lines=source_lines,
            created_at=now,
            modified_at=now,
            created_by_agent=agent_id,
            modified_by_agent=agent_id,
            expires_at=expires_at,
            ttl_seconds=ttl_seconds,
            tags=tags or [],
        )

    @property
    def is_expired(self) -> bool:
        """Check if this entry has expired (TTL exceeded)."""
        if self.expires_at is None:
            return False
        import time

        return time.time() >= self.expires_at


@dataclass
class ClipboardPermissions:
    """Clipboard scope access permissions."""

    agent_scope: bool = True  # Can use agent-scoped clipboard
    project_read: bool = False  # Can read from project clipboard
    project_write: bool = False  # Can write to project clipboard
    system_read: bool = False  # Can read from system clipboard
    system_write: bool = False  # Can write to system clipboard

    def can_read(self, scope: ClipboardScope) -> bool:
        """Check if this permission set allows reading from scope."""
        if scope == ClipboardScope.AGENT:
            return self.agent_scope
        elif scope == ClipboardScope.PROJECT:
            return self.project_read
        elif scope == ClipboardScope.SYSTEM:
            return self.system_read
        return False

    def can_write(self, scope: ClipboardScope) -> bool:
        """Check if this permission set allows writing to scope."""
        if scope == ClipboardScope.AGENT:
            return self.agent_scope
        elif scope == ClipboardScope.PROJECT:
            return self.project_write
        elif scope == ClipboardScope.SYSTEM:
            return self.system_write
        return False


# Preset permission configurations
CLIPBOARD_PRESETS: dict[str, ClipboardPermissions] = {
    "yolo": ClipboardPermissions(
        agent_scope=True,
        project_read=True,
        project_write=True,
        system_read=True,
        system_write=True,
    ),
    "trusted": ClipboardPermissions(
        agent_scope=True,
        project_read=True,
        project_write=True,
        system_read=True,
        system_write=False,  # Can read system, not write
    ),
    "sandboxed": ClipboardPermissions(
        agent_scope=True,
        project_read=False,
        project_write=False,
        system_read=False,
        system_write=False,
    ),
}
# Note: This plan assumes the permission presets are `yolo`, `trusted`, and `sandboxed`.
# If legacy preset names exist (e.g. "worker"), treat them as aliases for sandboxed
# for clipboard purposes.


# Size limits
MAX_ENTRY_SIZE_BYTES = 1 * 1024 * 1024  # 1 MB hard limit
WARN_ENTRY_SIZE_BYTES = 100 * 1024  # 100 KB warning threshold
