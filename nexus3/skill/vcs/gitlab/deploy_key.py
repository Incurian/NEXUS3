"""GitLab deploy key skill."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nexus3.core.types import ToolResult
from nexus3.skill.vcs.gitlab.base import GitLabSkill
from nexus3.skill.vcs.gitlab.client import GitLabClient

if TYPE_CHECKING:
    pass


class GitLabDeployKeySkill(GitLabSkill):
    """Manage GitLab deploy keys for repository access."""

    @property
    def name(self) -> str:
        return "gitlab_deploy_key"

    @property
    def description(self) -> str:
        return "Manage GitLab deploy keys for repository access"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "get", "create", "update", "delete", "enable"],
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
                "key_id": {
                    "type": "integer",
                    "description": "Deploy key ID (required for get/update/delete/enable)",
                },
                "title": {
                    "type": "string",
                    "description": "Deploy key title (required for create)",
                },
                "key": {
                    "type": "string",
                    "description": "SSH public key (required for create)",
                },
                "can_push": {
                    "type": "boolean",
                    "description": "Allow push access (default: false, read-only)",
                },
            },
            "required": ["action"],
        }

    def _get_base_path(self, client: GitLabClient, project: str) -> str:
        """Get API base path for project deploy keys."""
        resolved = self._resolve_project(project)
        return f"/projects/{client._encode_path(resolved)}/deploy_keys"

    def _truncate_key(self, key: str, max_len: int = 40) -> str:
        """Truncate SSH key for display (security - never show full key)."""
        if not key:
            return ""
        # SSH keys are typically "type base64data comment"
        # Show type + start of key + ... + end
        parts = key.split()
        if len(parts) >= 2:
            key_type = parts[0]
            key_data = parts[1]
            if len(key_data) > max_len:
                return f"{key_type} {key_data[:20]}...{key_data[-10:]}"
            return f"{key_type} {key_data}"
        # Fallback for malformed keys
        if len(key) > max_len:
            return f"{key[:20]}...{key[-10:]}"
        return key

    async def _execute_impl(
        self,
        client: GitLabClient,
        **kwargs: Any,
    ) -> ToolResult:
        action = kwargs.get("action", "")
        project = kwargs.get("project")

        # Filter out consumed kwargs to avoid passing them twice
        filtered = {
            k: v
            for k, v in kwargs.items()
            if k not in ("action", "project", "instance", "key_id", "title", "key", "can_push")
        }

        match action:
            case "list":
                return await self._list_keys(client, project)
            case "get":
                key_id = kwargs.get("key_id")
                if not key_id:
                    return ToolResult(error="key_id parameter required for get action")
                return await self._get_key(client, project, key_id)
            case "create":
                title = kwargs.get("title")
                key = kwargs.get("key")
                if not title:
                    return ToolResult(error="title parameter required for create action")
                if not key:
                    return ToolResult(error="key parameter required for create action")
                can_push = kwargs.get("can_push", False)
                return await self._create_key(client, project, title, key, can_push)
            case "update":
                key_id = kwargs.get("key_id")
                if not key_id:
                    return ToolResult(error="key_id parameter required for update action")
                return await self._update_key(client, project, key_id, **filtered)
            case "delete":
                key_id = kwargs.get("key_id")
                if not key_id:
                    return ToolResult(error="key_id parameter required for delete action")
                return await self._delete_key(client, project, key_id)
            case "enable":
                key_id = kwargs.get("key_id")
                if not key_id:
                    return ToolResult(error="key_id parameter required for enable action")
                return await self._enable_key(client, project, key_id)
            case _:
                return ToolResult(error=f"Unknown action: {action}")

    async def _list_keys(
        self,
        client: GitLabClient,
        project: str | None,
    ) -> ToolResult:
        if not project:
            project = self._resolve_project(None)
        base_path = self._get_base_path(client, project)

        keys = [key async for key in client.paginate(base_path, limit=100)]

        if not keys:
            return ToolResult(output="No deploy keys found")

        lines = [f"Found {len(keys)} deploy key(s):"]
        for key in keys:
            title = key.get("title", "Untitled")
            key_id = key.get("id", "?")
            can_push = key.get("can_push", False)
            access = "read-write" if can_push else "read-only"

            # Show fingerprint if available, otherwise truncate key
            fingerprint = key.get("fingerprint", "")
            if fingerprint:
                key_display = f"fingerprint: {fingerprint}"
            else:
                key_display = self._truncate_key(key.get("key", ""))

            lines.append(f"  [{key_id}] {title} ({access})")
            if key_display:
                lines.append(f"      {key_display}")

        return ToolResult(output="\n".join(lines))

    async def _get_key(
        self,
        client: GitLabClient,
        project: str | None,
        key_id: int,
    ) -> ToolResult:
        if not project:
            project = self._resolve_project(None)
        base_path = self._get_base_path(client, project)
        key = await client.get(f"{base_path}/{key_id}")

        title = key.get("title", "Untitled")
        can_push = key.get("can_push", False)
        access = "read-write" if can_push else "read-only"
        created_at = key.get("created_at", "")

        # Show fingerprint if available, otherwise truncate key
        fingerprint = key.get("fingerprint", "")
        if fingerprint:
            key_display = f"Fingerprint: {fingerprint}"
        else:
            key_display = f"Key: {self._truncate_key(key.get('key', ''))}"

        lines = [
            f"# {title}",
            "",
            f"ID: {key.get('id', '')}",
            key_display,
            f"Access: {access}",
        ]

        if created_at:
            lines.append(f"Created: {created_at}")

        return ToolResult(output="\n".join(lines))

    async def _create_key(
        self,
        client: GitLabClient,
        project: str | None,
        title: str,
        key: str,
        can_push: bool,
    ) -> ToolResult:
        if not project:
            project = self._resolve_project(None)
        base_path = self._get_base_path(client, project)

        data: dict[str, Any] = {
            "title": title,
            "key": key,
            "can_push": can_push,
        }

        result = await client.post(base_path, **data)

        access = "read-write" if result.get("can_push", False) else "read-only"
        return ToolResult(
            output=f"Created deploy key '{result.get('title', title)}' ({access})"
        )

    async def _update_key(
        self,
        client: GitLabClient,
        project: str | None,
        key_id: int,
        **kwargs: Any,
    ) -> ToolResult:
        if not project:
            project = self._resolve_project(None)
        base_path = self._get_base_path(client, project)

        data: dict[str, Any] = {}

        title = kwargs.get("title")
        can_push = kwargs.get("can_push")

        if title is not None:
            data["title"] = title
        if can_push is not None:
            data["can_push"] = can_push

        if not data:
            return ToolResult(error="No fields to update (provide title or can_push)")

        result = await client.put(f"{base_path}/{key_id}", **data)

        return ToolResult(output=f"Updated deploy key '{result.get('title', '')}'")

    async def _delete_key(
        self,
        client: GitLabClient,
        project: str | None,
        key_id: int,
    ) -> ToolResult:
        if not project:
            project = self._resolve_project(None)
        base_path = self._get_base_path(client, project)
        await client.delete(f"{base_path}/{key_id}")
        return ToolResult(output=f"Deleted deploy key {key_id}")

    async def _enable_key(
        self,
        client: GitLabClient,
        project: str | None,
        key_id: int,
    ) -> ToolResult:
        """Enable an existing deploy key from another project."""
        if not project:
            project = self._resolve_project(None)
        base_path = self._get_base_path(client, project)

        result = await client.post(f"{base_path}/{key_id}/enable")

        return ToolResult(
            output=f"Enabled deploy key '{result.get('title', '')}' for this project"
        )
