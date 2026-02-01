"""GitLab draft notes (batch review) skill."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nexus3.core.types import ToolResult
from nexus3.skill.vcs.gitlab.base import GitLabSkill
from nexus3.skill.vcs.gitlab.client import GitLabClient

if TYPE_CHECKING:
    pass


class GitLabDraftSkill(GitLabSkill):
    """Manage draft notes for batch MR reviews."""

    @property
    def name(self) -> str:
        return "gitlab_draft"

    @property
    def description(self) -> str:
        return "Manage draft notes for batch MR reviews"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "add", "update", "delete", "publish"],
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
                "iid": {
                    "type": "integer",
                    "description": "Merge request internal ID (required for all actions)",
                },
                "draft_id": {
                    "type": "integer",
                    "description": "Draft note ID (required for update/delete)",
                },
                "body": {
                    "type": "string",
                    "description": "Note content (required for add/update)",
                },
                "path": {
                    "type": "string",
                    "description": "File path in the diff (for line comments)",
                },
                "line": {
                    "type": "integer",
                    "description": "Line number (for line comments)",
                },
                "line_type": {
                    "type": "string",
                    "enum": ["new", "old"],
                    "description": "Line type: 'new' (right side) or 'old' (left side) of diff",
                },
            },
            "required": ["action", "iid"],
        }

    def _get_mr_path(self, client: GitLabClient, project: str | None) -> str:
        """Get API path for MR draft notes."""
        resolved = self._resolve_project(project)
        return f"/projects/{client._encode_path(resolved)}/merge_requests"

    async def _execute_impl(
        self,
        client: GitLabClient,
        **kwargs: Any,
    ) -> ToolResult:
        action = kwargs.get("action", "")
        project = kwargs.get("project")
        iid = kwargs.get("iid")

        if not iid:
            return ToolResult(error="iid parameter required")

        # Filter out consumed kwargs to avoid passing them twice
        filtered = {
            k: v
            for k, v in kwargs.items()
            if k not in ("action", "project", "instance", "iid", "draft_id")
        }

        match action:
            case "list":
                return await self._list_drafts(client, project, iid)
            case "add":
                body = kwargs.get("body")
                if not body:
                    return ToolResult(error="body parameter required for add action")
                return await self._add_draft(client, project, iid, **filtered)
            case "update":
                draft_id = kwargs.get("draft_id")
                body = kwargs.get("body")
                if not draft_id:
                    return ToolResult(error="draft_id parameter required for update action")
                if not body:
                    return ToolResult(error="body parameter required for update action")
                return await self._update_draft(client, project, iid, draft_id, body)
            case "delete":
                draft_id = kwargs.get("draft_id")
                if not draft_id:
                    return ToolResult(error="draft_id parameter required for delete action")
                return await self._delete_draft(client, project, iid, draft_id)
            case "publish":
                return await self._publish_drafts(client, project, iid)
            case _:
                return ToolResult(error=f"Unknown action: {action}")

    async def _list_drafts(
        self,
        client: GitLabClient,
        project: str | None,
        iid: int,
    ) -> ToolResult:
        mr_path = self._get_mr_path(client, project)
        drafts = [
            draft
            async for draft in client.paginate(
                f"{mr_path}/{iid}/draft_notes", limit=100
            )
        ]

        if not drafts:
            return ToolResult(output="No draft notes pending")

        lines = [f"Found {len(drafts)} draft note(s):"]
        for draft in drafts:
            draft_id = draft.get("id")
            note = draft.get("note", "")
            # Truncate long notes
            preview = note[:80] + "..." if len(note) > 80 else note
            preview = preview.replace("\n", " ")

            # Check if it's a line comment
            position = draft.get("position")
            location = ""
            if position:
                path = position.get("new_path") or position.get("old_path", "")
                line = position.get("new_line") or position.get("old_line", "")
                if path and line:
                    location = f" [{path}:{line}]"

            lines.append(f"  #{draft_id}{location}: {preview}")

        return ToolResult(output="\n".join(lines))

    async def _add_draft(
        self,
        client: GitLabClient,
        project: str | None,
        iid: int,
        **kwargs: Any,
    ) -> ToolResult:
        mr_path = self._get_mr_path(client, project)
        body = kwargs["body"]
        path = kwargs.get("path")
        line = kwargs.get("line")
        line_type = kwargs.get("line_type", "new")

        data: dict[str, Any] = {"note": body}

        # If path and line provided, add as file-level comment
        # For full diff position support, we'd need to fetch MR diff info
        # to get base_sha, start_sha, head_sha. For v1, support simple comments.
        if path and line:
            # Get MR to fetch SHA information for position
            mr = await client.get(f"{mr_path}/{iid}")
            diff_refs = mr.get("diff_refs", {})

            position: dict[str, Any] = {
                "base_sha": diff_refs.get("base_sha", ""),
                "start_sha": diff_refs.get("start_sha", ""),
                "head_sha": diff_refs.get("head_sha", ""),
                "position_type": "text",
                "new_path": path,
            }

            if line_type == "old":
                position["old_path"] = path
                position["old_line"] = line
            else:
                position["new_line"] = line

            data["position"] = position

        draft = await client.post(f"{mr_path}/{iid}/draft_notes", **data)

        location = ""
        if path and line:
            location = f" on {path}:{line}"

        return ToolResult(
            output=f"Added draft note #{draft.get('id')}{location}"
        )

    async def _update_draft(
        self,
        client: GitLabClient,
        project: str | None,
        iid: int,
        draft_id: int,
        body: str,
    ) -> ToolResult:
        mr_path = self._get_mr_path(client, project)
        await client.put(f"{mr_path}/{iid}/draft_notes/{draft_id}", note=body)
        return ToolResult(output=f"Updated draft note #{draft_id}")

    async def _delete_draft(
        self,
        client: GitLabClient,
        project: str | None,
        iid: int,
        draft_id: int,
    ) -> ToolResult:
        mr_path = self._get_mr_path(client, project)
        await client.delete(f"{mr_path}/{iid}/draft_notes/{draft_id}")
        return ToolResult(output=f"Deleted draft note #{draft_id}")

    async def _publish_drafts(
        self,
        client: GitLabClient,
        project: str | None,
        iid: int,
    ) -> ToolResult:
        mr_path = self._get_mr_path(client, project)
        await client.post(f"{mr_path}/{iid}/draft_notes/bulk_publish")
        return ToolResult(output="Published all draft notes as review")
