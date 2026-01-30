"""GitLab merge request skill."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nexus3.core.types import ToolResult
from nexus3.skill.vcs.gitlab.base import GitLabSkill
from nexus3.skill.vcs.gitlab.client import GitLabClient

if TYPE_CHECKING:
    pass


class GitLabMRSkill(GitLabSkill):
    """Create, view, update, and manage GitLab merge requests."""

    @property
    def name(self) -> str:
        return "gitlab_mr"

    @property
    def description(self) -> str:
        return "Create, view, update, and manage GitLab merge requests"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "get", "create", "update", "merge", "close", "reopen", "comment"],
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
                    "description": "MR IID (required for get/update/merge/close/reopen/comment)",
                },
                "title": {
                    "type": "string",
                    "description": "MR title (required for create)",
                },
                "description": {
                    "type": "string",
                    "description": "MR description (markdown supported)",
                },
                "source_branch": {
                    "type": "string",
                    "description": "Source branch (required for create)",
                },
                "target_branch": {
                    "type": "string",
                    "description": "Target branch (default: default branch)",
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
                "reviewers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Usernames to add as reviewers",
                },
                "draft": {
                    "type": "boolean",
                    "description": "Create as draft MR",
                },
                "squash": {
                    "type": "boolean",
                    "description": "Squash commits on merge",
                },
                "remove_source_branch": {
                    "type": "boolean",
                    "description": "Remove source branch after merge",
                },
                "state": {
                    "type": "string",
                    "enum": ["opened", "closed", "merged", "all"],
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
                return await self._list_mrs(client, project_encoded, **filtered)
            case "get":
                iid = kwargs.get("iid")
                if not iid:
                    return ToolResult(error="iid parameter required for get action")
                return await self._get_mr(client, project_encoded, iid)
            case "create":
                source = kwargs.get("source_branch")
                title = kwargs.get("title")
                if not source:
                    return ToolResult(error="source_branch required for create action")
                if not title:
                    return ToolResult(error="title required for create action")
                return await self._create_mr(client, project_encoded, **filtered)
            case "update":
                iid = kwargs.get("iid")
                if not iid:
                    return ToolResult(error="iid parameter required for update action")
                return await self._update_mr(client, project_encoded, iid, **filtered)
            case "merge":
                iid = kwargs.get("iid")
                if not iid:
                    return ToolResult(error="iid parameter required for merge action")
                return await self._merge_mr(client, project_encoded, iid, **filtered)
            case "close":
                iid = kwargs.get("iid")
                if not iid:
                    return ToolResult(error="iid parameter required for close action")
                return await self._close_mr(client, project_encoded, iid)
            case "reopen":
                iid = kwargs.get("iid")
                if not iid:
                    return ToolResult(error="iid parameter required for reopen action")
                return await self._reopen_mr(client, project_encoded, iid)
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

    async def _list_mrs(
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

        mrs = [
            mr async for mr in
            client.paginate(f"/projects/{project}/merge_requests", limit=limit, **params)
        ]

        if not mrs:
            return ToolResult(output="No merge requests found")

        lines = [f"Found {len(mrs)} merge request(s):"]
        for mr in mrs:
            state_icons = {
                "opened": "🟢",
                "closed": "🔴",
                "merged": "🟣",
            }
            state_icon = state_icons.get(mr["state"], "❓")
            draft = "📝 " if mr.get("draft") else ""
            lines.append(f"  {state_icon} {draft}!{mr['iid']}: {mr['title']}")
            lines.append(f"      {mr['source_branch']} → {mr['target_branch']}")

        return ToolResult(output="\n".join(lines))

    async def _get_mr(
        self,
        client: GitLabClient,
        project: str,
        iid: int,
    ) -> ToolResult:
        mr = await client.get(f"/projects/{project}/merge_requests/{iid}")

        lines = [
            f"# {mr['title']}",
            "",
            f"IID: !{mr['iid']} | State: {mr['state']} | Author: @{mr['author']['username']}",
            f"Branch: {mr['source_branch']} → {mr['target_branch']}",
            f"Created: {mr['created_at']} | Updated: {mr['updated_at']}",
        ]

        if mr.get("draft"):
            lines.append("Status: DRAFT")
        if mr.get("labels"):
            lines.append(f"Labels: {', '.join(mr['labels'])}")
        if mr.get("assignees"):
            assignees = [f"@{a['username']}" for a in mr["assignees"]]
            lines.append(f"Assignees: {', '.join(assignees)}")
        if mr.get("reviewers"):
            reviewers = [f"@{r['username']}" for r in mr["reviewers"]]
            lines.append(f"Reviewers: {', '.join(reviewers)}")
        if mr.get("milestone"):
            lines.append(f"Milestone: {mr['milestone']['title']}")

        # Merge status
        if mr.get("merge_status"):
            lines.append(f"Merge Status: {mr['merge_status']}")
        if mr.get("has_conflicts"):
            lines.append("⚠️ Has conflicts")

        lines.append("")
        lines.append(mr.get("description") or "(no description)")
        lines.append("")
        lines.append(f"Web URL: {mr['web_url']}")

        return ToolResult(output="\n".join(lines))

    async def _create_mr(
        self,
        client: GitLabClient,
        project: str,
        **kwargs: Any,
    ) -> ToolResult:
        data: dict[str, Any] = {
            "source_branch": kwargs["source_branch"],
            "title": kwargs["title"],
        }

        if target := kwargs.get("target_branch"):
            data["target_branch"] = target
        if description := kwargs.get("description"):
            data["description"] = description
        if labels := kwargs.get("labels"):
            data["labels"] = ",".join(labels)
        if kwargs.get("draft"):
            data["draft"] = True
        if kwargs.get("squash"):
            data["squash"] = True
        if kwargs.get("remove_source_branch"):
            data["remove_source_branch"] = True

        mr = await client.post(f"/projects/{project}/merge_requests", **data)

        return ToolResult(
            output=f"Created MR !{mr['iid']}: {mr['title']}\n{mr['web_url']}"
        )

    async def _update_mr(
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
        if target := kwargs.get("target_branch"):
            data["target_branch"] = target

        if not data:
            return ToolResult(error="No fields to update")

        mr = await client.put(f"/projects/{project}/merge_requests/{iid}", **data)

        return ToolResult(output=f"Updated MR !{mr['iid']}: {mr['title']}")

    async def _merge_mr(
        self,
        client: GitLabClient,
        project: str,
        iid: int,
        **kwargs: Any,
    ) -> ToolResult:
        data: dict[str, Any] = {}

        if kwargs.get("squash"):
            data["squash"] = True
        if kwargs.get("remove_source_branch"):
            data["should_remove_source_branch"] = True

        mr = await client.put(f"/projects/{project}/merge_requests/{iid}/merge", **data)

        return ToolResult(output=f"Merged MR !{mr['iid']}: {mr['title']}")

    async def _close_mr(
        self,
        client: GitLabClient,
        project: str,
        iid: int,
    ) -> ToolResult:
        await client.put(
            f"/projects/{project}/merge_requests/{iid}", state_event="close"
        )
        return ToolResult(output=f"Closed MR !{iid}")

    async def _reopen_mr(
        self,
        client: GitLabClient,
        project: str,
        iid: int,
    ) -> ToolResult:
        await client.put(
            f"/projects/{project}/merge_requests/{iid}", state_event="reopen"
        )
        return ToolResult(output=f"Reopened MR !{iid}")

    async def _add_comment(
        self,
        client: GitLabClient,
        project: str,
        iid: int,
        body: str,
    ) -> ToolResult:
        await client.post(f"/projects/{project}/merge_requests/{iid}/notes", body=body)
        return ToolResult(output=f"Added comment to MR !{iid}")
