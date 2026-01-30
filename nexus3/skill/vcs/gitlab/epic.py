"""GitLab epic management skill."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nexus3.core.types import ToolResult
from nexus3.skill.vcs.gitlab.base import GitLabSkill
from nexus3.skill.vcs.gitlab.client import GitLabClient

if TYPE_CHECKING:
    pass


class GitLabEpicSkill(GitLabSkill):
    """Create, view, update, and manage GitLab epics (group-level)."""

    @property
    def name(self) -> str:
        return "gitlab_epic"

    @property
    def description(self) -> str:
        return "Create, view, update, and manage GitLab epics (group-level feature)"

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
                        "update",
                        "close",
                        "reopen",
                        "add-issue",
                        "remove-issue",
                        "list-issues",
                    ],
                    "description": "Action to perform",
                },
                "instance": {
                    "type": "string",
                    "description": "GitLab instance name (uses default if omitted)",
                },
                "group": {
                    "type": "string",
                    "description": "Group path (e.g., 'mygroup' or 'parent/subgroup'). Required.",
                },
                "iid": {
                    "type": "integer",
                    "description": "Epic IID (required for most actions)",
                },
                "title": {
                    "type": "string",
                    "description": "Epic title (required for create)",
                },
                "description": {
                    "type": "string",
                    "description": "Epic description (markdown supported)",
                },
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Labels to apply",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date (YYYY-MM-DD)",
                },
                "due_date": {
                    "type": "string",
                    "description": "Due date (YYYY-MM-DD)",
                },
                "parent_id": {
                    "type": "integer",
                    "description": "Parent epic ID for hierarchy",
                },
                "issue_id": {
                    "type": "integer",
                    "description": "Issue ID to add/remove",
                },
                "epic_issue_id": {
                    "type": "integer",
                    "description": "Epic-issue link ID for removal",
                },
                "state": {
                    "type": "string",
                    "enum": ["opened", "closed", "all"],
                    "description": "Filter by state",
                },
                "author": {
                    "type": "string",
                    "description": "Filter by author username",
                },
                "search": {
                    "type": "string",
                    "description": "Search in title and description",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results (default: 20)",
                },
            },
            "required": ["action", "group"],
        }

    async def _execute_impl(
        self,
        client: GitLabClient,
        **kwargs: Any,
    ) -> ToolResult:
        action = kwargs.get("action", "")
        group = kwargs.get("group")

        if not group:
            return ToolResult(error="group parameter is required")

        group_encoded = client._encode_path(group)

        # Filter out consumed kwargs to avoid passing them twice
        excluded = ("action", "group", "instance", "iid", "issue_id", "epic_issue_id")
        filtered = {k: v for k, v in kwargs.items() if k not in excluded}

        match action:
            case "list":
                return await self._list_epics(client, group_encoded, **filtered)
            case "get":
                iid = kwargs.get("iid")
                if not iid:
                    return ToolResult(error="iid parameter required for get action")
                return await self._get_epic(client, group_encoded, iid)
            case "create":
                title = kwargs.get("title")
                if not title:
                    return ToolResult(error="title parameter required for create action")
                return await self._create_epic(client, group_encoded, **filtered)
            case "update":
                iid = kwargs.get("iid")
                if not iid:
                    return ToolResult(error="iid parameter required for update action")
                return await self._update_epic(client, group_encoded, iid, **filtered)
            case "close":
                iid = kwargs.get("iid")
                if not iid:
                    return ToolResult(error="iid parameter required for close action")
                return await self._close_epic(client, group_encoded, iid)
            case "reopen":
                iid = kwargs.get("iid")
                if not iid:
                    return ToolResult(error="iid parameter required for reopen action")
                return await self._reopen_epic(client, group_encoded, iid)
            case "add-issue":
                iid = kwargs.get("iid")
                issue_id = kwargs.get("issue_id")
                if not iid:
                    return ToolResult(error="iid parameter required for add-issue action")
                if not issue_id:
                    return ToolResult(error="issue_id parameter required for add-issue action")
                return await self._add_issue(client, group_encoded, iid, issue_id)
            case "remove-issue":
                iid = kwargs.get("iid")
                epic_issue_id = kwargs.get("epic_issue_id")
                if not iid:
                    return ToolResult(error="iid parameter required for remove-issue action")
                if not epic_issue_id:
                    return ToolResult(
                        error="epic_issue_id parameter required for remove-issue action"
                    )
                return await self._remove_issue(client, group_encoded, iid, epic_issue_id)
            case "list-issues":
                iid = kwargs.get("iid")
                if not iid:
                    return ToolResult(error="iid parameter required for list-issues action")
                return await self._list_issues(client, group_encoded, iid, **filtered)
            case _:
                return ToolResult(error=f"Unknown action: {action}")

    async def _list_epics(
        self,
        client: GitLabClient,
        group: str,
        **kwargs: Any,
    ) -> ToolResult:
        params: dict[str, Any] = {}

        if state := kwargs.get("state"):
            params["state"] = state
        if labels := kwargs.get("labels"):
            params["labels"] = ",".join(labels)
        if author := kwargs.get("author"):
            params["author_username"] = author
        if search := kwargs.get("search"):
            params["search"] = search

        limit = kwargs.get("limit", 20)

        epics = [
            epic async for epic in
            client.paginate(f"/groups/{group}/epics", limit=limit, **params)
        ]

        if not epics:
            return ToolResult(output="No epics found")

        lines = [f"Found {len(epics)} epic(s):"]
        for epic in epics:
            state_emoji = "🟢" if epic.get("state") == "opened" else "🔴"
            date_range = ""
            if epic.get("start_date") or epic.get("due_date"):
                start = epic.get("start_date", "?")
                end = epic.get("due_date", "?")
                date_range = f" ({start} → {end})"
            lines.append(f"  {state_emoji} #{epic['iid']} {epic['title']}{date_range}")

        return ToolResult(output="\n".join(lines))

    async def _get_epic(
        self,
        client: GitLabClient,
        group: str,
        iid: int,
    ) -> ToolResult:
        epic = await client.get(f"/groups/{group}/epics/{iid}")

        state_emoji = "🟢" if epic.get("state") == "opened" else "🔴"
        lines = [
            f"# {state_emoji} Epic #{epic['iid']}: {epic['title']}",
            "",
            f"State: {epic.get('state', 'unknown')}",
            f"Author: @{epic.get('author', {}).get('username', 'unknown')}",
        ]

        if epic.get("start_date"):
            lines.append(f"Start Date: {epic['start_date']}")
        if epic.get("due_date"):
            lines.append(f"Due Date: {epic['due_date']}")

        if epic.get("labels"):
            lines.append(f"Labels: {', '.join(epic['labels'])}")

        if epic.get("parent"):
            parent = epic["parent"]
            lines.append(f"Parent Epic: #{parent.get('iid', '?')} {parent.get('title', 'unknown')}")

        lines.append("")

        if epic.get("description"):
            lines.append("## Description")
            lines.append(epic["description"])
            lines.append("")

        lines.append(f"URL: {epic.get('web_url', 'N/A')}")

        return ToolResult(output="\n".join(lines))

    async def _create_epic(
        self,
        client: GitLabClient,
        group: str,
        **kwargs: Any,
    ) -> ToolResult:
        data: dict[str, Any] = {
            "title": kwargs["title"],
        }

        if description := kwargs.get("description"):
            data["description"] = description
        if labels := kwargs.get("labels"):
            data["labels"] = ",".join(labels)
        if start_date := kwargs.get("start_date"):
            data["start_date"] = start_date
        if due_date := kwargs.get("due_date"):
            data["due_date"] = due_date
        if parent_id := kwargs.get("parent_id"):
            data["parent_id"] = parent_id

        epic = await client.post(f"/groups/{group}/epics", **data)

        return ToolResult(
            output=f"Created epic #{epic['iid']}: {epic['title']}"
        )

    async def _update_epic(
        self,
        client: GitLabClient,
        group: str,
        iid: int,
        **kwargs: Any,
    ) -> ToolResult:
        data: dict[str, Any] = {}

        if title := kwargs.get("title"):
            data["title"] = title
        if description := kwargs.get("description"):
            data["description"] = description
        if labels := kwargs.get("labels"):
            data["labels"] = ",".join(labels)
        if start_date := kwargs.get("start_date"):
            data["start_date"] = start_date
        if due_date := kwargs.get("due_date"):
            data["due_date"] = due_date

        if not data:
            return ToolResult(error="No fields to update")

        epic = await client.put(f"/groups/{group}/epics/{iid}", **data)

        return ToolResult(output=f"Updated epic #{epic['iid']}: {epic['title']}")

    async def _close_epic(
        self,
        client: GitLabClient,
        group: str,
        iid: int,
    ) -> ToolResult:
        epic = await client.put(f"/groups/{group}/epics/{iid}", state_event="close")
        return ToolResult(output=f"Closed epic #{epic['iid']}: {epic['title']}")

    async def _reopen_epic(
        self,
        client: GitLabClient,
        group: str,
        iid: int,
    ) -> ToolResult:
        epic = await client.put(f"/groups/{group}/epics/{iid}", state_event="reopen")
        return ToolResult(output=f"Reopened epic #{epic['iid']}: {epic['title']}")

    async def _add_issue(
        self,
        client: GitLabClient,
        group: str,
        iid: int,
        issue_id: int,
    ) -> ToolResult:
        result = await client.post(f"/groups/{group}/epics/{iid}/issues/{issue_id}")
        epic = result.get("epic", {})
        issue = result.get("issue", {})
        return ToolResult(
            output=f"Added issue #{issue.get('iid', issue_id)} to epic #{epic.get('iid', iid)}"
        )

    async def _remove_issue(
        self,
        client: GitLabClient,
        group: str,
        iid: int,
        epic_issue_id: int,
    ) -> ToolResult:
        result = await client.delete(f"/groups/{group}/epics/{iid}/issues/{epic_issue_id}")
        epic = result.get("epic", {}) if result else {}
        issue = result.get("issue", {}) if result else {}
        return ToolResult(
            output=f"Removed issue #{issue.get('iid', '?')} from epic #{epic.get('iid', iid)}"
        )

    async def _list_issues(
        self,
        client: GitLabClient,
        group: str,
        iid: int,
        **kwargs: Any,
    ) -> ToolResult:
        limit = kwargs.get("limit", 20)

        issues = [
            issue async for issue in
            client.paginate(f"/groups/{group}/epics/{iid}/issues", limit=limit)
        ]

        if not issues:
            return ToolResult(output=f"No issues linked to epic #{iid}")

        lines = [f"Epic #{iid} has {len(issues)} linked issue(s):"]
        for issue in issues:
            state_emoji = "🟢" if issue.get("state") == "opened" else "🔴"
            project_path = issue.get("project", {}).get("path_with_namespace", "")
            lines.append(f"  {state_emoji} {project_path}#{issue['iid']} {issue['title']}")

        return ToolResult(output="\n".join(lines))
