"""GitLab milestone management skill."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nexus3.core.types import ToolResult
from nexus3.skill.vcs.gitlab.base import GitLabSkill
from nexus3.skill.vcs.gitlab.client import GitLabClient

if TYPE_CHECKING:
    pass


class GitLabMilestoneSkill(GitLabSkill):
    """Create, view, update, and manage GitLab milestones (project or group level)."""

    @property
    def name(self) -> str:
        return "gitlab_milestone"

    @property
    def description(self) -> str:
        return "Create, view, update, and manage GitLab milestones (project or group level)"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "list", "get", "create", "update", "close",
                        "issues", "merge-requests",
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
                        "Either project or group required."
                    ),
                },
                "group": {
                    "type": "string",
                    "description": (
                        "Group path (e.g., 'my-group'). "
                        "Either project or group required."
                    ),
                },
                "milestone_id": {
                    "type": "integer",
                    "description": "Milestone ID (required for most actions)",
                },
                "title": {
                    "type": "string",
                    "description": "Milestone title (required for create)",
                },
                "description": {
                    "type": "string",
                    "description": "Milestone description",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date (YYYY-MM-DD)",
                },
                "due_date": {
                    "type": "string",
                    "description": "Due date (YYYY-MM-DD)",
                },
                "state": {
                    "type": "string",
                    "enum": ["active", "closed"],
                    "description": "Filter by state",
                },
                "search": {
                    "type": "string",
                    "description": "Search by title",
                },
            },
            "required": ["action"],
        }

    def _get_base_path(
        self,
        client: GitLabClient,
        project: str | None,
        group: str | None,
    ) -> str:
        """Get API base path for project or group milestones."""
        if group:
            return f"/groups/{client._encode_path(group)}"
        if project:
            resolved = self._resolve_project(project)
            return f"/projects/{client._encode_path(resolved)}"
        raise ValueError("Either 'project' or 'group' parameter is required")

    async def _execute_impl(
        self,
        client: GitLabClient,
        **kwargs: Any,
    ) -> ToolResult:
        action = kwargs.get("action", "")
        project = kwargs.get("project")
        group = kwargs.get("group")

        # Filter out consumed kwargs to avoid passing them twice
        excluded = ("action", "project", "group", "instance", "milestone_id")
        filtered = {k: v for k, v in kwargs.items() if k not in excluded}

        match action:
            case "list":
                return await self._list_milestones(client, project, group, **filtered)
            case "get":
                milestone_id = kwargs.get("milestone_id")
                if not milestone_id:
                    return ToolResult(error="milestone_id parameter required for get action")
                return await self._get_milestone(client, project, group, milestone_id)
            case "create":
                title = kwargs.get("title")
                if not title:
                    return ToolResult(error="title parameter required for create action")
                return await self._create_milestone(client, project, group, **filtered)
            case "update":
                milestone_id = kwargs.get("milestone_id")
                if not milestone_id:
                    return ToolResult(error="milestone_id parameter required for update action")
                return await self._update_milestone(
                    client, project, group, milestone_id, **filtered
                )
            case "close":
                milestone_id = kwargs.get("milestone_id")
                if not milestone_id:
                    return ToolResult(error="milestone_id parameter required for close action")
                return await self._close_milestone(client, project, group, milestone_id)
            case "issues":
                milestone_id = kwargs.get("milestone_id")
                if not milestone_id:
                    return ToolResult(error="milestone_id parameter required for issues action")
                return await self._list_milestone_issues(client, project, group, milestone_id)
            case "merge-requests":
                milestone_id = kwargs.get("milestone_id")
                if not milestone_id:
                    return ToolResult(
                        error="milestone_id parameter required for merge-requests action"
                    )
                return await self._list_milestone_merge_requests(
                    client, project, group, milestone_id
                )
            case _:
                return ToolResult(error=f"Unknown action: {action}")

    async def _list_milestones(
        self,
        client: GitLabClient,
        project: str | None,
        group: str | None,
        **kwargs: Any,
    ) -> ToolResult:
        base_path = self._get_base_path(client, project, group)
        params: dict[str, Any] = {}

        if state := kwargs.get("state"):
            params["state"] = state
        if search := kwargs.get("search"):
            params["search"] = search

        milestones = [
            ms async for ms in
            client.paginate(f"{base_path}/milestones", limit=100, **params)
        ]

        if not milestones:
            return ToolResult(output="No milestones found")

        lines = [f"Found {len(milestones)} milestone(s):"]
        for ms in milestones:
            # green/red circle for active/inactive
            state_icon = "\U0001f7e2" if ms.get("state") == "active" else "\U0001f534"
            title = ms.get("title", "Untitled")

            # Date range
            start = ms.get("start_date", "")
            due = ms.get("due_date", "")
            date_range = ""
            if start and due:
                date_range = f" ({start} to {due})"
            elif due:
                date_range = f" (due {due})"
            elif start:
                date_range = f" (started {start})"

            lines.append(f"  {state_icon} #{ms['id']} {title}{date_range}")

        return ToolResult(output="\n".join(lines))

    async def _get_milestone(
        self,
        client: GitLabClient,
        project: str | None,
        group: str | None,
        milestone_id: int,
    ) -> ToolResult:
        base_path = self._get_base_path(client, project, group)
        ms = await client.get(f"{base_path}/milestones/{milestone_id}")

        state_icon = "\U0001f7e2" if ms.get("state") == "active" else "\U0001f534"
        lines = [
            f"# {state_icon} {ms.get('title', 'Untitled')}",
            "",
            f"ID: {ms['id']}",
            f"IID: {ms.get('iid', 'N/A')}",
            f"State: {ms.get('state', 'unknown')}",
        ]

        if ms.get("start_date"):
            lines.append(f"Start Date: {ms['start_date']}")
        if ms.get("due_date"):
            lines.append(f"Due Date: {ms['due_date']}")

        if ms.get("description"):
            lines.append("")
            lines.append("## Description")
            lines.append(ms["description"])

        if ms.get("web_url"):
            lines.append("")
            lines.append(f"URL: {ms['web_url']}")

        return ToolResult(output="\n".join(lines))

    async def _create_milestone(
        self,
        client: GitLabClient,
        project: str | None,
        group: str | None,
        **kwargs: Any,
    ) -> ToolResult:
        base_path = self._get_base_path(client, project, group)
        data: dict[str, Any] = {
            "title": kwargs["title"],
        }

        if description := kwargs.get("description"):
            data["description"] = description
        if start_date := kwargs.get("start_date"):
            data["start_date"] = start_date
        if due_date := kwargs.get("due_date"):
            data["due_date"] = due_date

        ms = await client.post(f"{base_path}/milestones", **data)

        return ToolResult(
            output=f"Created milestone '{ms.get('title')}' (ID: {ms['id']})"
        )

    async def _update_milestone(
        self,
        client: GitLabClient,
        project: str | None,
        group: str | None,
        milestone_id: int,
        **kwargs: Any,
    ) -> ToolResult:
        base_path = self._get_base_path(client, project, group)
        data: dict[str, Any] = {}

        if title := kwargs.get("title"):
            data["title"] = title
        if description := kwargs.get("description"):
            data["description"] = description
        if start_date := kwargs.get("start_date"):
            data["start_date"] = start_date
        if due_date := kwargs.get("due_date"):
            data["due_date"] = due_date

        if not data:
            return ToolResult(error="No fields to update")

        ms = await client.put(f"{base_path}/milestones/{milestone_id}", **data)

        return ToolResult(output=f"Updated milestone '{ms.get('title')}'")

    async def _close_milestone(
        self,
        client: GitLabClient,
        project: str | None,
        group: str | None,
        milestone_id: int,
    ) -> ToolResult:
        base_path = self._get_base_path(client, project, group)
        ms = await client.put(f"{base_path}/milestones/{milestone_id}", state_event="close")
        return ToolResult(output=f"Closed milestone '{ms.get('title')}'")

    async def _list_milestone_issues(
        self,
        client: GitLabClient,
        project: str | None,
        group: str | None,
        milestone_id: int,
    ) -> ToolResult:
        base_path = self._get_base_path(client, project, group)
        issues = [
            issue async for issue in
            client.paginate(f"{base_path}/milestones/{milestone_id}/issues", limit=100)
        ]

        if not issues:
            return ToolResult(output="No issues in this milestone")

        lines = [f"Found {len(issues)} issue(s):"]
        for issue in issues:
            state_icon = "\U0001f7e2" if issue.get("state") == "opened" else "\U0001f534"
            lines.append(f"  {state_icon} #{issue['iid']} {issue.get('title', 'Untitled')}")

        return ToolResult(output="\n".join(lines))

    async def _list_milestone_merge_requests(
        self,
        client: GitLabClient,
        project: str | None,
        group: str | None,
        milestone_id: int,
    ) -> ToolResult:
        base_path = self._get_base_path(client, project, group)
        mrs = [
            mr async for mr in
            client.paginate(f"{base_path}/milestones/{milestone_id}/merge_requests", limit=100)
        ]

        if not mrs:
            return ToolResult(output="No merge requests in this milestone")

        lines = [f"Found {len(mrs)} merge request(s):"]
        for mr in mrs:
            state = mr.get("state", "unknown")
            if state == "merged":
                state_icon = "\U0001f7e3"  # purple circle
            elif state == "opened":
                state_icon = "\U0001f7e2"  # green circle
            else:
                state_icon = "\U0001f534"  # red circle
            lines.append(f"  {state_icon} !{mr['iid']} {mr.get('title', 'Untitled')}")

        return ToolResult(output="\n".join(lines))
