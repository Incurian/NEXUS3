"""Unified path resolution for all agent contexts.

PathResolver consolidates the path resolution logic scattered across
FileSkill, ExecutionSkill, FilteredCommandSkill, and global_dispatcher.
All path operations should go through this class to ensure consistent
security and resolution behavior.
"""

from pathlib import Path
from typing import TYPE_CHECKING

from nexus3.core.errors import PathSecurityError
from nexus3.core.paths import validate_path

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
        """Resolve path relative to agent's cwd, validate against allowed_paths.

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
        # 1. Get agent's cwd (not process cwd)
        agent_cwd = self._services.get_cwd()

        # 2. Resolve relative paths against agent cwd
        p = Path(path).expanduser() if isinstance(path, str) else path.expanduser()
        if not p.is_absolute():
            p = agent_cwd / p

        # 3. Get per-tool allowed_paths
        allowed = self._services.get_tool_allowed_paths(tool_name) if tool_name else None

        # 4. Validate via validate_path (follows symlinks, checks containment)
        resolved = validate_path(p, allowed_paths=allowed)

        # 5. Existence checks
        if must_exist and not resolved.exists():
            raise PathSecurityError(str(path), f"Path not found: {path}")
        if must_be_dir and not resolved.is_dir():
            raise PathSecurityError(str(path), f"Not a directory: {path}")

        return resolved

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
        # Get agent's cwd as default
        agent_cwd = self._services.get_cwd()

        if not cwd:
            return str(agent_cwd), None

        try:
            resolved = self.resolve(
                cwd,
                tool_name=tool_name,
                must_exist=True,
                must_be_dir=True,
            )
            return str(resolved), None
        except PathSecurityError as e:
            return None, str(e)

    def resolve_or_error(
        self,
        path: str | Path,
        tool_name: str | None = None,
        must_exist: bool = False,
        must_be_dir: bool = False,
    ) -> tuple[Path | None, str | None]:
        """Resolve path, returning error message instead of raising.

        Convenience wrapper around resolve() that catches PathSecurityError
        and returns it as a string, useful for skill implementations.

        Args:
            path: Path string or Path object to resolve.
            tool_name: Optional tool name for per-tool allowed_paths lookup.
            must_exist: Return error if path doesn't exist.
            must_be_dir: Return error if path isn't a directory.

        Returns:
            Tuple of (resolved_path, error_message).
            If error_message is not None, resolved_path will be None.
        """
        try:
            resolved = self.resolve(
                path,
                tool_name=tool_name,
                must_exist=must_exist,
                must_be_dir=must_be_dir,
            )
            return resolved, None
        except PathSecurityError as e:
            return None, str(e)
