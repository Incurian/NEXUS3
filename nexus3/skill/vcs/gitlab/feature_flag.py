"""GitLab feature flag skill."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nexus3.core.types import ToolResult
from nexus3.skill.vcs.gitlab.base import GitLabSkill
from nexus3.skill.vcs.gitlab.client import GitLabClient

if TYPE_CHECKING:
    pass


class GitLabFeatureFlagSkill(GitLabSkill):
    """Manage GitLab feature flags for controlled rollouts.

    Actions: list, get, create, update, delete, list-user-lists, create-user-list,
    update-user-list, delete-user-list. Create/update accept strategies array for
    targeting rules. Premium feature.
    """

    @property
    def name(self) -> str:
        return "gitlab_feature_flag"

    @property
    def description(self) -> str:
        return (
            "Manage GitLab feature flags for controlled rollouts. "
            "Actions: list, get, create, update, delete, list-user-lists, "
            "create-user-list, update-user-list, delete-user-list. "
            "Create/update accept strategies array for targeting rules. Premium feature."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "list", "get", "create", "update", "delete",
                        "list-user-lists", "create-user-list",
                        "update-user-list", "delete-user-list",
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
                        "Auto-detected from git remote if omitted."
                    ),
                },
                "name": {
                    "type": "string",
                    "description": "Feature flag name (for get/create/update/delete)",
                },
                "description": {
                    "type": "string",
                    "description": "Feature flag description (for create/update)",
                },
                "active": {
                    "type": "boolean",
                    "description": "Whether flag is active (for create/update)",
                },
                "strategies": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "enum": [
                                    "default", "gradualRolloutUserId",
                                    "userWithId", "gitlabUserList", "flexibleRollout",
                                ],
                                "description": "Strategy type",
                            },
                            "parameters": {
                                "type": "object",
                                "description": "Strategy-specific parameters",
                            },
                            "scopes": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "environment_scope": {"type": "string"},
                                    },
                                },
                                "description": "Environment scopes (e.g., production, staging)",
                            },
                        },
                    },
                    "description": "Rollout strategies (for create/update)",
                },
                "scope": {
                    "type": "string",
                    "enum": ["enabled", "disabled"],
                    "description": "Filter flags by enabled/disabled (for list)",
                },
                "list_id": {
                    "type": "integer",
                    "description": "User list ID (for update-user-list/delete-user-list)",
                },
                "list_name": {
                    "type": "string",
                    "description": "User list name (for create-user-list/update-user-list)",
                },
                "user_xids": {
                    "type": "string",
                    "description": (
                        "Comma-separated user external IDs "
                        "(for create-user-list/update-user-list)"
                    ),
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

        match action:
            case "list":
                return await self._list_flags(
                    client, project_encoded, kwargs.get("scope")
                )
            case "get":
                name = kwargs.get("name")
                if not name:
                    return ToolResult(error="name parameter required for get action")
                return await self._get_flag(client, project_encoded, name)
            case "create":
                name = kwargs.get("name")
                if not name:
                    return ToolResult(error="name parameter required for create action")
                return await self._create_flag(
                    client, project_encoded, name,
                    description=kwargs.get("description"),
                    active=kwargs.get("active"),
                    strategies=kwargs.get("strategies"),
                )
            case "update":
                name = kwargs.get("name")
                if not name:
                    return ToolResult(error="name parameter required for update action")
                return await self._update_flag(
                    client, project_encoded, name,
                    description=kwargs.get("description"),
                    active=kwargs.get("active"),
                    strategies=kwargs.get("strategies"),
                )
            case "delete":
                name = kwargs.get("name")
                if not name:
                    return ToolResult(error="name parameter required for delete action")
                return await self._delete_flag(client, project_encoded, name)
            case "list-user-lists":
                return await self._list_user_lists(client, project_encoded)
            case "create-user-list":
                list_name = kwargs.get("list_name")
                user_xids = kwargs.get("user_xids")
                if not list_name:
                    return ToolResult(
                        error="list_name parameter required for create-user-list action"
                    )
                if not user_xids:
                    return ToolResult(
                        error="user_xids parameter required for create-user-list action"
                    )
                return await self._create_user_list(
                    client, project_encoded, list_name, user_xids
                )
            case "update-user-list":
                list_id = kwargs.get("list_id")
                if not list_id:
                    return ToolResult(
                        error="list_id parameter required for update-user-list action"
                    )
                return await self._update_user_list(
                    client, project_encoded, list_id,
                    list_name=kwargs.get("list_name"),
                    user_xids=kwargs.get("user_xids"),
                )
            case "delete-user-list":
                list_id = kwargs.get("list_id")
                if not list_id:
                    return ToolResult(
                        error="list_id parameter required for delete-user-list action"
                    )
                return await self._delete_user_list(client, project_encoded, list_id)
            case _:
                return ToolResult(error=f"Unknown action: {action}")

    async def _list_flags(
        self,
        client: GitLabClient,
        project: str,
        scope: str | None = None,
    ) -> ToolResult:
        params: dict[str, Any] = {}
        if scope:
            params["scope"] = scope

        flags = [
            flag async for flag in
            client.paginate(f"/projects/{project}/feature_flags", limit=100, **params)
        ]

        if not flags:
            return ToolResult(output="No feature flags found")

        lines = [f"Found {len(flags)} feature flag(s):"]
        for flag in flags:
            name = flag.get("name", "")
            active = flag.get("active", False)
            version = flag.get("version", "")
            status = "active" if active else "inactive"
            version_str = f" (v{version})" if version else ""
            lines.append(f"  - {name}: {status}{version_str}")

        return ToolResult(output="\n".join(lines))

    async def _get_flag(
        self,
        client: GitLabClient,
        project: str,
        name: str,
    ) -> ToolResult:
        flag = await client.get(f"/projects/{project}/feature_flags/{name}")

        active = flag.get("active", False)
        status = "active" if active else "inactive"

        lines = [
            f"# Feature Flag: {flag.get('name', '')}",
            "",
            f"Status: {status}",
        ]

        if flag.get("description"):
            lines.append(f"Description: {flag['description']}")

        if flag.get("version"):
            lines.append(f"Version: {flag['version']}")

        if flag.get("created_at"):
            lines.append(f"Created: {flag['created_at']}")

        if flag.get("updated_at"):
            lines.append(f"Updated: {flag['updated_at']}")

        # Show strategies
        strategies = flag.get("strategies", [])
        if strategies:
            lines.append("")
            lines.append("Strategies:")
            for strategy in strategies:
                strategy_name = strategy.get("name", "unknown")
                params = strategy.get("parameters", {})
                scopes = strategy.get("scopes", [])

                # Format scopes
                scope_envs = [s.get("environment_scope", "*") for s in scopes]
                scope_str = ", ".join(scope_envs) if scope_envs else "*"

                lines.append(f"  - {strategy_name}")
                lines.append(f"    Environments: {scope_str}")
                if params:
                    lines.append(f"    Parameters: {params}")

        return ToolResult(output="\n".join(lines))

    async def _create_flag(
        self,
        client: GitLabClient,
        project: str,
        name: str,
        description: str | None = None,
        active: bool | None = None,
        strategies: list[dict[str, Any]] | None = None,
    ) -> ToolResult:
        data: dict[str, Any] = {
            "name": name,
            "version": "new_version_flag",  # Required for new flags
        }

        if description:
            data["description"] = description
        if active is not None:
            data["active"] = active
        if strategies:
            data["strategies"] = strategies

        flag = await client.post(f"/projects/{project}/feature_flags", **data)

        active_status = flag.get("active", False)
        status = "active" if active_status else "inactive"

        return ToolResult(
            output=f"Created feature flag '{flag.get('name')}' ({status})"
        )

    async def _update_flag(
        self,
        client: GitLabClient,
        project: str,
        name: str,
        description: str | None = None,
        active: bool | None = None,
        strategies: list[dict[str, Any]] | None = None,
    ) -> ToolResult:
        data: dict[str, Any] = {}

        if description is not None:
            data["description"] = description
        if active is not None:
            data["active"] = active
        if strategies is not None:
            data["strategies"] = strategies

        if not data:
            return ToolResult(error="No fields to update")

        flag = await client.put(f"/projects/{project}/feature_flags/{name}", **data)

        active_status = flag.get("active", False)
        status = "active" if active_status else "inactive"

        return ToolResult(
            output=f"Updated feature flag '{flag.get('name')}' ({status})"
        )

    async def _delete_flag(
        self,
        client: GitLabClient,
        project: str,
        name: str,
    ) -> ToolResult:
        await client.delete(f"/projects/{project}/feature_flags/{name}")
        return ToolResult(output=f"Deleted feature flag '{name}'")

    async def _list_user_lists(
        self,
        client: GitLabClient,
        project: str,
    ) -> ToolResult:
        user_lists = [
            ul async for ul in
            client.paginate(
                f"/projects/{project}/feature_flags_user_lists", limit=100
            )
        ]

        if not user_lists:
            return ToolResult(output="No user lists found")

        lines = [f"Found {len(user_lists)} user list(s):"]
        for ul in user_lists:
            name = ul.get("name", "")
            user_xids = ul.get("user_xids", "")
            # Count users from comma-separated string
            user_count = len(user_xids.split(",")) if user_xids else 0
            list_id = ul.get("id") or ul.get("iid", "?")
            lines.append(f"  - {name} (#{list_id}): {user_count} user(s)")

        return ToolResult(output="\n".join(lines))

    async def _create_user_list(
        self,
        client: GitLabClient,
        project: str,
        list_name: str,
        user_xids: str,
    ) -> ToolResult:
        data = {
            "name": list_name,
            "user_xids": user_xids,
        }

        user_list = await client.post(
            f"/projects/{project}/feature_flags_user_lists", **data
        )

        created_name = user_list.get("name", list_name)
        list_id = user_list.get("id") or user_list.get("iid", "?")

        return ToolResult(
            output=f"Created user list '{created_name}' (#{list_id})"
        )

    async def _update_user_list(
        self,
        client: GitLabClient,
        project: str,
        list_id: int,
        list_name: str | None = None,
        user_xids: str | None = None,
    ) -> ToolResult:
        data: dict[str, Any] = {}

        if list_name is not None:
            data["name"] = list_name
        if user_xids is not None:
            data["user_xids"] = user_xids

        if not data:
            return ToolResult(error="No fields to update")

        user_list = await client.put(
            f"/projects/{project}/feature_flags_user_lists/{list_id}", **data
        )

        updated_name = user_list.get("name", "")

        return ToolResult(output=f"Updated user list '{updated_name}' (#{list_id})")

    async def _delete_user_list(
        self,
        client: GitLabClient,
        project: str,
        list_id: int,
    ) -> ToolResult:
        await client.delete(
            f"/projects/{project}/feature_flags_user_lists/{list_id}"
        )
        return ToolResult(output=f"Deleted user list #{list_id}")
