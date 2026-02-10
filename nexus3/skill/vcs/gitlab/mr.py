"""GitLab merge request skill."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nexus3.core.types import ToolResult
from nexus3.skill.vcs.gitlab.base import GitLabSkill
from nexus3.skill.vcs.gitlab.client import GitLabClient

if TYPE_CHECKING:
    pass


class GitLabMRSkill(GitLabSkill):
    """Create, view, update, and manage GitLab merge requests.

    Actions: list, get, create, update, merge, close, reopen, comment, diff,
    commits, pipelines. Project is auto-detected from git remote. Use diff to
    review changes, pipelines to check CI status.
    """

    @property
    def name(self) -> str:
        return "gitlab_mr"

    @property
    def description(self) -> str:
        return (
            "Create, view, update, and manage GitLab merge requests. "
            "Actions: list, get, create, update, merge, close, reopen, "
            "comment, diff, commits, pipelines. "
            "List works cross-project when project is omitted (e.g., "
            "'list all my open MRs'). Other actions auto-detect "
            "project from git remote if omitted."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "list", "get", "create", "update", "merge",
                        "close", "reopen", "comment", "diff", "commits", "pipelines",
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
                        "Auto-detected from git remote if omitted. "
                        "For list: omit for cross-project search, "
                        "or pass 'this' to infer from git remote."
                    ),
                },
                "iid": {
                    "type": "integer",
                    "description": (
                        "MR IID (required for get/update/merge/close/reopen/"
                        "comment/diff/commits/pipelines)"
                    ),
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
                    "description": (
                        "GitLab usernames to assign (not emails). "
                        "Use 'me' for yourself."
                    ),
                },
                "reviewers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "GitLab usernames to add as reviewers (not emails). "
                        "Use 'me' for yourself."
                    ),
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
                "assignee_username": {
                    "type": "string",
                    "description": (
                        "Filter MRs by assignee username (list action). "
                        "Use 'me' for yourself, or 'None' for unassigned."
                    ),
                },
                "author_username": {
                    "type": "string",
                    "description": (
                        "Filter MRs by author username (list action). "
                        "Use 'me' for yourself."
                    ),
                },
                "reviewer_username": {
                    "type": "string",
                    "description": (
                        "Filter MRs by reviewer username (list action). "
                        "Use 'me' for yourself."
                    ),
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

        # Filter out consumed kwargs to avoid passing them twice
        # Note: iid is filtered here because some methods receive it positionally
        consumed = ("action", "project", "instance", "iid")
        filtered = {k: v for k, v in kwargs.items() if k not in consumed}

        # List supports cross-project queries (project optional)
        if action == "list":
            project_raw = kwargs.get("project")
            if project_raw:
                # Explicit project or "this" (resolve from git remote)
                project_encoded = client._encode_path(
                    self._resolve_project(project_raw)
                )
            else:
                # No project — use global endpoint (cross-project)
                project_encoded = None
            return await self._list_mrs(client, project_encoded, **filtered)

        # All other actions require a project
        project = self._resolve_project(kwargs.get("project"))
        project_encoded = client._encode_path(project)

        match action:
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
            case "diff":
                iid = kwargs.get("iid")
                if not iid:
                    return ToolResult(error="iid parameter required for diff action")
                return await self._get_diff(client, project_encoded, iid)
            case "commits":
                iid = kwargs.get("iid")
                if not iid:
                    return ToolResult(error="iid parameter required for commits action")
                return await self._list_commits(client, project_encoded, iid)
            case "pipelines":
                iid = kwargs.get("iid")
                if not iid:
                    return ToolResult(error="iid parameter required for pipelines action")
                return await self._list_pipelines(client, project_encoded, iid)
            case _:
                return ToolResult(error=f"Unknown action: {action}")

    async def _list_mrs(
        self,
        client: GitLabClient,
        project: str | None,
        **kwargs: Any,
    ) -> ToolResult:
        params: dict[str, Any] = {}

        if state := kwargs.get("state"):
            params["state"] = state
        if search := kwargs.get("search"):
            params["search"] = search
        if labels := kwargs.get("labels"):
            params["labels"] = ",".join(labels)
        if assignee := kwargs.get("assignee_username"):
            if assignee.lower() == "me":
                params["assignee_username"] = await self._resolve_me_username(client)
            else:
                params["assignee_username"] = assignee
        if author := kwargs.get("author_username"):
            if author.lower() == "me":
                params["author_username"] = await self._resolve_me_username(client)
            else:
                params["author_username"] = author
        if reviewer := kwargs.get("reviewer_username"):
            if reviewer.lower() == "me":
                params["reviewer_username"] = await self._resolve_me_username(client)
            else:
                params["reviewer_username"] = reviewer

        limit = kwargs.get("limit", 20)

        # Use global endpoint when no project specified
        endpoint = f"/projects/{project}/merge_requests" if project else "/merge_requests"
        mrs = [
            mr async for mr in
            client.paginate(endpoint, limit=limit, **params)
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
            # Include project path for cross-project listings
            if not project and mr.get("references", {}).get("full"):
                mr_ref = mr["references"]["full"]
            else:
                mr_ref = f"!{mr['iid']}"
            lines.append(f"  {state_icon} {draft}{mr_ref}: {mr['title']}")
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
        if assignees := kwargs.get("assignees"):
            data["assignee_ids"] = await self._resolve_user_ids(client, assignees)
        if reviewers := kwargs.get("reviewers"):
            data["reviewer_ids"] = await self._resolve_user_ids(client, reviewers)

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
        if "assignees" in kwargs:
            assignees = kwargs["assignees"]
            if assignees:
                data["assignee_ids"] = await self._resolve_user_ids(client, assignees)
            else:
                data["assignee_ids"] = []  # Clear assignees
        if "reviewers" in kwargs:
            reviewers = kwargs["reviewers"]
            if reviewers:
                data["reviewer_ids"] = await self._resolve_user_ids(client, reviewers)
            else:
                data["reviewer_ids"] = []  # Clear reviewers

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

    async def _get_diff(
        self,
        client: GitLabClient,
        project: str,
        iid: int,
    ) -> ToolResult:
        """Get MR diff (files changed with stats)."""
        # Use /diffs endpoint for cleaner diff data
        diffs = await client.get(f"/projects/{project}/merge_requests/{iid}/diffs")

        if not diffs:
            return ToolResult(output=f"MR !{iid} has no changes")

        total_additions = 0
        total_deletions = 0
        lines = []

        for diff in diffs:
            old_path = diff.get("old_path", "")
            new_path = diff.get("new_path", "")
            new_file = diff.get("new_file", False)
            deleted_file = diff.get("deleted_file", False)
            renamed_file = diff.get("renamed_file", False)

            # Count additions/deletions from diff content
            diff_content = diff.get("diff", "")
            additions = diff_content.count("\n+") - diff_content.count("\n+++")
            deletions = diff_content.count("\n-") - diff_content.count("\n---")
            total_additions += additions
            total_deletions += deletions

            # Determine change type indicator
            if new_file:
                indicator = "A"
                path_display = new_path
            elif deleted_file:
                indicator = "D"
                path_display = old_path
            elif renamed_file:
                indicator = "R"
                path_display = f"{new_path} (renamed from {old_path})"
            else:
                indicator = "M"
                path_display = new_path

            lines.append(f"  {indicator} {path_display} (+{additions}/-{deletions})")

        header = f"MR !{iid} Changes ({len(diffs)} file(s), +{total_additions}/-{total_deletions}):"
        return ToolResult(output="\n".join([header] + lines))

    async def _list_commits(
        self,
        client: GitLabClient,
        project: str,
        iid: int,
    ) -> ToolResult:
        """List commits in MR."""
        commits = await client.get(f"/projects/{project}/merge_requests/{iid}/commits")

        if not commits:
            return ToolResult(output=f"MR !{iid} has no commits")

        lines = [f"MR !{iid} has {len(commits)} commit(s):"]
        for commit in commits:
            short_sha = commit["short_id"]
            author = commit.get("author_name", "unknown")
            # Get first line of commit message
            message = commit.get("title", commit.get("message", "")).split("\n")[0]
            lines.append(f"  {short_sha} @{author}: {message}")

        return ToolResult(output="\n".join(lines))

    async def _list_pipelines(
        self,
        client: GitLabClient,
        project: str,
        iid: int,
    ) -> ToolResult:
        """List pipelines for MR."""
        pipelines = await client.get(f"/projects/{project}/merge_requests/{iid}/pipelines")

        if not pipelines:
            return ToolResult(output=f"MR !{iid} has no pipelines")

        status_icons = {
            "success": "🟢",
            "passed": "🟢",
            "failed": "🔴",
            "running": "🔵",
            "pending": "🟡",
            "canceled": "⚪",
            "skipped": "⚪",
            "manual": "🟠",
            "created": "🟡",
        }

        lines = [f"MR !{iid} has {len(pipelines)} pipeline(s):"]
        for pipeline in pipelines:
            status = pipeline.get("status", "unknown")
            icon = status_icons.get(status, "❓")
            pipeline_id = pipeline["id"]
            ref = pipeline.get("ref", "")
            created_at = pipeline.get("created_at", "")
            lines.append(f"  {icon} #{pipeline_id} {status} ({ref}) - {created_at}")

        return ToolResult(output="\n".join(lines))
