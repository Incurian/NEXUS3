"""ClipboardManager - coordinates storage, permissions, and scope resolution."""
from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

from nexus3.clipboard.storage import ClipboardStorage
from nexus3.clipboard.types import (
    CLIPBOARD_PRESETS,
    MAX_ENTRY_SIZE_BYTES,
    WARN_ENTRY_SIZE_BYTES,
    ClipboardEntry,
    ClipboardPermissions,
    ClipboardScope,
)

if TYPE_CHECKING:
    pass


class ClipboardManager:
    """Manages clipboard operations across all scopes with permission enforcement."""

    def __init__(
        self,
        agent_id: str,
        cwd: Path,
        permissions: ClipboardPermissions | None = None,
        home_dir: Path | None = None,
    ) -> None:
        """Initialize clipboard manager.

        Args:
            agent_id: Current agent's ID (for tracking modifications)
            cwd: Current working directory (for project scope resolution)
            permissions: Clipboard permissions (defaults to sandboxed)
            home_dir: Home directory override (for testing)
        """
        self._agent_id = agent_id
        self._cwd = cwd
        self._permissions = permissions or CLIPBOARD_PRESETS["sandboxed"]
        # NOTE: For system-scope clipboard paths, prefer nexus3.core.constants.get_nexus_dir()
        # rather than hardcoding Path.home() / ".nexus3". Home override remains useful for tests.
        self._home_dir = home_dir or Path.home()

        # Agent scope: in-memory only
        self._agent_clipboard: dict[str, ClipboardEntry] = {}

        # Lazy-loaded persistent storage
        self._project_storage: ClipboardStorage | None = None
        self._system_storage: ClipboardStorage | None = None

    def _get_project_storage(self) -> ClipboardStorage:
        """Get or create project-scope storage."""
        if self._project_storage is None:
            db_path = self._cwd / ".nexus3" / "clipboard.db"
            self._project_storage = ClipboardStorage(db_path, ClipboardScope.PROJECT)
        return self._project_storage

    def _get_system_storage(self) -> ClipboardStorage:
        """Get or create system-scope storage."""
        if self._system_storage is None:
            db_path = self._home_dir / ".nexus3" / "clipboard.db"
            self._system_storage = ClipboardStorage(db_path, ClipboardScope.SYSTEM)
        return self._system_storage

    def _check_read_permission(self, scope: ClipboardScope) -> None:
        """Raise PermissionError if read not allowed for scope."""
        if not self._permissions.can_read(scope):
            raise PermissionError(f"No read permission for {scope.value} clipboard")

    def _check_write_permission(self, scope: ClipboardScope) -> None:
        """Raise PermissionError if write not allowed for scope."""
        if not self._permissions.can_write(scope):
            raise PermissionError(f"No write permission for {scope.value} clipboard")

    def _validate_size(self, content: str) -> str | None:
        """Validate content size. Returns warning message or None."""
        size = len(content.encode("utf-8"))
        if size > MAX_ENTRY_SIZE_BYTES:
            raise ValueError(
                f"Content size ({size:,} bytes) exceeds maximum ({MAX_ENTRY_SIZE_BYTES:,} bytes)"
            )
        if size > WARN_ENTRY_SIZE_BYTES:
            return f"Warning: Large clipboard entry ({size:,} bytes)"
        return None

    # --- Core Operations ---

    def copy(
        self,
        key: str,
        content: str,
        scope: ClipboardScope = ClipboardScope.AGENT,
        *,
        short_description: str | None = None,
        source_path: str | None = None,
        source_lines: str | None = None,
        tags: list[str] | None = None,
        ttl_seconds: int | None = None,
    ) -> tuple[ClipboardEntry, str | None]:
        """Copy content to clipboard.

        Args:
            key: Clipboard key name
            content: Content to store
            scope: Clipboard scope (agent/project/system)
            short_description: Optional description
            source_path: Original file path
            source_lines: Line range (e.g., "50-150")
            tags: Optional tags for organizing entries
            ttl_seconds: Optional TTL in seconds (None = permanent)

        Returns:
            Tuple of (created entry, warning message or None)

        Raises:
            PermissionError: If scope not accessible
            ValueError: If key already exists or content too large
        """
        self._check_write_permission(scope)
        warning = self._validate_size(content)

        # Apply scope-specific default TTL if not specified
        if ttl_seconds is None:
            ttl_seconds = self._get_ttl_for_scope(scope)

        entry = ClipboardEntry.from_content(
            key=key,
            scope=scope,
            content=content,
            short_description=short_description,
            source_path=source_path,
            source_lines=source_lines,
            agent_id=self._agent_id,
            ttl_seconds=ttl_seconds,
            tags=tags,
        )

        if scope == ClipboardScope.AGENT:
            if key in self._agent_clipboard:
                raise ValueError(
                    f"Key '{key}' already exists in agent scope. "
                    "Use clipboard_update to modify or choose a different key."
                )
            self._agent_clipboard[key] = entry
        elif scope == ClipboardScope.PROJECT:
            try:
                self._get_project_storage().create(entry)
            except ValueError as e:
                raise ValueError(
                    f"Key '{key}' already exists in project scope. "
                    "Use clipboard_update to modify or choose a different key."
                ) from e
        elif scope == ClipboardScope.SYSTEM:
            try:
                self._get_system_storage().create(entry)
            except ValueError as e:
                raise ValueError(
                    f"Key '{key}' already exists in system scope. "
                    "Use clipboard_update to modify or choose a different key."
                ) from e

        return entry, warning

    def get(
        self,
        key: str,
        scope: ClipboardScope | None = None,
    ) -> ClipboardEntry | None:
        """Get entry by key.

        Args:
            key: Clipboard key
            scope: Specific scope to search, or None to search agent->project->system

        Returns:
            Entry if found, None otherwise

        Raises:
            PermissionError: If scope not accessible
        """
        if scope is not None:
            # Search specific scope
            self._check_read_permission(scope)
            return self._get_from_scope(key, scope)

        # Search all accessible scopes in order: agent -> project -> system
        for s in [ClipboardScope.AGENT, ClipboardScope.PROJECT, ClipboardScope.SYSTEM]:
            if self._permissions.can_read(s):
                entry = self._get_from_scope(key, s)
                if entry is not None:
                    return entry
        return None

    def _get_from_scope(self, key: str, scope: ClipboardScope) -> ClipboardEntry | None:
        """Get entry from specific scope (no permission check)."""
        if scope == ClipboardScope.AGENT:
            return self._agent_clipboard.get(key)
        elif scope == ClipboardScope.PROJECT:
            return self._get_project_storage().get(key)
        elif scope == ClipboardScope.SYSTEM:
            return self._get_system_storage().get(key)
        return None

    def update(
        self,
        key: str,
        scope: ClipboardScope,
        *,
        content: str | None = None,
        short_description: str | None = None,
        source_path: str | None = None,
        source_lines: str | None = None,
        new_key: str | None = None,
        ttl_seconds: int | None = None,
    ) -> tuple[ClipboardEntry, str | None]:
        """Update existing entry.

        Returns:
            Tuple of (updated entry, warning message or None)
        """
        self._check_write_permission(scope)

        warning = None
        if content is not None:
            warning = self._validate_size(content)

        if scope == ClipboardScope.AGENT:
            if key not in self._agent_clipboard:
                raise KeyError(f"Key '{key}' not found in agent scope")
            if new_key is not None and new_key != key and new_key in self._agent_clipboard:
                raise ValueError(f"Key '{new_key}' already exists in agent scope")

            entry = self._agent_clipboard[key]
            if content is not None:
                entry.content = content
                entry.line_count = content.count("\n") + (
                    1 if content and not content.endswith("\n") else 0
                )
                entry.byte_count = len(content.encode("utf-8"))
            if short_description is not None:
                entry.short_description = short_description
            if source_path is not None:
                entry.source_path = source_path
            if source_lines is not None:
                entry.source_lines = source_lines
            if ttl_seconds is not None:
                entry.ttl_seconds = ttl_seconds
                entry.expires_at = time.time() + ttl_seconds
            entry.modified_at = time.time()
            entry.modified_by_agent = self._agent_id

            if new_key is not None and new_key != key:
                entry.key = new_key
                del self._agent_clipboard[key]
                self._agent_clipboard[new_key] = entry

            return entry, warning

        elif scope == ClipboardScope.PROJECT:
            entry = self._get_project_storage().update(
                key,
                content=content,
                short_description=short_description,
                source_path=source_path,
                source_lines=source_lines,
                new_key=new_key,
                agent_id=self._agent_id,
                ttl_seconds=ttl_seconds,
            )
            return entry, warning

        elif scope == ClipboardScope.SYSTEM:
            entry = self._get_system_storage().update(
                key,
                content=content,
                short_description=short_description,
                source_path=source_path,
                source_lines=source_lines,
                new_key=new_key,
                agent_id=self._agent_id,
                ttl_seconds=ttl_seconds,
            )
            return entry, warning

        raise ValueError(f"Unknown scope: {scope}")

    def delete(self, key: str, scope: ClipboardScope) -> bool:
        """Delete entry. Returns True if deleted."""
        self._check_write_permission(scope)

        if scope == ClipboardScope.AGENT:
            if key in self._agent_clipboard:
                del self._agent_clipboard[key]
                return True
            return False
        elif scope == ClipboardScope.PROJECT:
            return self._get_project_storage().delete(key)
        elif scope == ClipboardScope.SYSTEM:
            return self._get_system_storage().delete(key)
        return False

    def clear(self, scope: ClipboardScope) -> int:
        """Clear all entries in scope. Returns count deleted."""
        self._check_write_permission(scope)

        if scope == ClipboardScope.AGENT:
            count = len(self._agent_clipboard)
            self._agent_clipboard.clear()
            return count
        elif scope == ClipboardScope.PROJECT:
            return self._get_project_storage().clear()
        elif scope == ClipboardScope.SYSTEM:
            return self._get_system_storage().clear()
        return 0

    def list_entries(
        self,
        scope: ClipboardScope | None = None,
        *,
        tags: list[str] | None = None,
        any_tags: list[str] | None = None,
        include_expired: bool = True,
    ) -> list[ClipboardEntry]:
        """List entries, optionally filtered by scope and tags.

        Args:
            scope: Specific scope, or None for all accessible scopes
            tags: Filter to entries having ALL of these tags (AND logic)
            any_tags: Filter to entries having ANY of these tags (OR logic)
            include_expired: If False, exclude expired entries

        Returns entries sorted by modified_at descending.
        Only includes entries from scopes the agent can read.
        """
        entries: list[ClipboardEntry] = []

        scopes = (
            [scope]
            if scope
            else [ClipboardScope.AGENT, ClipboardScope.PROJECT, ClipboardScope.SYSTEM]
        )

        for s in scopes:
            if not self._permissions.can_read(s):
                continue

            if s == ClipboardScope.AGENT:
                entries.extend(self._agent_clipboard.values())
            elif s == ClipboardScope.PROJECT:
                entries.extend(self._get_project_storage().list_all())
            elif s == ClipboardScope.SYSTEM:
                entries.extend(self._get_system_storage().list_all())

        # Filter by tags (AND logic)
        if tags:
            entries = [e for e in entries if all(t in e.tags for t in tags)]

        # Filter by any_tags (OR logic)
        if any_tags:
            entries = [e for e in entries if any(t in e.tags for t in any_tags)]

        # Filter out expired if requested
        if not include_expired:
            entries = [e for e in entries if not e.is_expired]

        # Sort by modified_at descending
        entries.sort(key=lambda e: e.modified_at, reverse=True)
        return entries

    def close(self) -> None:
        """Close any open database connections."""
        if self._project_storage:
            self._project_storage.close()
        if self._system_storage:
            self._system_storage.close()

    # --- TTL Support ---

    def _get_ttl_for_scope(self, scope: ClipboardScope) -> int | None:
        """Get default TTL for scope from config, or None for permanent."""
        # In implementation, this reads from ClipboardConfig
        # For now, return None (permanent) - will be wired in Phase 5b
        return None

    def count_expired(self, scope: ClipboardScope | None = None) -> int:
        """Count expired entries (does NOT delete them).

        Args:
            scope: Specific scope to check, or None for all accessible scopes

        Returns count of expired entries. Use get_expired() to see them,
        or a future cleanup command with user confirmation to delete.
        """
        now = time.time()
        count = 0

        scopes = (
            [scope]
            if scope
            else [ClipboardScope.AGENT, ClipboardScope.PROJECT, ClipboardScope.SYSTEM]
        )

        for s in scopes:
            if not self._permissions.can_read(s):
                continue

            if s == ClipboardScope.AGENT:
                count += sum(
                    1
                    for e in self._agent_clipboard.values()
                    if e.expires_at is not None and e.expires_at <= now
                )
            elif s == ClipboardScope.PROJECT:
                count += self._get_project_storage().count_expired(now)
            elif s == ClipboardScope.SYSTEM:
                count += self._get_system_storage().count_expired(now)

        return count

    def get_expired(self, scope: ClipboardScope | None = None) -> list[ClipboardEntry]:
        """Get all expired entries for review.

        Args:
            scope: Specific scope to check, or None for all accessible scopes

        Returns list of expired entries. User can review before cleanup.
        """
        now = time.time()
        expired: list[ClipboardEntry] = []

        scopes = (
            [scope]
            if scope
            else [ClipboardScope.AGENT, ClipboardScope.PROJECT, ClipboardScope.SYSTEM]
        )

        for s in scopes:
            if not self._permissions.can_read(s):
                continue

            if s == ClipboardScope.AGENT:
                expired.extend(
                    e
                    for e in self._agent_clipboard.values()
                    if e.expires_at is not None and e.expires_at <= now
                )
            elif s == ClipboardScope.PROJECT:
                expired.extend(self._get_project_storage().get_expired(now))
            elif s == ClipboardScope.SYSTEM:
                expired.extend(self._get_system_storage().get_expired(now))

        return expired

    # --- Search Support ---

    def search(
        self,
        query: str,
        scope: ClipboardScope | None = None,
        search_content: bool = True,
        search_keys: bool = True,
        search_descriptions: bool = True,
        tags: list[str] | None = None,
    ) -> list[ClipboardEntry]:
        """Search clipboard entries.

        Args:
            query: Search string (case-insensitive substring match)
            scope: Specific scope to search, or None for all accessible
            search_content: Search in content
            search_keys: Search in keys
            search_descriptions: Search in descriptions
            tags: Filter by tags (entries must have ALL specified tags)

        Returns:
            Matching entries, sorted by relevance (key match > desc > content)
        """
        entries = self.list_entries(scope)  # Already filters by permission
        query_lower = query.lower()
        results = []

        for entry in entries:
            # Filter by tags first (if specified)
            if tags:
                if not all(t in entry.tags for t in tags):
                    continue

            # Search in specified fields
            matches = False
            if search_keys and query_lower in entry.key.lower():
                matches = True
            elif (
                search_descriptions
                and entry.short_description
                and query_lower in entry.short_description.lower()
            ):
                matches = True
            elif search_content and query_lower in entry.content.lower():
                matches = True

            if matches:
                results.append(entry)

        return results

    # --- Tag Management ---

    def add_tags(
        self, key: str, scope: ClipboardScope, tags: list[str]
    ) -> ClipboardEntry:
        """Add tags to an entry. Creates tags if they don't exist."""
        self._check_write_permission(scope)
        entry = self._get_from_scope(key, scope)
        if entry is None:
            raise KeyError(f"Key '{key}' not found in {scope.value} scope")

        # Add new tags (avoid duplicates)
        new_tags = list(set(entry.tags + tags))
        entry.tags = new_tags
        entry.modified_at = time.time()
        entry.modified_by_agent = self._agent_id

        # Persist if not agent scope
        if scope != ClipboardScope.AGENT:
            storage = (
                self._get_project_storage()
                if scope == ClipboardScope.PROJECT
                else self._get_system_storage()
            )
            storage.set_tags(key, new_tags)

        return entry

    def remove_tags(
        self, key: str, scope: ClipboardScope, tags: list[str]
    ) -> ClipboardEntry:
        """Remove tags from an entry."""
        self._check_write_permission(scope)
        entry = self._get_from_scope(key, scope)
        if entry is None:
            raise KeyError(f"Key '{key}' not found in {scope.value} scope")

        # Remove specified tags
        entry.tags = [t for t in entry.tags if t not in tags]
        entry.modified_at = time.time()
        entry.modified_by_agent = self._agent_id

        # Persist if not agent scope
        if scope != ClipboardScope.AGENT:
            storage = (
                self._get_project_storage()
                if scope == ClipboardScope.PROJECT
                else self._get_system_storage()
            )
            storage.set_tags(key, entry.tags)

        return entry

    def list_tags(self, scope: ClipboardScope | None = None) -> list[str]:
        """List all tags in use across accessible scopes."""
        entries = self.list_entries(scope)
        all_tags: set[str] = set()
        for entry in entries:
            all_tags.update(entry.tags)
        return sorted(all_tags)

    # --- Agent Clipboard Access (for Session Persistence) ---

    def get_agent_entries(self) -> dict[str, ClipboardEntry]:
        """Get all agent-scope entries (for session persistence)."""
        return dict(self._agent_clipboard)

    def restore_agent_entries(self, entries: dict[str, ClipboardEntry]) -> None:
        """Restore agent-scope entries from session persistence."""
        self._agent_clipboard = dict(entries)
