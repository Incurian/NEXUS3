"""GitLab issue management skill."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from nexus3.core.types import ToolResult
from nexus3.skill.vcs.gitlab.base import GitLabSkill
from nexus3.skill.vcs.gitlab.client import GitLabClient

if TYPE_CHECKING:
    pass


class GitLabIssueSkill(GitLabSkill):
    """Create, view, update, and manage GitLab issues."""

    @property
    def name(self) -> str:
        return "gitlab_issue"

    @property
    def description(self) -> str:
        return "Create, view, update, and manage GitLab issues"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "get", "create", "update", "close", "reopen", "comment"],
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
                "iid": {
                    "type": "integer",
                    "description": "Issue IID (required for get/update/close/reopen/comment)",
                },
                "title": {
                    "type": "string",
                    "description": "Issue title (required for create)",
                },
                "description": {
                    "type": "string",
                    "description": "Issue description (markdown supported)",
                },
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Labels to apply",
                },
                "assignees": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Usernames to assign",
                },
                "state": {
                    "type": "string",
                    "enum": ["opened", "closed", "all"],
                    "description": "Filter by state (default: opened)",
                },
                "search": {
                    "type": "string",
                    "description": "Search in title and description",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results (default: 20)",
                },
                "body": {
                    "type": "string",
                    "description": "Comment body (for comment action)",
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
                return await self._list_issues(client, project_encoded, **filtered)
            case "get":
                iid = kwargs.get("iid")
                if not iid:
                    return ToolResult(error="iid parameter required for get action")
                return await self._get_issue(client, project_encoded, iid)
            case "create":
                title = kwargs.get("title")
                if not title:
                    return ToolResult(error="title parameter required for create action")
                return await self._create_issue(client, project_encoded, **filtered)
            case "update":
                iid = kwargs.get("iid")
                if not iid:
                    return ToolResult(error="iid parameter required for update action")
                return await self._update_issue(client, project_encoded, iid, **filtered)
            case "close":
                iid = kwargs.get("iid")
                if not iid:
                    return ToolResult(error="iid parameter required for close action")
                return await self._close_issue(client, project_encoded, iid)
            case "reopen":
                iid = kwargs.get("iid")
                if not iid:
                    return ToolResult(error="iid parameter required for reopen action")
                return await self._reopen_issue(client, project_encoded, iid)
            case "comment":
                iid = kwargs.get("iid")
                body = kwargs.get("body")
                if not iid:
                    return ToolResult(error="iid parameter required for comment action")
                if not body:
                    return ToolResult(error="body parameter required for comment action")
                return await self._add_comment(client, project_encoded, iid, body)
            case _:
                return ToolResult(error=f"Unknown action: {action}")

    async def _list_issues(
        self,
        client: GitLabClient,
        project: str,
        **kwargs: Any,
    ) -> ToolResult:
        params: dict[str, Any] = {}

        if state := kwargs.get("state"):
            params["state"] = state
        if search := kwargs.get("search"):
            params["search"] = search
        if labels := kwargs.get("labels"):
            params["labels"] = ",".join(labels)

        limit = kwargs.get("limit", 20)

        issues = [
            issue async for issue in
            client.paginate(f"/projects/{project}/issues", limit=limit, **params)
        ]

        if not issues:
            return ToolResult(output="No issues found")

        lines = [f"Found {len(issues)} issue(s):"]
        for issue in issues:
            state_icon = "🟢" if issue["state"] == "opened" else "🔴"
            labels_str = f" [{', '.join(issue.get('labels', []))}]" if issue.get("labels") else ""
            lines.append(f"  {state_icon} #{issue['iid']}: {issue['title']}{labels_str}")

        return ToolResult(output="\n".join(lines))

    async def _get_issue(
        self,
        client: GitLabClient,
        project: str,
        iid: int,
    ) -> ToolResult:
        issue = await client.get(f"/projects/{project}/issues/{iid}")

        lines = [
            f"# {issue['title']}",
            "",
            f"IID: #{issue['iid']} | State: {issue['state']} | Author: @{issue['author']['username']}",
            f"Created: {issue['created_at']} | Updated: {issue['updated_at']}",
        ]

        if issue.get("labels"):
            lines.append(f"Labels: {', '.join(issue['labels'])}")
        if issue.get("assignees"):
            assignees = [f"@{a['username']}" for a in issue["assignees"]]
            lines.append(f"Assignees: {', '.join(assignees)}")
        if issue.get("milestone"):
            lines.append(f"Milestone: {issue['milestone']['title']}")
        if issue.get("due_date"):
            lines.append(f"Due: {issue['due_date']}")

        lines.append("")
        lines.append(issue.get("description") or "(no description)")
        lines.append("")
        lines.append(f"Web URL: {issue['web_url']}")

        return ToolResult(output="\n".join(lines))

    async def _create_issue(
        self,
        client: GitLabClient,
        project: str,
        **kwargs: Any,
    ) -> ToolResult:
        data: dict[str, Any] = {"title": kwargs["title"]}

        if description := kwargs.get("description"):
            data["description"] = description
        if labels := kwargs.get("labels"):
            data["labels"] = ",".join(labels)

        issue = await client.post(f"/projects/{project}/issues", **data)

        return ToolResult(
            output=f"Created issue #{issue['iid']}: {issue['title']}\n{issue['web_url']}"
        )

    async def _update_issue(
        self,
        client: GitLabClient,
        project: str,
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

        if not data:
            return ToolResult(error="No fields to update")

        issue = await client.put(f"/projects/{project}/issues/{iid}", **data)

        return ToolResult(output=f"Updated issue #{issue['iid']}: {issue['title']}")

    async def _close_issue(
        self,
        client: GitLabClient,
        project: str,
        iid: int,
    ) -> ToolResult:
        issue = await client.put(f"/projects/{project}/issues/{iid}", state_event="close")
        return ToolResult(output=f"Closed issue #{issue['iid']}")

    async def _reopen_issue(
        self,
        client: GitLabClient,
        project: str,
        iid: int,
    ) -> ToolResult:
        issue = await client.put(f"/projects/{project}/issues/{iid}", state_event="reopen")
        return ToolResult(output=f"Reopened issue #{issue['iid']}")

    async def _add_comment(
        self,
        client: GitLabClient,
        project: str,
        iid: int,
        body: str,
    ) -> ToolResult:
        await client.post(f"/projects/{project}/issues/{iid}/notes", body=body)
        return ToolResult(output=f"Added comment to issue #{iid}")
