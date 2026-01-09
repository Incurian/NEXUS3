"""Session logging types and configuration."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Flag, auto
from pathlib import Path
from secrets import token_hex


class LogStream(Flag):
    """Log streams - can be combined with |.

    These are independent streams, not hierarchical levels.
    CONTEXT is always on in practice, others are opt-in.
    """

    NONE = 0
    CONTEXT = auto()  # Messages, tool calls - always on
    VERBOSE = auto()  # Thinking, timing, metadata - --verbose
    RAW = auto()  # Raw API JSON - --raw-log
    ALL = CONTEXT | VERBOSE | RAW


@dataclass
class LogConfig:
    """Configuration for session logging."""

    base_dir: Path = field(default_factory=lambda: Path(".nexus3/logs"))
    streams: LogStream = LogStream.ALL  # All streams on by default for now
    parent_session: str | None = None
    mode: str = "repl"  # "repl" or "serve" - shown in log folder name
    session_type: str = "temp"  # 'saved' | 'temp' | 'subagent' - for cleanup

    def __post_init__(self) -> None:
        """Ensure base_dir is a Path."""
        if isinstance(self.base_dir, str):
            self.base_dir = Path(self.base_dir)


@dataclass
class SessionInfo:
    """Information about a logging session."""

    session_id: str
    session_dir: Path
    parent_id: str | None = None
    created_at: datetime = field(default_factory=datetime.now)

    @classmethod
    def create(
        cls,
        base_dir: Path,
        parent_id: str | None = None,
        mode: str = "repl",
    ) -> "SessionInfo":
        """Create a new session with generated ID.

        Session ID format: YYYY-MM-DD_HHMMSS_MODE_xxxxxx
        Where MODE is 'repl' or 'serve' and xxxxxx is a 6-character hex string.

        For subagent sessions (parent_id is set), base_dir should be the
        parent's session_dir, and the subagent folder is created directly
        under it.
        """
        now = datetime.now()
        timestamp = now.strftime("%Y-%m-%d_%H%M%S")
        suffix = token_hex(3)  # 6 hex chars
        session_id = f"{timestamp}_{mode}_{suffix}"

        if parent_id:
            # Subagent: base_dir IS the parent session dir, create subagent folder
            session_dir = base_dir / f"subagent_{suffix}"
        else:
            # Top-level session
            session_dir = base_dir / session_id

        return cls(
            session_id=session_id,
            session_dir=session_dir,
            parent_id=parent_id,
            created_at=now,
        )
