"""Base class for GitLab skills."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from nexus3.core.types import ToolResult
from nexus3.skill.base import BaseSkill
from nexus3.skill.vcs.config import GitLabConfig, GitLabInstance
from nexus3.skill.vcs.gitlab.client import GitLabAPIError, GitLabClient

if TYPE_CHECKING:
    from nexus3.skill.services import ServiceContainer


class GitLabSkill(BaseSkill):
    """
    Base class for all GitLab skills.

    Provides:
    - Instance resolution (which GitLab to connect to)
    - Client management (lazy initialization, caching)
    - Project resolution from git remote
    - Standard error handling
    """

    def __init__(
        self,
        services: ServiceContainer,
        gitlab_config: GitLabConfig,
    ):
        self._services = services
        self._config = gitlab_config
        self._clients: dict[str, GitLabClient] = {}
        self._current_instance: GitLabInstance | None = None
        self._remote_url_cache: dict[str, str | None] = {}

    def _remote_cache_key(self, cwd: Path | str | None = None) -> str:
        work_dir = Path(cwd) if cwd is not None else self._services.get_cwd()
        return str(work_dir)

    def _read_remote_origin_url(self, cwd: Path) -> str | None:
        """Read the origin remote URL for a working tree."""
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=cwd,
        )
        if result.returncode != 0:
            return None

        remote_url = result.stdout.strip()
        return remote_url or None

    def _get_remote_origin_url(self, cwd: Path | str | None = None) -> str | None:
        """Get cached origin remote URL, populating synchronously if needed."""
        work_dir = Path(cwd) if cwd is not None else self._services.get_cwd()
        cache_key = str(work_dir)
        if cache_key not in self._remote_url_cache:
            try:
                self._remote_url_cache[cache_key] = self._read_remote_origin_url(work_dir)
            except Exception:
                self._remote_url_cache[cache_key] = None
        return self._remote_url_cache[cache_key]

    async def _prime_remote_context(self, cwd: Path | str | None = None) -> None:
        """Populate origin-remote cache off the event loop when possible."""
        work_dir = Path(cwd) if cwd is not None else self._services.get_cwd()
        cache_key = str(work_dir)
        if cache_key in self._remote_url_cache:
            return

        try:
            self._remote_url_cache[cache_key] = await asyncio.to_thread(
                self._read_remote_origin_url,
                work_dir,
            )
        except Exception:
            self._remote_url_cache[cache_key] = None

    def _resolve_instance(self, instance_name: str | None = None) -> GitLabInstance:
        """
        Resolve which GitLab instance to use.

        Priority:
        1. Explicit instance_name parameter
        2. Detect from git remote (if in a git repo)
        3. Default instance from config
        """
        # Explicit instance requested
        if instance_name:
            instance = self._config.get_instance(instance_name)
            if not instance:
                raise ValueError(f"GitLab instance '{instance_name}' not configured")
            return instance

        # Try to detect from git remote
        detected = self._detect_instance_from_remote()
        if detected:
            return detected

        # Fall back to default
        instance = self._config.get_instance()
        if not instance:
            raise ValueError("No GitLab instance configured")
        return instance

    def _detect_instance_from_remote(self) -> GitLabInstance | None:
        """
        Detect GitLab instance from current git remote.

        Returns instance if a configured instance matches the remote URL.
        """
        try:
            remote_url = self._get_remote_origin_url()
            if not remote_url:
                return None
            remote_host = self._extract_host(remote_url)

            # Find matching instance
            for instance in self._config.instances.values():
                if instance.host == remote_host:
                    return instance

            return None
        except Exception:
            return None

    def _extract_host(self, url: str) -> str:
        """Extract hostname from git URL (supports HTTPS and SSH)."""
        # SSH format: git@gitlab.com:group/repo.git
        if url.startswith("git@"):
            return url.split("@")[1].split(":")[0]
        # HTTPS format: https://gitlab.com/group/repo.git
        return urlparse(url).netloc

    def _get_client(self, instance: GitLabInstance) -> GitLabClient:
        """Get or create client for instance."""
        key = instance.host
        if key not in self._clients:
            self._clients[key] = GitLabClient(instance)
        return self._clients[key]

    def _resolve_project(
        self,
        project: str | None,
        cwd: str | None = None,
    ) -> str:
        """
        Resolve project path.

        Priority:
        1. Explicit project parameter (pass "this" to force git remote detection)
        2. Detect from git remote
        """
        if project and project.lower() != "this":
            return project

        # Try to detect from git remote
        try:
            work_dir = Path(cwd) if cwd else self._services.get_cwd()
            remote_url = self._get_remote_origin_url(work_dir)
            if remote_url:
                return self._extract_project_path(remote_url)
        except Exception:
            pass

        raise ValueError("No project specified and could not detect from git remote")

    def _extract_project_path(self, url: str) -> str:
        """Extract project path from git URL."""
        # SSH format: git@gitlab.com:group/repo.git
        if url.startswith("git@"):
            path = url.split(":")[1]
        else:
            # HTTPS format: https://gitlab.com/group/repo.git
            path = urlparse(url).path.lstrip("/")

        # Remove .git suffix
        if path.endswith(".git"):
            path = path[:-4]

        return path

    def _format_error(self, error: GitLabAPIError) -> ToolResult:
        """Format API error as ToolResult with full message passthrough."""
        return ToolResult(error=str(error))

    async def execute(self, **kwargs: Any) -> ToolResult:
        """
        Execute skill with error handling.

        Subclasses should override _execute_impl() instead of this method.
        """
        try:
            if (
                kwargs.get("instance") is None
                or kwargs.get("project") is None
                or kwargs.get("project") == "this"
            ):
                await self._prime_remote_context()

            # Resolve instance
            instance = self._resolve_instance(kwargs.get("instance"))
            self._current_instance = instance

            # Get client and execute
            client = self._get_client(instance)
            return await self._execute_impl(client, **kwargs)

        except GitLabAPIError as e:
            return self._format_error(e)
        except ValueError as e:
            return ToolResult(error=str(e))
        except Exception as e:
            return ToolResult(error=f"Unexpected error: {e}")

    async def _execute_impl(
        self,
        client: GitLabClient,
        **kwargs: Any,
    ) -> ToolResult:
        """
        Implement skill logic. Override in subclasses.

        Args:
            client: Authenticated GitLab client
            **kwargs: Skill parameters

        Returns:
            ToolResult with output or error
        """
        raise NotImplementedError("Subclasses must implement _execute_impl")

    async def _resolve_user_ids(
        self,
        client: GitLabClient,
        usernames: list[str],
    ) -> list[int]:
        """Resolve usernames to numeric user IDs.

        Supports 'me' shorthand which resolves from config or API.
        """
        result: list[int] = []
        for username in usernames:
            if username.lower() == "me":
                user_id = await self._resolve_me_user_id(client)
                result.append(user_id)
            else:
                result.append(await client.lookup_user(username))
        return result

    async def _resolve_me_user_id(self, client: GitLabClient) -> int:
        """Resolve 'me' to a numeric user ID.

        Uses config user_id if set, else looks up config username, else falls
        back to GET /user.
        """
        inst = self._current_instance
        if inst and inst.user_id:
            return inst.user_id
        if inst and inst.username:
            return await client.lookup_user(inst.username)
        # API fallback
        user = await client.get_current_user()
        user_id: int = user["id"]
        return user_id

    async def _resolve_me_username(self, client: GitLabClient) -> str:
        """Resolve 'me' to a username string (for list filters).

        Uses config username if set, else falls back to GET /user.
        """
        inst = self._current_instance
        if inst and inst.username:
            return inst.username
        user = await client.get_current_user()
        username: str = user["username"]
        return username
