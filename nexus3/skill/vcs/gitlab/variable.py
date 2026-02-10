"""GitLab CI/CD variable skill."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nexus3.core.types import ToolResult
from nexus3.skill.vcs.gitlab.base import GitLabSkill
from nexus3.skill.vcs.gitlab.client import GitLabClient

if TYPE_CHECKING:
    pass


class GitLabVariableSkill(GitLabSkill):
    """Create, view, update, and delete GitLab CI/CD variables.

    Works at project or group level (provide one). Actions: list, get, create,
    update, delete. Create requires key and value. Supports protected, masked,
    and environment_scope options.
    """

    @property
    def name(self) -> str:
        return "gitlab_variable"

    @property
    def description(self) -> str:
        return (
            "Create, view, update, and delete GitLab CI/CD variables. "
            "Works at project or group level (provide one). "
            "Actions: list, get, create, update, delete. "
            "Create requires key and value. "
            "Supports protected, masked, and environment_scope options."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "get", "create", "update", "delete"],
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
                "key": {
                    "type": "string",
                    "description": "Variable key/name (required for get/create/update/delete)",
                },
                "value": {
                    "type": "string",
                    "description": "Variable value (required for create, optional for update)",
                },
                "protected": {
                    "type": "boolean",
                    "description": "Only expose to protected branches/tags (default: false)",
                },
                "masked": {
                    "type": "boolean",
                    "description": "Mask variable in job logs (default: false)",
                },
                "raw": {
                    "type": "boolean",
                    "description": "Treat variable as raw string, no expansion (default: false)",
                },
                "environment_scope": {
                    "type": "string",
                    "description": "Environment scope (default: '*' for all environments)",
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
        """Get API base path for project or group variables."""
        if group:
            return f"/groups/{client._encode_path(group)}/variables"
        if project:
            resolved = self._resolve_project(project)
            return f"/projects/{client._encode_path(resolved)}/variables"
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
        excluded = ("action", "project", "group", "instance", "key")
        filtered = {k: v for k, v in kwargs.items() if k not in excluded}

        match action:
            case "list":
                return await self._list_variables(client, project, group)
            case "get":
                key = kwargs.get("key")
                if not key:
                    return ToolResult(error="key parameter required for get action")
                return await self._get_variable(client, project, group, key)
            case "create":
                key = kwargs.get("key")
                value = kwargs.get("value")
                if not key:
                    return ToolResult(error="key parameter required for create action")
                if not value:
                    return ToolResult(error="value parameter required for create action")
                return await self._create_variable(
                    client, project, group, key, value, **filtered
                )
            case "update":
                key = kwargs.get("key")
                if not key:
                    return ToolResult(error="key parameter required for update action")
                return await self._update_variable(
                    client, project, group, key, **filtered
                )
            case "delete":
                key = kwargs.get("key")
                if not key:
                    return ToolResult(error="key parameter required for delete action")
                return await self._delete_variable(client, project, group, key)
            case _:
                return ToolResult(error=f"Unknown action: {action}")

    async def _list_variables(
        self,
        client: GitLabClient,
        project: str | None,
        group: str | None,
    ) -> ToolResult:
        base_path = self._get_base_path(client, project, group)

        variables = [
            var async for var in
            client.paginate(base_path, limit=100)
        ]

        if not variables:
            return ToolResult(output="No CI/CD variables found")

        lines = [f"Found {len(variables)} variable(s):"]
        for var in variables:
            key = var.get("key", "")
            masked = var.get("masked", False)
            protected = var.get("protected", False)
            scope = var.get("environment_scope", "*")

            # Build status indicators
            indicators = []
            if masked:
                indicators.append("\U0001f512")  # lock emoji for masked
            if protected:
                indicators.append("\U0001f6e1\ufe0f")  # shield emoji for protected
            indicator_str = " ".join(indicators) + " " if indicators else ""

            # Show scope only if not default
            scope_str = f" [{scope}]" if scope != "*" else ""

            lines.append(f"  {indicator_str}{key}{scope_str}")

        return ToolResult(output="\n".join(lines))

    async def _get_variable(
        self,
        client: GitLabClient,
        project: str | None,
        group: str | None,
        key: str,
    ) -> ToolResult:
        base_path = self._get_base_path(client, project, group)
        var = await client.get(f"{base_path}/{key}")

        masked = var.get("masked", False)
        protected = var.get("protected", False)
        raw = var.get("raw", False)
        scope = var.get("environment_scope", "*")

        # Format status strings (avoid escape sequences in f-strings for Python 3.11)
        value_display = "****" if masked else var.get("value", "")
        masked_display = "\U0001f512 Yes" if masked else "No"
        protected_display = "\U0001f6e1\ufe0f Yes" if protected else "No"
        raw_display = "Yes" if raw else "No"

        lines = [
            f"# {var.get('key', '')}",
            "",
            f"Value: {value_display}",
            f"Masked: {masked_display}",
            f"Protected: {protected_display}",
            f"Raw: {raw_display}",
            f"Environment Scope: {scope}",
        ]

        if var.get("variable_type"):
            lines.append(f"Type: {var['variable_type']}")

        return ToolResult(output="\n".join(lines))

    async def _create_variable(
        self,
        client: GitLabClient,
        project: str | None,
        group: str | None,
        key: str,
        value: str,
        **kwargs: Any,
    ) -> ToolResult:
        base_path = self._get_base_path(client, project, group)
        data: dict[str, Any] = {
            "key": key,
            "value": value,
        }

        if kwargs.get("protected") is not None:
            data["protected"] = kwargs["protected"]
        if kwargs.get("masked") is not None:
            data["masked"] = kwargs["masked"]
        if kwargs.get("raw") is not None:
            data["raw"] = kwargs["raw"]
        if environment_scope := kwargs.get("environment_scope"):
            data["environment_scope"] = environment_scope

        var = await client.post(base_path, **data)

        # Build result message with settings
        settings = []
        if var.get("protected"):
            settings.append("protected")
        if var.get("masked"):
            settings.append("masked")
        settings_str = f" ({', '.join(settings)})" if settings else ""

        return ToolResult(
            output=f"Created variable '{var.get('key')}'{settings_str}"
        )

    async def _update_variable(
        self,
        client: GitLabClient,
        project: str | None,
        group: str | None,
        key: str,
        **kwargs: Any,
    ) -> ToolResult:
        base_path = self._get_base_path(client, project, group)
        data: dict[str, Any] = {}

        if value := kwargs.get("value"):
            data["value"] = value
        if kwargs.get("protected") is not None:
            data["protected"] = kwargs["protected"]
        if kwargs.get("masked") is not None:
            data["masked"] = kwargs["masked"]
        if kwargs.get("raw") is not None:
            data["raw"] = kwargs["raw"]
        if environment_scope := kwargs.get("environment_scope"):
            data["environment_scope"] = environment_scope

        if not data:
            return ToolResult(error="No fields to update")

        var = await client.put(f"{base_path}/{key}", **data)

        return ToolResult(output=f"Updated variable '{var.get('key')}'")

    async def _delete_variable(
        self,
        client: GitLabClient,
        project: str | None,
        group: str | None,
        key: str,
    ) -> ToolResult:
        base_path = self._get_base_path(client, project, group)
        await client.delete(f"{base_path}/{key}")
        return ToolResult(output=f"Deleted variable '{key}'")
