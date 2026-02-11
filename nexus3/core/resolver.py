"""Unified path resolution for all agent contexts.

PathResolver consolidates the path resolution logic scattered across
FileSkill, ExecutionSkill, FilteredCommandSkill, and global_dispatcher.
All path operations should go through this class to ensure consistent
security and resolution behavior.

Arch A2 Integration: PathResolver now routes through PathDecisionEngine,
ensuring a single source of truth for all path access decisions.
"""

from pathlib import Path
from typing import TYPE_CHECKING

from nexus3.core.path_decision import PathDecisionEngine

if TYPE_CHECKING:
    from nexus3.skill.services import ServiceContainer


class PathResolver:
    """Unified path resolution for all agent contexts.

    Consolidates:
    - Relative path resolution against agent's cwd (not process cwd)
    - Per-tool allowed_paths resolution via ServiceContainer
    - Symlink following and security validation
    - Existence and directory checks

    This replaces the duplicated logic in:
    - FileSkill._validate_path()
    - ExecutionSkill._resolve_working_directory()
    - FilteredCommandSkill._validate_cwd()
    - global_dispatcher.py inline validation
    """

    def __init__(self, services: "ServiceContainer") -> None:
        """Initialize PathResolver with ServiceContainer.

        Args:
            services: ServiceContainer for accessing cwd and per-tool allowed_paths.
        """
        self._services = services

    def resolve(
        self,
        path: str | Path,
        tool_name: str | None = None,
        must_exist: bool = False,
        must_be_dir: bool = False,
    ) -> Path:
        """Resolve path relative to agent's cwd, validate against allowed/blocked paths.

        Arch A2: Routes through PathDecisionEngine for consistent path decisions.
        P2.3 SECURITY: blocked_paths are always enforced and take precedence over
        allowed_paths. This ensures sensitive paths can never be accessed even if
        they would otherwise be within allowed_paths.

        Args:
            path: Path string or Path object to resolve.
            tool_name: Optional tool name for per-tool allowed_paths lookup.
            must_exist: Raise if path doesn't exist.
            must_be_dir: Raise if path isn't a directory.

        Returns:
            Resolved absolute Path (symlinks followed).

        Raises:
            PathSecurityError: If path fails security validation.
        """
        # Route through PathDecisionEngine for consistent decisions
        engine = PathDecisionEngine.from_services(self._services, tool_name=tool_name)
        decision = engine.check_access(path, must_exist=must_exist, must_be_dir=must_be_dir)

        # raise_if_denied() returns the resolved path or raises PathSecurityError
        return decision.raise_if_denied()

    def resolve_cwd(
        self,
        cwd: str | None,
        tool_name: str | None = None,
    ) -> tuple[str | None, str | None]:
        """Resolve working directory for subprocess execution.

        This is a convenience method for ExecutionSkill and FilteredCommandSkill
        that need to resolve a cwd parameter for subprocess execution.

        Args:
            cwd: Working directory path (or None for agent's default).
            tool_name: Tool name for per-tool allowed_paths lookup.

        Returns:
            Tuple of (resolved_cwd_string, error_message_or_none).
            If error_message is not None, resolved_cwd will be None.
        """
        # Use PathDecisionEngine for cwd validation
        engine = PathDecisionEngine.from_services(self._services, tool_name=tool_name)
        decision = engine.check_cwd(cwd, tool_name=tool_name)

        if decision.allowed:
            return str(decision.resolved_path), None
        else:
            return None, decision.reason_detail

    def resolve_or_error(
        self,
        path: str | Path,
        tool_name: str | None = None,
        must_exist: bool = False,
        must_be_dir: bool = False,
    ) -> tuple[Path | None, str | None]:
        """Resolve path, returning error message instead of raising.

        Convenience wrapper that uses PathDecisionEngine directly and
        returns error message instead of raising, useful for skill implementations.

        Args:
            path: Path string or Path object to resolve.
            tool_name: Optional tool name for per-tool allowed_paths lookup.
            must_exist: Return error if path doesn't exist.
            must_be_dir: Return error if path isn't a directory.

        Returns:
            Tuple of (resolved_path, error_message).
            If error_message is not None, resolved_path will be None.
        """
        # Use PathDecisionEngine directly for non-throwing API
        engine = PathDecisionEngine.from_services(self._services, tool_name=tool_name)
        decision = engine.check_access(path, must_exist=must_exist, must_be_dir=must_be_dir)

        if decision.allowed:
            return decision.resolved_path, None
        else:
            return None, decision.reason_detail
