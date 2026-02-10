"""GitLab branch management skill."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nexus3.core.types import ToolResult
from nexus3.skill.vcs.gitlab.base import GitLabSkill
from nexus3.skill.vcs.gitlab.client import GitLabClient

if TYPE_CHECKING:
    pass


class GitLabBranchSkill(GitLabSkill):
    """List, create, delete, and protect GitLab branches.

    Actions: list, get, create, delete, protect, unprotect, list-protected.
    Create requires name and ref (source branch/tag/commit).
    """

    @property
    def name(self) -> str:
        return "gitlab_branch"

    @property
    def description(self) -> str:
        return (
            "List, create, delete, and protect GitLab branches. "
            "Actions: list, get, create, delete, protect, unprotect, list-protected. "
            "Create requires name and ref (source branch/tag/commit)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "list", "get", "create", "delete",
                        "protect", "unprotect", "list-protected",
                    ],
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
                    "description": "Branch name (required for get/create/delete/protect/unprotect)",
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
                "push_level": {
                    "type": "string",
                    "enum": ["no_access", "developer", "maintainer"],
                    "description": "Who can push to protected branch (default: maintainer)",
                },
                "merge_level": {
                    "type": "string",
                    "enum": ["no_access", "developer", "maintainer"],
                    "description": "Who can merge to protected branch (default: maintainer)",
                },
                "allow_force_push": {
                    "type": "boolean",
                    "description": "Allow force push to protected branch (default: false)",
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
        excluded = (
            "action", "project", "instance", "name", "ref",
            "push_level", "merge_level", "allow_force_push",
        )
        filtered = {k: v for k, v in kwargs.items() if k not in excluded}

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
            case "protect":
                name = kwargs.get("name")
                if not name:
                    return ToolResult(error="name parameter required for protect action")
                push_level = kwargs.get("push_level", "maintainer")
                merge_level = kwargs.get("merge_level", "maintainer")
                allow_force_push = kwargs.get("allow_force_push", False)
                return await self._protect_branch(
                    client, project_encoded, name, push_level, merge_level, allow_force_push
                )
            case "unprotect":
                name = kwargs.get("name")
                if not name:
                    return ToolResult(error="name parameter required for unprotect action")
                return await self._unprotect_branch(client, project_encoded, name)
            case "list-protected":
                return await self._list_protected_branches(client, project_encoded, **filtered)
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

    def _access_level_to_int(self, level: str) -> int:
        """Convert access level string to GitLab API integer."""
        level_map = {
            "no_access": 0,
            "developer": 30,
            "maintainer": 40,
        }
        return level_map.get(level, 40)  # Default to maintainer

    def _access_level_to_str(self, level: int) -> str:
        """Convert GitLab API integer to human-readable string."""
        level_map = {
            0: "no_access",
            30: "developer",
            40: "maintainer",
            60: "admin",
        }
        return level_map.get(level, f"level_{level}")

    async def _protect_branch(
        self,
        client: GitLabClient,
        project: str,
        name: str,
        push_level: str,
        merge_level: str,
        allow_force_push: bool,
    ) -> ToolResult:
        push_access_level = self._access_level_to_int(push_level)
        merge_access_level = self._access_level_to_int(merge_level)

        await client.post(
            f"/projects/{project}/protected_branches",
            name=name,
            push_access_level=push_access_level,
            merge_access_level=merge_access_level,
            allow_force_push=allow_force_push,
        )

        return ToolResult(
            output=f"Protected branch '{name}' (push: {push_level}, merge: {merge_level})"
        )

    async def _unprotect_branch(
        self,
        client: GitLabClient,
        project: str,
        name: str,
    ) -> ToolResult:
        branch_encoded = client._encode_path(name)
        await client.delete(f"/projects/{project}/protected_branches/{branch_encoded}")
        return ToolResult(output=f"Removed protection from branch '{name}'")

    async def _list_protected_branches(
        self,
        client: GitLabClient,
        project: str,
        **kwargs: Any,
    ) -> ToolResult:
        limit = kwargs.get("limit", 20)

        branches = [
            branch async for branch in
            client.paginate(f"/projects/{project}/protected_branches", limit=limit)
        ]

        if not branches:
            return ToolResult(output="No protected branches found")

        lines = [f"Found {len(branches)} protected branch(es):"]
        for branch in branches:
            name = branch.get("name", "unknown")

            # Extract push access levels
            push_levels = branch.get("push_access_levels", [])
            push_str = ", ".join(
                self._access_level_to_str(p.get("access_level", 0))
                for p in push_levels
            ) or "none"

            # Extract merge access levels
            merge_levels = branch.get("merge_access_levels", [])
            merge_str = ", ".join(
                self._access_level_to_str(m.get("access_level", 0))
                for m in merge_levels
            ) or "none"

            force_push = "yes" if branch.get("allow_force_push") else "no"

            lines.append(f"  {name}")
            lines.append(f"      push: {push_str}, merge: {merge_str}, force_push: {force_push}")

        return ToolResult(output="\n".join(lines))
