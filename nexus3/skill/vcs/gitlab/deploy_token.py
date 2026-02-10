"""GitLab deploy token skill."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nexus3.core.types import ToolResult
from nexus3.skill.vcs.gitlab.base import GitLabSkill
from nexus3.skill.vcs.gitlab.client import GitLabClient

if TYPE_CHECKING:
    pass


class GitLabDeployTokenSkill(GitLabSkill):
    """Manage GitLab deploy tokens for CI/CD and registry access.

    Works at project or group level. Actions: list, get, create, delete. Create
    requires name and scopes array. Token value is only shown on create.
    """

    @property
    def name(self) -> str:
        return "gitlab_deploy_token"

    @property
    def description(self) -> str:
        return (
            "Manage GitLab deploy tokens for CI/CD and registry access. "
            "Works at project or group level. "
            "Actions: list, get, create, delete. "
            "Create requires name and scopes array. Token value is only shown on create."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "get", "create", "delete"],
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
                "token_id": {
                    "type": "integer",
                    "description": "Deploy token ID (required for get/delete)",
                },
                "name": {
                    "type": "string",
                    "description": "Token name (required for create)",
                },
                "scopes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Token scopes (required for create). Options: "
                        "read_repository, read_registry, write_registry, "
                        "read_package_registry, write_package_registry"
                    ),
                },
                "expires_at": {
                    "type": "string",
                    "description": "Expiration date in ISO format (YYYY-MM-DD)",
                },
                "username": {
                    "type": "string",
                    "description": "Custom username for the token (optional)",
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
        """Get API base path for project or group deploy tokens."""
        if group:
            return f"/groups/{client._encode_path(group)}/deploy_tokens"
        if project:
            resolved = self._resolve_project(project)
            return f"/projects/{client._encode_path(resolved)}/deploy_tokens"
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
        filtered = {
            k: v for k, v in kwargs.items()
            if k not in (
                "action", "project", "group", "instance",
                "token_id", "name", "scopes", "expires_at", "username"
            )
        }

        match action:
            case "list":
                return await self._list_tokens(client, project, group)
            case "get":
                token_id = kwargs.get("token_id")
                if not token_id:
                    return ToolResult(error="token_id parameter required for get action")
                return await self._get_token(client, project, group, token_id)
            case "create":
                name = kwargs.get("name")
                scopes = kwargs.get("scopes")
                if not name:
                    return ToolResult(error="name parameter required for create action")
                if not scopes:
                    return ToolResult(error="scopes parameter required for create action")
                return await self._create_token(
                    client, project, group, name, scopes,
                    expires_at=kwargs.get("expires_at"),
                    username=kwargs.get("username"),
                    **filtered,
                )
            case "delete":
                token_id = kwargs.get("token_id")
                if not token_id:
                    return ToolResult(error="token_id parameter required for delete action")
                return await self._delete_token(client, project, group, token_id)
            case _:
                return ToolResult(error=f"Unknown action: {action}")

    async def _list_tokens(
        self,
        client: GitLabClient,
        project: str | None,
        group: str | None,
    ) -> ToolResult:
        base_path = self._get_base_path(client, project, group)

        tokens = [
            token async for token in
            client.paginate(base_path, limit=100)
        ]

        if not tokens:
            return ToolResult(output="No deploy tokens found")

        lines = [f"Found {len(tokens)} deploy token(s):"]
        for token in tokens:
            name = token.get("name", "")
            username = token.get("username", "")
            scopes = token.get("scopes", [])
            expires_at = token.get("expires_at") or "never"
            revoked = token.get("revoked", False)

            # Build status indicators
            status = " [REVOKED]" if revoked else ""
            scope_str = ", ".join(scopes) if scopes else "none"

            lines.append(
                f"  #{token.get('id', '')} {name}{status}\n"
                f"    Username: {username}\n"
                f"    Scopes: {scope_str}\n"
                f"    Expires: {expires_at}"
            )

        return ToolResult(output="\n".join(lines))

    async def _get_token(
        self,
        client: GitLabClient,
        project: str | None,
        group: str | None,
        token_id: int,
    ) -> ToolResult:
        base_path = self._get_base_path(client, project, group)
        token = await client.get(f"{base_path}/{token_id}")

        name = token.get("name", "")
        username = token.get("username", "")
        scopes = token.get("scopes", [])
        created_at = token.get("created_at", "unknown")
        expires_at = token.get("expires_at") or "never"
        revoked = token.get("revoked", False)

        scope_str = ", ".join(scopes) if scopes else "none"
        revoked_str = "Yes" if revoked else "No"

        lines = [
            f"# Deploy Token #{token.get('id', '')}",
            "",
            f"Name: {name}",
            f"Username: {username}",
            f"Scopes: {scope_str}",
            f"Created: {created_at}",
            f"Expires: {expires_at}",
            f"Revoked: {revoked_str}",
        ]

        return ToolResult(output="\n".join(lines))

    async def _create_token(
        self,
        client: GitLabClient,
        project: str | None,
        group: str | None,
        name: str,
        scopes: list[str],
        expires_at: str | None = None,
        username: str | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        base_path = self._get_base_path(client, project, group)
        data: dict[str, Any] = {
            "name": name,
            "scopes": scopes,
        }

        if expires_at:
            data["expires_at"] = expires_at
        if username:
            data["username"] = username

        token = await client.post(base_path, **data)

        # CRITICAL: The token value is ONLY returned on creation
        token_value = token.get("token", "")
        token_username = token.get("username", "")
        token_id = token.get("id", "")
        scope_str = ", ".join(token.get("scopes", []))

        lines = [
            f"Created deploy token '{name}' (ID: {token_id})",
            "",
            "=== SAVE THIS TOKEN NOW ===",
            "The token value is only shown once and cannot be retrieved later.",
            "",
            f"Token: {token_value}",
            f"Username: {token_username}",
            f"Scopes: {scope_str}",
            "",
            "Use in CI/CD or Docker:",
            f"  docker login -u {token_username} -p $DEPLOY_TOKEN registry.gitlab.com",
        ]

        return ToolResult(output="\n".join(lines))

    async def _delete_token(
        self,
        client: GitLabClient,
        project: str | None,
        group: str | None,
        token_id: int,
    ) -> ToolResult:
        base_path = self._get_base_path(client, project, group)
        await client.delete(f"{base_path}/{token_id}")
        return ToolResult(output=f"Deleted deploy token #{token_id}")
