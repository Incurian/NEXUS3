"""GitLab tag management skill."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nexus3.core.types import ToolResult
from nexus3.skill.vcs.gitlab.base import GitLabSkill
from nexus3.skill.vcs.gitlab.client import GitLabClient

if TYPE_CHECKING:
    pass


class GitLabTagSkill(GitLabSkill):
    """List, create, delete, and protect GitLab tags.

    Actions: list, get, create, delete, protect, unprotect, list-protected.
    Create requires name and ref (commit SHA or branch).
    """

    @property
    def name(self) -> str:
        return "gitlab_tag"

    @property
    def description(self) -> str:
        return (
            "List, create, delete, and protect GitLab tags. "
            "Actions: list, get, create, delete, protect, unprotect, list-protected. "
            "Create requires name and ref (commit SHA or branch)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "list",
                        "get",
                        "create",
                        "delete",
                        "protect",
                        "unprotect",
                        "list-protected",
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
                    "description": "Tag name (required for get/create/delete)",
                },
                "ref": {
                    "type": "string",
                    "description": "Source ref for create (branch, tag, or commit SHA)",
                },
                "message": {
                    "type": "string",
                    "description": "Annotation message for create (creates annotated tag)",
                },
                "release_description": {
                    "type": "string",
                    "description": "Release notes (markdown) for create",
                },
                "search": {
                    "type": "string",
                    "description": "Filter tags by search term",
                },
                "order_by": {
                    "type": "string",
                    "enum": ["name", "updated", "version"],
                    "description": "Sort order (default: name)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results (default: 20)",
                },
                "create_level": {
                    "type": "string",
                    "enum": ["no_access", "developer", "maintainer"],
                    "description": (
                        "Who can create tags matching pattern (protect action). "
                        "Default: maintainer"
                    ),
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
        filtered = {
            k: v for k, v in kwargs.items()
            if k not in ("action", "project", "instance", "name", "create_level")
        }

        match action:
            case "list":
                return await self._list_tags(client, project_encoded, **filtered)
            case "get":
                name = kwargs.get("name")
                if not name:
                    return ToolResult(error="name parameter required for get action")
                return await self._get_tag(client, project_encoded, name)
            case "create":
                name = kwargs.get("name")
                ref = kwargs.get("ref")
                if not name:
                    return ToolResult(error="name parameter required for create action")
                if not ref:
                    return ToolResult(error="ref parameter required for create action")
                return await self._create_tag(client, project_encoded, **filtered)
            case "delete":
                name = kwargs.get("name")
                if not name:
                    return ToolResult(error="name parameter required for delete action")
                return await self._delete_tag(client, project_encoded, name)
            case "protect":
                name = kwargs.get("name")
                if not name:
                    return ToolResult(error="name parameter required for protect action")
                create_level = kwargs.get("create_level", "maintainer")
                return await self._protect_tag(client, project_encoded, name, create_level)
            case "unprotect":
                name = kwargs.get("name")
                if not name:
                    return ToolResult(error="name parameter required for unprotect action")
                return await self._unprotect_tag(client, project_encoded, name)
            case "list-protected":
                return await self._list_protected_tags(client, project_encoded, **filtered)
            case _:
                return ToolResult(error=f"Unknown action: {action}")

    async def _list_tags(
        self,
        client: GitLabClient,
        project: str,
        **kwargs: Any,
    ) -> ToolResult:
        params: dict[str, Any] = {}

        if search := kwargs.get("search"):
            params["search"] = search
        if order_by := kwargs.get("order_by"):
            params["order_by"] = order_by

        limit = kwargs.get("limit", 20)

        tags = [
            tag async for tag in
            client.paginate(f"/projects/{project}/repository/tags", limit=limit, **params)
        ]

        if not tags:
            return ToolResult(output="No tags found")

        lines = [f"Found {len(tags)} tag(s):"]
        for tag in tags:
            protected = " 🔒" if tag.get("protected") else ""

            # Get commit info
            commit = tag.get("commit", {})
            short_sha = commit.get("short_id", "")[:8] if commit else ""

            # Check for release
            release = " 📦" if tag.get("release") else ""

            lines.append(f"  {tag['name']}{protected}{release}")
            if short_sha:
                lines.append(f"      → {short_sha}")

        return ToolResult(output="\n".join(lines))

    async def _get_tag(
        self,
        client: GitLabClient,
        project: str,
        name: str,
    ) -> ToolResult:
        tag_encoded = client._encode_path(name)
        tag = await client.get(f"/projects/{project}/repository/tags/{tag_encoded}")

        lines = [
            f"# {tag['name']}",
            "",
        ]

        if tag.get("protected"):
            lines.append("Protected: Yes")

        # Commit info
        commit = tag.get("commit", {})
        if commit:
            lines.append("")
            lines.append("Tagged Commit:")
            lines.append(f"  SHA: {commit.get('id', 'N/A')}")
            lines.append(f"  Author: {commit.get('author_name', 'N/A')}")
            lines.append(f"  Date: {commit.get('created_at', 'N/A')}")
            lines.append(f"  Message: {commit.get('title', 'N/A')}")

        # Tag message (if annotated)
        if tag.get("message"):
            lines.append("")
            lines.append("Tag Message:")
            lines.append(tag["message"])

        # Release info
        if tag.get("release"):
            release = tag["release"]
            lines.append("")
            lines.append("Release:")
            if release.get("tag_name"):
                lines.append(f"  Tag: {release['tag_name']}")
            if release.get("description"):
                lines.append(f"  Notes: {release['description'][:200]}...")

        return ToolResult(output="\n".join(lines))

    async def _create_tag(
        self,
        client: GitLabClient,
        project: str,
        **kwargs: Any,
    ) -> ToolResult:
        data: dict[str, Any] = {
            "tag_name": kwargs["name"],
            "ref": kwargs["ref"],
        }

        if message := kwargs.get("message"):
            data["message"] = message
        if release_description := kwargs.get("release_description"):
            data["release_description"] = release_description

        tag = await client.post(f"/projects/{project}/repository/tags", **data)

        output = f"Created tag '{tag['name']}' at {kwargs['ref']}"
        if kwargs.get("release_description"):
            output += " with release notes"

        return ToolResult(output=output)

    async def _delete_tag(
        self,
        client: GitLabClient,
        project: str,
        name: str,
    ) -> ToolResult:
        tag_encoded = client._encode_path(name)
        await client.delete(f"/projects/{project}/repository/tags/{tag_encoded}")
        return ToolResult(output=f"Deleted tag '{name}'")

    async def _protect_tag(
        self,
        client: GitLabClient,
        project: str,
        name: str,
        create_level: str,
    ) -> ToolResult:
        # Map level names to GitLab access level integers
        level_map = {
            "no_access": 0,
            "developer": 30,
            "maintainer": 40,
        }
        access_level = level_map.get(create_level, 40)

        await client.post(
            f"/projects/{project}/protected_tags",
            name=name,
            create_access_level=access_level,
        )

        return ToolResult(output=f"Protected tag pattern '{name}' (create: {create_level})")

    async def _unprotect_tag(
        self,
        client: GitLabClient,
        project: str,
        name: str,
    ) -> ToolResult:
        name_encoded = client._encode_path(name)
        await client.delete(f"/projects/{project}/protected_tags/{name_encoded}")
        return ToolResult(output=f"Removed protection from tag pattern '{name}'")

    async def _list_protected_tags(
        self,
        client: GitLabClient,
        project: str,
        **kwargs: Any,
    ) -> ToolResult:
        limit = kwargs.get("limit", 20)

        # Reverse map for displaying level names
        level_names = {
            0: "no_access",
            30: "developer",
            40: "maintainer",
        }

        protected_tags = [
            tag async for tag in
            client.paginate(f"/projects/{project}/protected_tags", limit=limit)
        ]

        if not protected_tags:
            return ToolResult(output="No protected tag patterns found")

        lines = [f"Found {len(protected_tags)} protected tag pattern(s):"]
        for tag in protected_tags:
            name = tag.get("name", "")

            # Get create access level
            create_access_levels = tag.get("create_access_levels", [])
            if create_access_levels:
                level_value = create_access_levels[0].get("access_level", 40)
                level_name = level_names.get(level_value, f"level_{level_value}")
            else:
                level_name = "maintainer"

            lines.append(f"  {name} (create: {level_name})")

        return ToolResult(output="\n".join(lines))
