"""GitLab discussion (threaded comments) skill."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nexus3.core.types import ToolResult
from nexus3.skill.vcs.gitlab.base import GitLabSkill
from nexus3.skill.vcs.gitlab.client import GitLabClient

if TYPE_CHECKING:
    pass


class GitLabDiscussionSkill(GitLabSkill):
    """Manage threaded discussions on merge requests and issues.

    Actions: list, get, create, reply, resolve, unresolve. Requires target_type
    ('mr' or 'issue'). Create on MRs supports file-level comments (path, line).
    Resolve/unresolve is MR-only.
    """

    @property
    def name(self) -> str:
        return "gitlab_discussion"

    @property
    def description(self) -> str:
        return (
            "Manage threaded discussions on merge requests and issues. "
            "Actions: list, get, create, reply, resolve, unresolve. "
            "Requires target_type ('mr' or 'issue'). "
            "Create on MRs supports file-level comments (path, line). Resolve/unresolve is MR-only."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "get", "create", "reply", "resolve", "unresolve"],
                    "description": "Action to perform",
                },
                "instance": {
                    "type": "string",
                    "description": "GitLab instance name (uses default if omitted)",
                },
                "project": {
                    "type": "string",
                    "description": "Project path (e.g., 'group/repo')",
                },
                "iid": {
                    "type": "integer",
                    "description": "MR or issue internal ID",
                },
                "target_type": {
                    "type": "string",
                    "enum": ["mr", "issue"],
                    "description": "Target type: 'mr' or 'issue'",
                },
                "discussion_id": {
                    "type": "string",
                    "description": "Discussion ID (for get, reply, resolve, unresolve)",
                },
                "body": {
                    "type": "string",
                    "description": "Comment body (for create, reply)",
                },
                "path": {
                    "type": "string",
                    "description": "File path for inline diff comment (create only, MR only)",
                },
                "line": {
                    "type": "integer",
                    "description": "Line number for inline diff comment (create only, MR only)",
                },
            },
            "required": ["action", "target_type"],
        }

    def _get_target_path(
        self,
        client: GitLabClient,
        project: str,
        iid: int,
        target_type: str,
    ) -> str:
        """Build API path for target type."""
        resolved = self._resolve_project(project)
        encoded = client._encode_path(resolved)

        if target_type == "mr":
            return f"/projects/{encoded}/merge_requests/{iid}/discussions"
        elif target_type == "issue":
            return f"/projects/{encoded}/issues/{iid}/discussions"
        else:
            raise ValueError(f"Invalid target_type: {target_type}. Must be 'mr' or 'issue'")

    async def _execute_impl(
        self,
        client: GitLabClient,
        **kwargs: Any,
    ) -> ToolResult:
        action = kwargs.get("action", "")
        project = kwargs.get("project")
        iid = kwargs.get("iid")
        target_type = kwargs.get("target_type", "")

        # Validate required parameters
        if not target_type:
            return ToolResult(error="target_type parameter required (must be 'mr' or 'issue')")

        if target_type not in ("mr", "issue"):
            return ToolResult(error=f"Invalid target_type: {target_type}. Must be 'mr' or 'issue'")

        # Filter out consumed kwargs
        filtered = {
            k: v for k, v in kwargs.items()
            if k not in ("action", "project", "instance", "iid", "discussion_id", "target_type")
        }

        match action:
            case "list":
                if not iid:
                    return ToolResult(error="iid parameter required for list action")
                return await self._list_discussions(client, project, iid, target_type)

            case "get":
                if not iid:
                    return ToolResult(error="iid parameter required for get action")
                discussion_id = kwargs.get("discussion_id")
                if not discussion_id:
                    return ToolResult(error="discussion_id parameter required for get action")
                return await self._get_discussion(client, project, iid, discussion_id, target_type)

            case "create":
                if not iid:
                    return ToolResult(error="iid parameter required for create action")
                body = kwargs.get("body")
                if not body:
                    return ToolResult(error="body parameter required for create action")
                return await self._create_discussion(client, project, iid, target_type, **filtered)

            case "reply":
                if not iid:
                    return ToolResult(error="iid parameter required for reply action")
                discussion_id = kwargs.get("discussion_id")
                if not discussion_id:
                    return ToolResult(error="discussion_id parameter required for reply action")
                body = kwargs.get("body")
                if not body:
                    return ToolResult(error="body parameter required for reply action")
                return await self._reply_to_discussion(
                    client, project, iid, discussion_id, body, target_type
                )

            case "resolve":
                if not iid:
                    return ToolResult(error="iid parameter required for resolve action")
                if target_type != "mr":
                    return ToolResult(error="resolve action is only available for MR discussions")
                discussion_id = kwargs.get("discussion_id")
                if not discussion_id:
                    return ToolResult(error="discussion_id parameter required for resolve action")
                return await self._resolve_discussion(client, project, iid, discussion_id)

            case "unresolve":
                if not iid:
                    return ToolResult(error="iid parameter required for unresolve action")
                if target_type != "mr":
                    return ToolResult(error="unresolve action is only available for MR discussions")
                discussion_id = kwargs.get("discussion_id")
                if not discussion_id:
                    return ToolResult(error="discussion_id parameter required for unresolve action")
                return await self._unresolve_discussion(client, project, iid, discussion_id)

            case _:
                return ToolResult(error=f"Unknown action: {action}")

    async def _list_discussions(
        self,
        client: GitLabClient,
        project: str | None,
        iid: int,
        target_type: str,
    ) -> ToolResult:
        base_path = self._get_target_path(client, project, iid, target_type)
        discussions = [
            d async for d in
            client.paginate(base_path, limit=100)
        ]

        if not discussions:
            target_label = "merge request" if target_type == "mr" else "issue"
            return ToolResult(output=f"No discussions found on {target_label} #{iid}")

        lines = [f"Found {len(discussions)} discussion(s):"]
        for disc in discussions:
            disc_id = disc.get("id", "unknown")
            notes = disc.get("notes", [])
            note_count = len(notes)

            # Get first note for preview
            first_note = notes[0] if notes else {}
            author = first_note.get("author", {}).get("username", "unknown")
            body = first_note.get("body", "")
            # Truncate body for preview
            preview = body[:60].replace("\n", " ")
            if len(body) > 60:
                preview += "..."

            # Resolution status (MRs only)
            resolvable = disc.get("resolvable", False)
            if resolvable:
                resolved = "resolved" if disc.get("resolved", False) else "unresolved"
                status = f", {resolved}"
            else:
                status = ""

            line = f"  \U0001f4ac {disc_id} ({note_count} note(s){status}) @{author}: {preview}"
            lines.append(line)

        return ToolResult(output="\n".join(lines))

    async def _get_discussion(
        self,
        client: GitLabClient,
        project: str | None,
        iid: int,
        discussion_id: str,
        target_type: str,
    ) -> ToolResult:
        base_path = self._get_target_path(client, project, iid, target_type)
        disc = await client.get(f"{base_path}/{discussion_id}")

        lines = [f"# Discussion {disc.get('id', 'unknown')}"]
        lines.append("")

        # Resolution status (MRs only)
        if disc.get("resolvable"):
            resolved_status = "Resolved" if disc.get("resolved") else "Unresolved"
            lines.append(f"Status: {resolved_status}")
            lines.append("")

        # List all notes in the thread
        notes = disc.get("notes", [])
        lines.append(f"## Notes ({len(notes)})")
        lines.append("")

        for i, note in enumerate(notes, 1):
            author = note.get("author", {}).get("username", "unknown")
            created = note.get("created_at", "unknown")[:10]  # Just date portion
            body = note.get("body", "")

            # Check if it's a diff comment
            position = note.get("position")
            if position and position.get("new_path"):
                path = position.get("new_path")
                line_num = position.get("new_line") or position.get("old_line")
                lines.append(f"### Note {i} - @{author} ({created}) [on {path}:{line_num}]")
            else:
                lines.append(f"### Note {i} - @{author} ({created})")

            lines.append("")
            lines.append(body)
            lines.append("")

        return ToolResult(output="\n".join(lines))

    async def _create_discussion(
        self,
        client: GitLabClient,
        project: str | None,
        iid: int,
        target_type: str,
        **kwargs: Any,
    ) -> ToolResult:
        base_path = self._get_target_path(client, project, iid, target_type)
        data: dict[str, Any] = {
            "body": kwargs["body"],
        }

        # Handle inline diff comments (MR only)
        if target_type == "mr" and (kwargs.get("path") or kwargs.get("line")):
            path = kwargs.get("path")
            line = kwargs.get("line")

            if not path:
                return ToolResult(error="path parameter required when specifying line")
            if not line:
                return ToolResult(error="line parameter required when specifying path")

            # For MR diff comments, we need position data
            data["position"] = {
                "base_sha": "",  # GitLab will use MR's base
                "start_sha": "",  # GitLab will use MR's start
                "head_sha": "",  # GitLab will use MR's head
                "position_type": "text",
                "new_path": path,
                "new_line": line,
            }

        disc = await client.post(base_path, **data)

        disc_id = disc.get("id", "unknown")
        target_label = "merge request" if target_type == "mr" else "issue"
        return ToolResult(
            output=f"Created discussion {disc_id} on {target_label} #{iid}"
        )

    async def _reply_to_discussion(
        self,
        client: GitLabClient,
        project: str | None,
        iid: int,
        discussion_id: str,
        body: str,
        target_type: str,
    ) -> ToolResult:
        base_path = self._get_target_path(client, project, iid, target_type)
        note = await client.post(f"{base_path}/{discussion_id}/notes", body=body)

        note_id = note.get("id", "unknown")
        return ToolResult(output=f"Added reply (note {note_id}) to discussion {discussion_id}")

    async def _resolve_discussion(
        self,
        client: GitLabClient,
        project: str | None,
        iid: int,
        discussion_id: str,
    ) -> ToolResult:
        # Only MRs support resolve
        resolved_project = self._resolve_project(project)
        encoded = client._encode_path(resolved_project)
        path = f"/projects/{encoded}/merge_requests/{iid}/discussions/{discussion_id}"

        await client.put(path, resolved=True)
        return ToolResult(output=f"Resolved discussion {discussion_id}")

    async def _unresolve_discussion(
        self,
        client: GitLabClient,
        project: str | None,
        iid: int,
        discussion_id: str,
    ) -> ToolResult:
        # Only MRs support unresolve
        resolved_project = self._resolve_project(project)
        encoded = client._encode_path(resolved_project)
        path = f"/projects/{encoded}/merge_requests/{iid}/discussions/{discussion_id}"

        await client.put(path, resolved=False)
        return ToolResult(output=f"Unresolved discussion {discussion_id}")
