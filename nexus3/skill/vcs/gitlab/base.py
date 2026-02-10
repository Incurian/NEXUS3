"""Base class for GitLab skills."""

from __future__ import annotations

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
            cwd = self._services.get_cwd()
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
        1. Explicit project parameter
        2. Detect from git remote
        """
        if project:
            return project

        # Try to detect from git remote
        try:
            work_dir = Path(cwd) if cwd else self._services.get_cwd()
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=work_dir,
            )
            if result.returncode == 0:
                return self._extract_project_path(result.stdout.strip())
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
        return user["id"]

    async def _resolve_me_username(self, client: GitLabClient) -> str:
        """Resolve 'me' to a username string (for list filters).

        Uses config username if set, else falls back to GET /user.
        """
        inst = self._current_instance
        if inst and inst.username:
            return inst.username
        user = await client.get_current_user()
        return user["username"]
