"""GitLab branch management skill."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nexus3.core.types import ToolResult
from nexus3.skill.vcs.gitlab.base import GitLabSkill
from nexus3.skill.vcs.gitlab.client import GitLabClient

if TYPE_CHECKING:
    pass


class GitLabBranchSkill(GitLabSkill):
    """List, create, and delete GitLab branches."""

    @property
    def name(self) -> str:
        return "gitlab_branch"

    @property
    def description(self) -> str:
        return "List, create, and delete GitLab branches"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "get", "create", "delete"],
                    "description": "Action to perform",
                },
                "instance": {
                    "type": "string",
                    "description": "GitLab instance name (uses default if omitted)",
                },
                "project": {
                    "type": "string",
                    "description": (
                        "Project path (e.g., 'group/repo'). "
                        "Auto-detected from git remote if omitted."
                    ),
                },
                "name": {
                    "type": "string",
                    "description": "Branch name (required for get/create/delete)",
                },
                "ref": {
                    "type": "string",
                    "description": "Source ref for create (branch, tag, or commit SHA)",
                },
                "search": {
                    "type": "string",
                    "description": "Filter branches by search term",
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
        project = self._resolve_project(kwargs.get("project"))
        project_encoded = client._encode_path(project)

        # Filter out consumed kwargs to avoid passing them twice
        filtered = {k: v for k, v in kwargs.items() if k not in ("action", "project", "instance")}

        match action:
            case "list":
                return await self._list_branches(client, project_encoded, **filtered)
            case "get":
                name = kwargs.get("name")
                if not name:
                    return ToolResult(error="name parameter required for get action")
                return await self._get_branch(client, project_encoded, name)
            case "create":
                name = kwargs.get("name")
                ref = kwargs.get("ref")
                if not name:
                    return ToolResult(error="name parameter required for create action")
                if not ref:
                    return ToolResult(error="ref parameter required for create action")
                return await self._create_branch(client, project_encoded, name, ref)
            case "delete":
                name = kwargs.get("name")
                if not name:
                    return ToolResult(error="name parameter required for delete action")
                return await self._delete_branch(client, project_encoded, name)
            case _:
                return ToolResult(error=f"Unknown action: {action}")

    async def _list_branches(
        self,
        client: GitLabClient,
        project: str,
        **kwargs: Any,
    ) -> ToolResult:
        params: dict[str, Any] = {}

        if search := kwargs.get("search"):
            params["search"] = search

        limit = kwargs.get("limit", 20)

        branches = [
            branch async for branch in
            client.paginate(f"/projects/{project}/repository/branches", limit=limit, **params)
        ]

        if not branches:
            return ToolResult(output="No branches found")

        lines = [f"Found {len(branches)} branch(es):"]
        for branch in branches:
            default = " (default)" if branch.get("default") else ""
            protected = " 🔒" if branch.get("protected") else ""
            merged = " ✓merged" if branch.get("merged") else ""

            # Get latest commit info
            commit = branch.get("commit", {})
            short_sha = commit.get("short_id", "")[:8] if commit else ""
            author = commit.get("author_name", "")

            lines.append(f"  {branch['name']}{default}{protected}{merged}")
            if short_sha:
                lines.append(f"      {short_sha} by {author}")

        return ToolResult(output="\n".join(lines))

    async def _get_branch(
        self,
        client: GitLabClient,
        project: str,
        name: str,
    ) -> ToolResult:
        branch_encoded = client._encode_path(name)
        branch = await client.get(f"/projects/{project}/repository/branches/{branch_encoded}")

        lines = [
            f"# {branch['name']}",
            "",
        ]

        if branch.get("default"):
            lines.append("Default Branch: Yes")
        if branch.get("protected"):
            lines.append("Protected: Yes")
        if branch.get("merged"):
            lines.append("Merged: Yes")
        if branch.get("developers_can_push"):
            lines.append("Developers Can Push: Yes")
        if branch.get("developers_can_merge"):
            lines.append("Developers Can Merge: Yes")

        # Commit info
        commit = branch.get("commit", {})
        if commit:
            lines.append("")
            lines.append("Latest Commit:")
            lines.append(f"  SHA: {commit.get('id', 'N/A')}")
            author_name = commit.get('author_name', 'N/A')
            author_email = commit.get('author_email', '')
            lines.append(f"  Author: {author_name} <{author_email}>")
            lines.append(f"  Date: {commit.get('created_at', 'N/A')}")
            lines.append(f"  Message: {commit.get('title', 'N/A')}")

        return ToolResult(output="\n".join(lines))

    async def _create_branch(
        self,
        client: GitLabClient,
        project: str,
        name: str,
        ref: str,
    ) -> ToolResult:
        branch = await client.post(
            f"/projects/{project}/repository/branches",
            branch=name,
            ref=ref,
        )

        return ToolResult(
            output=f"Created branch '{branch['name']}' from {ref}"
        )

    async def _delete_branch(
        self,
        client: GitLabClient,
        project: str,
        name: str,
    ) -> ToolResult:
        branch_encoded = client._encode_path(name)
        await client.delete(f"/projects/{project}/repository/branches/{branch_encoded}")
        return ToolResult(output=f"Deleted branch '{name}'")
