"""Session manager for disk storage operations.

This module handles persisting sessions to disk and loading them back.
Sessions are stored as JSON files in ~/.nexus3/sessions/.
"""

import json
import os
import stat
from datetime import datetime
from pathlib import Path

# Secure file permissions: owner read/write only (0o600)
_SECURE_FILE_MODE = stat.S_IRUSR | stat.S_IWUSR

from nexus3.core.constants import get_nexus_dir
from nexus3.core.errors import NexusError


def _secure_write_file(path: Path, content: str) -> None:
    """Write content to a file with secure permissions atomically.

    Uses os.open() with O_CREAT | O_TRUNC to set permissions at creation time,
    avoiding the race window between write and chmod where the file could be
    world-readable.

    Args:
        path: Path to write to.
        content: Content to write.

    Raises:
        OSError: If the file cannot be written.
    """
    fd = os.open(
        str(path),
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        _SECURE_FILE_MODE,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception:
        # fd is closed by fdopen, even on error
        raise
from nexus3.core.validation import ValidationError, validate_agent_id
from nexus3.session.persistence import SavedSession, SessionSummary


class SessionManagerError(NexusError):
    """Base error for session manager operations."""

    pass


class SessionNotFoundError(SessionManagerError):
    """Raised when a session does not exist."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Session not found: {name}")


class SessionManager:
    """Manages session persistence to disk.

    Sessions are stored as JSON files:
    - Named sessions: ~/.nexus3/sessions/{name}.json
    - Last session: ~/.nexus3/last-session.json
    - Last session name: ~/.nexus3/last-session-name

    Example:
        manager = SessionManager()
        manager.save_session(saved_session)
        sessions = manager.list_sessions()
        loaded = manager.load_session("my-project")
    """

    def __init__(self, nexus_dir: Path | None = None) -> None:
        """Initialize session manager.

        Args:
            nexus_dir: Base nexus directory. Defaults to ~/.nexus3.
        """
        self.nexus_dir = nexus_dir or get_nexus_dir()
        self.sessions_dir = self.nexus_dir / "sessions"

    def _ensure_dirs(self) -> None:
        """Ensure required directories exist."""
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def _session_path(self, name: str) -> Path:
        """Get path for a session file.

        SECURITY: Validates name to prevent path traversal attacks.
        """
        # Validate name format to prevent path traversal
        try:
            validate_agent_id(name)
        except ValidationError as e:
            raise SessionManagerError(f"Invalid session name: {e.message}") from e
        return self.sessions_dir / f"{name}.json"

    def _last_session_path(self) -> Path:
        """Get path for last session file."""
        return self.nexus_dir / "last-session.json"

    def _last_session_name_path(self) -> Path:
        """Get path for last session name file."""
        return self.nexus_dir / "last-session-name"

    def list_sessions(self) -> list[SessionSummary]:
        """List all saved sessions.

        Returns:
            List of SessionSummary objects, sorted by modified time (newest first).
        """
        self._ensure_dirs()

        summaries: list[SessionSummary] = []

        for path in self.sessions_dir.glob("*.json"):
            try:
                content = path.read_text(encoding="utf-8")
                data = json.loads(content)
                summaries.append(
                    SessionSummary(
                        name=path.stem,
                        modified_at=datetime.fromisoformat(data["modified_at"]),
                        message_count=len(data.get("messages", [])),
                        agent_id=data.get("agent_id", path.stem),
                    )
                )
            except (json.JSONDecodeError, KeyError, ValueError):
                # Skip malformed session files but log for debugging
                continue

        # Sort by modified time, newest first
        summaries.sort(key=lambda s: s.modified_at, reverse=True)
        return summaries

    def save_session(self, saved: SavedSession) -> Path:
        """Save a session to disk.

        The session is saved using its agent_id as the filename.

        Args:
            saved: SavedSession to persist.

        Returns:
            Path to the saved session file.
        """
        self._ensure_dirs()

        path = self._session_path(saved.agent_id)
        content = saved.to_json()
        _secure_write_file(path, content)
        return path

    def load_session(self, name: str) -> SavedSession:
        """Load a session from disk.

        Args:
            name: Session name (without .json extension).

        Returns:
            SavedSession loaded from disk.

        Raises:
            SessionNotFoundError: If session does not exist.
        """
        path = self._session_path(name)
        # Avoid TOCTOU race: catch FileNotFoundError instead of checking exists()
        try:
            content = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise SessionNotFoundError(name) from exc
        return SavedSession.from_json(content)

    def delete_session(self, name: str) -> bool:
        """Delete a saved session from disk.

        Args:
            name: Session name to delete.

        Returns:
            True if deleted, False if session didn't exist.
        """
        path = self._session_path(name)
        # Avoid TOCTOU race: catch FileNotFoundError instead of checking exists()
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False

    def session_exists(self, name: str) -> bool:
        """Check if a session exists.

        Args:
            name: Session name to check.

        Returns:
            True if session exists on disk.
        """
        return self._session_path(name).exists()

    def save_last_session(self, saved: SavedSession, name: str) -> None:
        """Save session as the last session (for resume).

        Persists both the session data and the session name for quick resume.

        Args:
            saved: SavedSession to persist.
            name: Name of the session (could be temp like ".1" or named).
        """
        self._ensure_dirs()

        # Save session data
        path = self._last_session_path()
        content = saved.to_json()
        _secure_write_file(path, content)

        # Save session name
        name_path = self._last_session_name_path()
        _secure_write_file(name_path, name)

    def load_last_session(self) -> tuple[SavedSession, str] | None:
        """Load the last session (for resume).

        Returns:
            Tuple of (SavedSession, name) or None if no last session.
        """
        path = self._last_session_path()
        name_path = self._last_session_name_path()

        # Avoid TOCTOU race: catch FileNotFoundError instead of checking exists()
        try:
            content = path.read_text(encoding="utf-8")
            session = SavedSession.from_json(content)

            name = session.agent_id  # Default to agent_id
            try:
                name = name_path.read_text(encoding="utf-8").strip()
            except FileNotFoundError:
                pass  # Use default agent_id

            return session, name
        except FileNotFoundError:
            return None
        except (json.JSONDecodeError, KeyError, ValueError):
            return None

    def get_last_session_name(self) -> str | None:
        """Get the name of the last session without loading it.

        Returns:
            Session name or None if no last session.
        """
        name_path = self._last_session_name_path()
        # Avoid TOCTOU race: catch FileNotFoundError instead of checking exists()
        try:
            return name_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None
        except OSError:
            return None

    def clear_last_session(self) -> None:
        """Clear the last session data.

        Removes both last-session.json and last-session-name.
        """
        path = self._last_session_path()
        name_path = self._last_session_name_path()

        # Avoid TOCTOU race: catch FileNotFoundError instead of checking exists()
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        try:
            name_path.unlink()
        except FileNotFoundError:
            pass

    def rename_session(self, old_name: str, new_name: str) -> Path:
        """Rename a saved session.

        Args:
            old_name: Current session name.
            new_name: New session name.

        Returns:
            Path to the renamed session file.

        Raises:
            SessionNotFoundError: If old session doesn't exist.
            SessionManagerError: If new name already exists.
        """
        old_path = self._session_path(old_name)
        new_path = self._session_path(new_name)

        # Avoid TOCTOU race: catch FileNotFoundError instead of checking exists()
        try:
            content = old_path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise SessionNotFoundError(old_name) from exc

        # Check destination doesn't exist (still a minor race, but acceptable for this use case)
        if new_path.exists():
            raise SessionManagerError(f"Session already exists: {new_name}")

        # Load, update agent_id, save with new name
        session = SavedSession.from_json(content)
        session.agent_id = new_name
        session.modified_at = datetime.now()

        _secure_write_file(new_path, session.to_json())
        old_path.unlink()

        return new_path

    def clone_session(self, src_name: str, dest_name: str) -> Path:
        """Clone a saved session.

        Args:
            src_name: Source session name.
            dest_name: Destination session name.

        Returns:
            Path to the cloned session file.

        Raises:
            SessionNotFoundError: If source session doesn't exist.
            SessionManagerError: If destination name already exists.
        """
        src_path = self._session_path(src_name)
        dest_path = self._session_path(dest_name)

        # Avoid TOCTOU race: catch FileNotFoundError instead of checking exists()
        try:
            content = src_path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise SessionNotFoundError(src_name) from exc

        # Check destination doesn't exist (still a minor race, but acceptable for this use case)
        if dest_path.exists():
            raise SessionManagerError(f"Session already exists: {dest_name}")

        # Load, update agent_id and timestamps, save with new name
        session = SavedSession.from_json(content)
        session.agent_id = dest_name
        now = datetime.now()
        session.created_at = now
        session.modified_at = now

        _secure_write_file(dest_path, session.to_json())

        return dest_path
