"""GitLab repository operations skill."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nexus3.core.types import ToolResult
from nexus3.skill.vcs.gitlab.base import GitLabSkill
from nexus3.skill.vcs.gitlab.client import GitLabClient

if TYPE_CHECKING:
    pass


class GitLabRepoSkill(GitLabSkill):
    """View, list, and fork GitLab repositories."""

    @property
    def name(self) -> str:
        return "gitlab_repo"

    @property
    def description(self) -> str:
        return "View, list, and fork GitLab repositories"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["get", "list", "fork", "search"],
                    "description": "Action to perform",
                },
                "instance": {
                    "type": "string",
                    "description": "GitLab instance name (uses default if omitted)",
                },
                "project": {
                    "type": "string",
                    "description": "Project path (e.g., 'group/repo'). Required for get/fork.",
                },
                "search": {
                    "type": "string",
                    "description": "Search term for list/search actions",
                },
                "owned": {
                    "type": "boolean",
                    "description": "Filter to owned projects only (list action)",
                },
                "membership": {
                    "type": "boolean",
                    "description": "Filter to projects with membership (list action)",
                },
                "namespace": {
                    "type": "string",
                    "description": "Namespace/group to fork into (fork action)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results (default: 20)",
                },
            },
            "required": ["action"],
        }

    async def _execute_impl(
        self,
        client: GitLabClient,
        **kwargs: Any,
    ) -> ToolResult:
        action = kwargs.get("action", "")

        # Filter out consumed kwargs to avoid passing them twice
        filtered = {k: v for k, v in kwargs.items() if k not in ("action", "project", "instance")}

        match action:
            case "get":
                project = self._resolve_project(kwargs.get("project"))
                return await self._get_project(client, project)
            case "list":
                return await self._list_projects(client, **filtered)
            case "search":
                search = kwargs.get("search", "")
                if not search:
                    return ToolResult(error="search parameter required for search action")
                return await self._search_projects(client, search, kwargs.get("limit", 20))
            case "fork":
                project = self._resolve_project(kwargs.get("project"))
                return await self._fork_project(client, project, kwargs.get("namespace"))
            case _:
                return ToolResult(error=f"Unknown action: {action}")

    async def _get_project(
        self,
        client: GitLabClient,
        project: str,
    ) -> ToolResult:
        proj = await client.get_project(project)

        lines = [
            f"# {proj['path_with_namespace']}",
            "",
            f"Name: {proj['name']}",
            f"ID: {proj['id']}",
            f"Visibility: {proj['visibility']}",
            f"Default Branch: {proj.get('default_branch', 'N/A')}",
        ]

        if proj.get("description"):
            lines.append(f"Description: {proj['description']}")

        if proj.get("topics"):
            lines.append(f"Topics: {', '.join(proj['topics'])}")

        stats = []
        if "star_count" in proj:
            stats.append(f"⭐ {proj['star_count']}")
        if "forks_count" in proj:
            stats.append(f"🍴 {proj['forks_count']}")
        if "open_issues_count" in proj:
            stats.append(f"📋 {proj['open_issues_count']} open issues")
        if stats:
            lines.append(f"Stats: {' | '.join(stats)}")

        lines.append("")
        lines.append(f"Clone (HTTPS): {proj.get('http_url_to_repo', 'N/A')}")
        lines.append(f"Clone (SSH): {proj.get('ssh_url_to_repo', 'N/A')}")
        lines.append(f"Web URL: {proj['web_url']}")

        return ToolResult(output="\n".join(lines))

    async def _list_projects(
        self,
        client: GitLabClient,
        **kwargs: Any,
    ) -> ToolResult:
        limit = kwargs.get("limit", 20)
        projects = await client.list_projects(
            owned=kwargs.get("owned", False),
            membership=kwargs.get("membership", False),
            search=kwargs.get("search"),
            limit=limit,
        )

        if not projects:
            return ToolResult(output="No projects found")

        lines = [f"Found {len(projects)} project(s):"]
        for proj in projects:
            visibility_icon = {"public": "🌍", "internal": "🏢", "private": "🔒"}.get(
                proj["visibility"], "❓"
            )
            lines.append(f"  {visibility_icon} {proj['path_with_namespace']}")

        return ToolResult(output="\n".join(lines))

    async def _search_projects(
        self,
        client: GitLabClient,
        search: str,
        limit: int,
    ) -> ToolResult:
        projects = await client.list_projects(search=search, limit=limit)

        if not projects:
            return ToolResult(output=f"No projects matching '{search}'")

        lines = [f"Found {len(projects)} project(s) matching '{search}':"]
        for proj in projects:
            desc = f" - {proj['description'][:50]}..." if proj.get("description") else ""
            lines.append(f"  {proj['path_with_namespace']}{desc}")

        return ToolResult(output="\n".join(lines))

    async def _fork_project(
        self,
        client: GitLabClient,
        project: str,
        namespace: str | None,
    ) -> ToolResult:
        project_encoded = client._encode_path(project)
        data: dict[str, Any] = {}
        if namespace:
            data["namespace_path"] = namespace

        fork = await client.post(f"/projects/{project_encoded}/fork", **data)

        return ToolResult(
            output=f"Forked to {fork['path_with_namespace']}\n{fork['web_url']}"
        )
