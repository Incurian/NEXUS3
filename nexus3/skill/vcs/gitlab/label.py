"""GitLab label management skill."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from nexus3.core.types import ToolResult
from nexus3.skill.vcs.gitlab.base import GitLabSkill
from nexus3.skill.vcs.gitlab.client import GitLabClient

if TYPE_CHECKING:
    pass


class GitLabLabelSkill(GitLabSkill):
    """Create, view, update, and delete GitLab labels."""

    @property
    def name(self) -> str:
        return "gitlab_label"

    @property
    def description(self) -> str:
        return "Create, view, update, and delete GitLab labels"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "get", "create", "update", "delete"],
                    "description": "Action to perform",
                },
                "instance": {
                    "type": "string",
                    "description": "GitLab instance name (uses default if omitted)",
                },
                "project": {
                    "type": "string",
                    "description": "Project path (e.g., 'group/repo'). Auto-detected from git remote if omitted.",
                },
                "name": {
                    "type": "string",
                    "description": "Label name (required for get/create/update/delete)",
                },
                "new_name": {
                    "type": "string",
                    "description": "New label name (for update action)",
                },
                "color": {
                    "type": "string",
                    "description": "Label color (hex, e.g., '#FF0000'). Required for create.",
                },
                "description": {
                    "type": "string",
                    "description": "Label description",
                },
                "priority": {
                    "type": "integer",
                    "description": "Label priority (lower = higher priority)",
                },
                "search": {
                    "type": "string",
                    "description": "Filter labels by search term",
                },
                "include_ancestor_groups": {
                    "type": "boolean",
                    "description": "Include labels from parent groups (default: true)",
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
                return await self._list_labels(client, project_encoded, **filtered)
            case "get":
                name = kwargs.get("name")
                if not name:
                    return ToolResult(error="name parameter required for get action")
                return await self._get_label(client, project_encoded, name)
            case "create":
                name = kwargs.get("name")
                color = kwargs.get("color")
                if not name:
                    return ToolResult(error="name parameter required for create action")
                if not color:
                    return ToolResult(error="color parameter required for create action")
                return await self._create_label(client, project_encoded, **filtered)
            case "update":
                name = kwargs.get("name")
                if not name:
                    return ToolResult(error="name parameter required for update action")
                return await self._update_label(client, project_encoded, name, **filtered)
            case "delete":
                name = kwargs.get("name")
                if not name:
                    return ToolResult(error="name parameter required for delete action")
                return await self._delete_label(client, project_encoded, name)
            case _:
                return ToolResult(error=f"Unknown action: {action}")

    async def _list_labels(
        self,
        client: GitLabClient,
        project: str,
        **kwargs: Any,
    ) -> ToolResult:
        params: dict[str, Any] = {}

        if search := kwargs.get("search"):
            params["search"] = search
        if kwargs.get("include_ancestor_groups") is False:
            params["include_ancestor_groups"] = False

        labels = [
            label async for label in
            client.paginate(f"/projects/{project}/labels", limit=100, **params)
        ]

        if not labels:
            return ToolResult(output="No labels found")

        lines = [f"Found {len(labels)} label(s):"]
        for label in labels:
            priority = f" (priority: {label['priority']})" if label.get("priority") else ""
            desc = f" - {label['description']}" if label.get("description") else ""
            lines.append(f"  {label['color']} {label['name']}{priority}{desc}")

        return ToolResult(output="\n".join(lines))

    async def _get_label(
        self,
        client: GitLabClient,
        project: str,
        name: str,
    ) -> ToolResult:
        label_encoded = client._encode_path(name)
        label = await client.get(f"/projects/{project}/labels/{label_encoded}")

        lines = [
            f"# {label['name']}",
            "",
            f"Color: {label['color']}",
            f"Text Color: {label.get('text_color', 'N/A')}",
        ]

        if label.get("description"):
            lines.append(f"Description: {label['description']}")
        if label.get("priority"):
            lines.append(f"Priority: {label['priority']}")
        if label.get("is_project_label") is not None:
            lines.append(f"Project Label: {label['is_project_label']}")

        # Usage stats
        lines.append("")
        lines.append(f"Open Issues: {label.get('open_issues_count', 0)}")
        lines.append(f"Closed Issues: {label.get('closed_issues_count', 0)}")
        lines.append(f"Open MRs: {label.get('open_merge_requests_count', 0)}")

        return ToolResult(output="\n".join(lines))

    async def _create_label(
        self,
        client: GitLabClient,
        project: str,
        **kwargs: Any,
    ) -> ToolResult:
        data: dict[str, Any] = {
            "name": kwargs["name"],
            "color": kwargs["color"],
        }

        if description := kwargs.get("description"):
            data["description"] = description
        if priority := kwargs.get("priority"):
            data["priority"] = priority

        label = await client.post(f"/projects/{project}/labels", **data)

        return ToolResult(
            output=f"Created label '{label['name']}' with color {label['color']}"
        )

    async def _update_label(
        self,
        client: GitLabClient,
        project: str,
        name: str,
        **kwargs: Any,
    ) -> ToolResult:
        label_encoded = client._encode_path(name)
        data: dict[str, Any] = {}

        if new_name := kwargs.get("new_name"):
            data["new_name"] = new_name
        if color := kwargs.get("color"):
            data["color"] = color
        if description := kwargs.get("description"):
            data["description"] = description
        if priority := kwargs.get("priority"):
            data["priority"] = priority

        if not data:
            return ToolResult(error="No fields to update")

        label = await client.put(f"/projects/{project}/labels/{label_encoded}", **data)

        return ToolResult(output=f"Updated label '{label['name']}'")

    async def _delete_label(
        self,
        client: GitLabClient,
        project: str,
        name: str,
    ) -> ToolResult:
        label_encoded = client._encode_path(name)
        await client.delete(f"/projects/{project}/labels/{label_encoded}")
        return ToolResult(output=f"Deleted label '{name}'")
