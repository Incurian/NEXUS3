"""Authoritative path decision engine for NEXUS3.

Arch A2: Provides a centralized, explicit path decision API that explains
why paths are allowed or denied.

This module builds on top of the existing `paths.py` validation functions
but provides:
1. Explicit decision results (not just exceptions)
2. Detailed reasoning for each decision
3. A single source of truth for all path access decisions

Usage:
    from nexus3.core.path_decision import PathDecisionEngine, PathDecision

    engine = PathDecisionEngine(
        allowed_paths=[Path("/home/user/project")],
        blocked_paths=[Path("/home/user/project/.env")],
    )

    decision = engine.check_access("/home/user/project/src/main.py")
    if decision.allowed:
        # Use decision.resolved_path
        ...
    else:
        print(f"Access denied: {decision.reason}")

SECURITY: This is the authoritative source for path access decisions.
All file operations, exec cwd validation, and path-related permission
checks should use this engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING

from nexus3.core.errors import PathSecurityError
from nexus3.core.paths import validate_path

if TYPE_CHECKING:
    from nexus3.skill.services import ServiceContainer


class PathDecisionReason(Enum):
    """Reasons for path access decisions."""

    # Allowed reasons
    UNRESTRICTED = auto()  # No allowed_paths configured (TRUSTED/YOLO mode)
    WITHIN_ALLOWED = auto()  # Path is within an allowed directory
    CWD_DEFAULT = auto()  # Path is agent's cwd (default working directory)

    # Denied reasons
    BLOCKED = auto()  # Path is in blocked_paths
    OUTSIDE_ALLOWED = auto()  # Path is not within any allowed directory
    NO_ALLOWED_PATHS = auto()  # Empty allowed_paths list (nothing permitted)
    RESOLUTION_FAILED = auto()  # Could not resolve path (invalid, dangling symlink)
    PATH_NOT_FOUND = auto()  # Path doesn't exist (when must_exist=True)
    NOT_A_DIRECTORY = auto()  # Path isn't a directory (when must_be_dir=True)


@dataclass(frozen=True)
class PathDecision:
    """Result of a path access decision.

    Attributes:
        allowed: Whether access is permitted.
        resolved_path: The resolved absolute path (if allowed), None otherwise.
        reason: Why the decision was made.
        reason_detail: Human-readable explanation.
        original_path: The original path that was checked.
        matched_rule: The specific allowed/blocked path that matched (if any).
    """

    allowed: bool
    resolved_path: Path | None
    reason: PathDecisionReason
    reason_detail: str
    original_path: str
    matched_rule: Path | None = None

    def __str__(self) -> str:
        """Human-readable decision string."""
        status = "ALLOWED" if self.allowed else "DENIED"
        return f"{status}: {self.original_path} - {self.reason_detail}"

    def raise_if_denied(self) -> Path:
        """Raise PathSecurityError if denied, return resolved path if allowed.

        This is a convenience method for code that expects the exception-based
        API but wants decision details on error.

        Returns:
            The resolved path if access is allowed.

        Raises:
            PathSecurityError: If access is denied.
        """
        if not self.allowed:
            raise PathSecurityError(self.original_path, self.reason_detail)
        assert self.resolved_path is not None
        return self.resolved_path


class PathDecisionEngine:
    """Authoritative engine for path access decisions.

    Centralizes all path validation logic and provides explicit decision
    results with reasoning. This is the single source of truth for
    determining whether a path can be accessed.

    The engine supports two modes:
    1. Standalone: Initialize with explicit allowed_paths/blocked_paths
    2. ServiceContainer: Initialize from a ServiceContainer for per-agent paths

    Examples:
        # Standalone mode
        engine = PathDecisionEngine(
            allowed_paths=[Path("/home/user/project")],
            blocked_paths=[Path("/home/user/project/.env")],
        )

        # ServiceContainer mode
        engine = PathDecisionEngine.from_services(services, tool_name="read_file")

        # Check access
        decision = engine.check_access("/home/user/project/src/main.py")
        if decision.allowed:
            with open(decision.resolved_path) as f:
                ...
    """

    def __init__(
        self,
        allowed_paths: list[Path] | None = None,
        blocked_paths: list[Path] | None = None,
        cwd: Path | None = None,
    ) -> None:
        """Initialize the path decision engine.

        Args:
            allowed_paths: Paths that are permitted. None = unrestricted.
                Empty list = nothing allowed.
            blocked_paths: Paths that are always denied (takes precedence).
            cwd: Working directory for resolving relative paths.
                Defaults to process cwd if not specified.
        """
        self._allowed_paths = allowed_paths
        self._blocked_paths = blocked_paths or []
        self._cwd = cwd or Path.cwd()

    @classmethod
    def from_services(
        cls,
        services: "ServiceContainer",
        tool_name: str | None = None,
    ) -> "PathDecisionEngine":
        """Create engine from a ServiceContainer.

        This uses the per-agent and per-tool path configurations from
        the ServiceContainer, which is the standard way to get path
        restrictions in skill implementations.

        Args:
            services: ServiceContainer with permissions and cwd.
            tool_name: Optional tool name for per-tool allowed_paths.

        Returns:
            PathDecisionEngine configured for this agent/tool.
        """
        return cls(
            allowed_paths=services.get_tool_allowed_paths(tool_name),
            blocked_paths=services.get_blocked_paths(),
            cwd=services.get_cwd(),
        )

    def check_access(
        self,
        path: str | Path,
        must_exist: bool = False,
        must_be_dir: bool = False,
    ) -> PathDecision:
        """Check whether access to a path is allowed.

        This is the main method for making path access decisions. It
        resolves the path, checks against allowed/blocked lists, and
        returns an explicit decision with reasoning.

        Args:
            path: Path to check (can be relative to cwd).
            must_exist: If True, deny if path doesn't exist.
            must_be_dir: If True, deny if path isn't a directory.

        Returns:
            PathDecision with allowed/denied status and reasoning.
        """
        original = str(path)

        # Resolve relative paths against cwd
        p = Path(path).expanduser() if isinstance(path, str) else path.expanduser()
        if not p.is_absolute():
            p = self._cwd / p

        # Try to resolve the path (follows symlinks)
        try:
            resolved = p.resolve()
        except (OSError, ValueError) as e:
            return PathDecision(
                allowed=False,
                resolved_path=None,
                reason=PathDecisionReason.RESOLUTION_FAILED,
                reason_detail=f"Cannot resolve path: {e}",
                original_path=original,
            )

        # Check blocked first (always enforced)
        for blocked in self._blocked_paths:
            try:
                blocked_resolved = blocked.resolve()
                if resolved.is_relative_to(blocked_resolved):
                    return PathDecision(
                        allowed=False,
                        resolved_path=None,
                        reason=PathDecisionReason.BLOCKED,
                        reason_detail=f"Path is blocked: {blocked}",
                        original_path=original,
                        matched_rule=blocked,
                    )
            except (OSError, ValueError):
                continue

        # Check allowed paths
        if self._allowed_paths is not None:
            # Empty list = nothing allowed
            if not self._allowed_paths:
                return PathDecision(
                    allowed=False,
                    resolved_path=None,
                    reason=PathDecisionReason.NO_ALLOWED_PATHS,
                    reason_detail="No allowed paths configured (access denied)",
                    original_path=original,
                )

            # Check if within any allowed path
            for allowed in self._allowed_paths:
                try:
                    allowed_resolved = allowed.resolve()
                    if resolved.is_relative_to(allowed_resolved):
                        # Allowed! But check existence constraints
                        return self._check_existence_constraints(
                            resolved, original, must_exist, must_be_dir, allowed
                        )
                except (OSError, ValueError):
                    continue

            # Not in any allowed path
            allowed_str = ", ".join(str(p) for p in self._allowed_paths)
            return PathDecision(
                allowed=False,
                resolved_path=None,
                reason=PathDecisionReason.OUTSIDE_ALLOWED,
                reason_detail=f"Path outside allowed directories. Allowed: [{allowed_str}]",
                original_path=original,
            )

        # No allowed_paths = unrestricted (TRUSTED/YOLO mode)
        return self._check_existence_constraints(
            resolved, original, must_exist, must_be_dir, None
        )

    def _check_existence_constraints(
        self,
        resolved: Path,
        original: str,
        must_exist: bool,
        must_be_dir: bool,
        matched_allowed: Path | None,
    ) -> PathDecision:
        """Check existence constraints after path is approved.

        Args:
            resolved: The resolved path.
            original: Original path string.
            must_exist: Require path to exist.
            must_be_dir: Require path to be a directory.
            matched_allowed: The allowed_path rule that matched (or None if unrestricted).

        Returns:
            PathDecision for the existence check.
        """
        if must_exist and not resolved.exists():
            return PathDecision(
                allowed=False,
                resolved_path=None,
                reason=PathDecisionReason.PATH_NOT_FOUND,
                reason_detail=f"Path not found: {original}",
                original_path=original,
            )

        if must_be_dir and resolved.exists() and not resolved.is_dir():
            return PathDecision(
                allowed=False,
                resolved_path=None,
                reason=PathDecisionReason.NOT_A_DIRECTORY,
                reason_detail=f"Not a directory: {original}",
                original_path=original,
            )

        # Determine the reason
        if self._allowed_paths is None:
            reason = PathDecisionReason.UNRESTRICTED
            detail = "Access unrestricted (TRUSTED/YOLO mode)"
        else:
            reason = PathDecisionReason.WITHIN_ALLOWED
            detail = f"Path within allowed directory: {matched_allowed}"

        return PathDecision(
            allowed=True,
            resolved_path=resolved,
            reason=reason,
            reason_detail=detail,
            original_path=original,
            matched_rule=matched_allowed,
        )

    def check_cwd(self, cwd: str | None, tool_name: str | None = None) -> PathDecision:
        """Check whether a working directory can be used.

        Convenience method for validating subprocess working directories.
        If cwd is None, returns success with the agent's default cwd.

        Args:
            cwd: Working directory path, or None for default.
            tool_name: Tool name (for logging/debugging).

        Returns:
            PathDecision with the validated cwd.
        """
        if cwd is None:
            return PathDecision(
                allowed=True,
                resolved_path=self._cwd,
                reason=PathDecisionReason.CWD_DEFAULT,
                reason_detail="Using agent's default working directory",
                original_path=str(self._cwd),
            )

        return self.check_access(cwd, must_exist=True, must_be_dir=True)

    @property
    def allowed_paths(self) -> list[Path] | None:
        """Get the allowed paths (None = unrestricted)."""
        return self._allowed_paths

    @property
    def blocked_paths(self) -> list[Path]:
        """Get the blocked paths."""
        return self._blocked_paths

    @property
    def cwd(self) -> Path:
        """Get the working directory."""
        return self._cwd

    def is_unrestricted(self) -> bool:
        """Check if this engine has no path restrictions.

        Returns:
            True if allowed_paths is None (TRUSTED/YOLO mode).
        """
        return self._allowed_paths is None

    def explain_config(self) -> str:
        """Get a human-readable explanation of the engine's configuration.

        Returns:
            Multi-line string explaining allowed/blocked paths.
        """
        lines = [f"Working directory: {self._cwd}"]

        if self._allowed_paths is None:
            lines.append("Allowed paths: UNRESTRICTED (all paths permitted)")
        elif not self._allowed_paths:
            lines.append("Allowed paths: NONE (all access denied)")
        else:
            lines.append("Allowed paths:")
            for p in self._allowed_paths:
                lines.append(f"  - {p}")

        if self._blocked_paths:
            lines.append("Blocked paths:")
            for p in self._blocked_paths:
                lines.append(f"  - {p}")
        else:
            lines.append("Blocked paths: none")

        return "\n".join(lines)
