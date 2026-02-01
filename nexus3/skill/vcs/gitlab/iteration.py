"""GitLab iteration management skill."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nexus3.core.types import ToolResult
from nexus3.skill.vcs.gitlab.base import GitLabSkill
from nexus3.skill.vcs.gitlab.client import GitLabClient

if TYPE_CHECKING:
    pass


class GitLabIterationSkill(GitLabSkill):
    """Create, view, update, and delete GitLab iterations."""

    @property
    def name(self) -> str:
        return "gitlab_iteration"

    @property
    def description(self) -> str:
        return "Create, view, update, and delete GitLab iterations (group-level)"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "list", "get", "create", "update", "delete",
                        "list-cadences", "create-cadence",
                    ],
                    "description": "Action to perform",
                },
                "instance": {
                    "type": "string",
                    "description": "GitLab instance name (uses default if omitted)",
                },
                "group": {
                    "type": "string",
                    "description": "Group path (e.g., 'mygroup'). Required.",
                },
                "iteration_id": {
                    "type": "integer",
                    "description": "Iteration ID (required for get/update/delete)",
                },
                "title": {
                    "type": "string",
                    "description": "Iteration or cadence title",
                },
                "description": {
                    "type": "string",
                    "description": "Iteration description",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date (YYYY-MM-DD)",
                },
                "due_date": {
                    "type": "string",
                    "description": "Due date (YYYY-MM-DD)",
                },
                "state": {
                    "type": "string",
                    "enum": ["upcoming", "current", "closed", "all"],
                    "description": "Filter by state",
                },
                "search": {
                    "type": "string",
                    "description": "Search iterations by title",
                },
                "include_ancestors": {
                    "type": "boolean",
                    "description": "Include iterations from parent groups",
                },
                "duration_in_weeks": {
                    "type": "integer",
                    "description": "Cadence duration (1-4 weeks)",
                },
                "iterations_in_advance": {
                    "type": "integer",
                    "description": "How many iterations to create in advance",
                },
                "automatic": {
                    "type": "boolean",
                    "description": "Automatically create new iterations",
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
        excluded = ("action", "group", "instance", "iteration_id")
        filtered = {k: v for k, v in kwargs.items() if k not in excluded}

        match action:
            case "list":
                return await self._list_iterations(client, group_encoded, **filtered)
            case "get":
                iteration_id = kwargs.get("iteration_id")
                if not iteration_id:
                    return ToolResult(error="iteration_id parameter required for get action")
                return await self._get_iteration(client, group_encoded, iteration_id)
            case "create":
                title = kwargs.get("title")
                start_date = kwargs.get("start_date")
                due_date = kwargs.get("due_date")
                if not title:
                    return ToolResult(error="title parameter required for create action")
                if not start_date:
                    return ToolResult(error="start_date parameter required for create action")
                if not due_date:
                    return ToolResult(error="due_date parameter required for create action")
                return await self._create_iteration(client, group_encoded, **filtered)
            case "update":
                iteration_id = kwargs.get("iteration_id")
                if not iteration_id:
                    return ToolResult(error="iteration_id parameter required for update action")
                return await self._update_iteration(client, group_encoded, iteration_id, **filtered)
            case "delete":
                iteration_id = kwargs.get("iteration_id")
                if not iteration_id:
                    return ToolResult(error="iteration_id parameter required for delete action")
                return await self._delete_iteration(client, group_encoded, iteration_id)
            case "list-cadences":
                return await self._list_cadences(client, group_encoded)
            case "create-cadence":
                title = kwargs.get("title")
                start_date = kwargs.get("start_date")
                duration = kwargs.get("duration_in_weeks")
                if not title:
                    return ToolResult(error="title parameter required for create-cadence action")
                if not start_date:
                    return ToolResult(
                        error="start_date parameter required for create-cadence action"
                    )
                if not duration:
                    return ToolResult(
                        error="duration_in_weeks parameter required for create-cadence action"
                    )
                return await self._create_cadence(client, group_encoded, **filtered)
            case _:
                return ToolResult(error=f"Unknown action: {action}")

    async def _list_iterations(
        self,
        client: GitLabClient,
        group: str,
        **kwargs: Any,
    ) -> ToolResult:
        params: dict[str, Any] = {}

        if state := kwargs.get("state"):
            params["state"] = state
        if search := kwargs.get("search"):
            params["search"] = search
        if kwargs.get("include_ancestors") is True:
            params["include_ancestors"] = True

        iterations = [
            iteration async for iteration in
            client.paginate(f"/groups/{group}/iterations", limit=100, **params)
        ]

        if not iterations:
            return ToolResult(output="No iterations found")

        lines = [f"Found {len(iterations)} iteration(s):"]
        for iteration in iterations:
            state_icon = self._state_icon(iteration.get("state", ""))
            title = iteration.get("title", "Untitled")
            start = iteration.get("start_date", "?")
            due = iteration.get("due_date", "?")
            lines.append(f"  {state_icon} #{iteration['id']} {title} ({start} to {due})")

        return ToolResult(output="\n".join(lines))

    async def _get_iteration(
        self,
        client: GitLabClient,
        group: str,
        iteration_id: int,
    ) -> ToolResult:
        iteration = await client.get(f"/groups/{group}/iterations/{iteration_id}")

        state_icon = self._state_icon(iteration.get("state", ""))
        lines = [
            f"# {state_icon} {iteration.get('title', 'Untitled')}",
            "",
            f"ID: {iteration['id']}",
            f"State: {iteration.get('state', 'unknown')}",
            f"Start Date: {iteration.get('start_date', 'N/A')}",
            f"Due Date: {iteration.get('due_date', 'N/A')}",
        ]

        if iteration.get("description"):
            lines.append(f"Description: {iteration['description']}")

        if iteration.get("web_url"):
            lines.append("")
            lines.append(f"URL: {iteration['web_url']}")

        return ToolResult(output="\n".join(lines))

    async def _create_iteration(
        self,
        client: GitLabClient,
        group: str,
        **kwargs: Any,
    ) -> ToolResult:
        data: dict[str, Any] = {
            "title": kwargs["title"],
            "start_date": kwargs["start_date"],
            "due_date": kwargs["due_date"],
        }

        if description := kwargs.get("description"):
            data["description"] = description

        iteration = await client.post(f"/groups/{group}/iterations", **data)

        return ToolResult(
            output=f"Created iteration '{iteration.get('title', 'Untitled')}' (#{iteration['id']})"
        )

    async def _update_iteration(
        self,
        client: GitLabClient,
        group: str,
        iteration_id: int,
        **kwargs: Any,
    ) -> ToolResult:
        data: dict[str, Any] = {}

        if title := kwargs.get("title"):
            data["title"] = title
        if description := kwargs.get("description"):
            data["description"] = description

        if not data:
            return ToolResult(error="No fields to update")

        iteration = await client.put(f"/groups/{group}/iterations/{iteration_id}", **data)

        return ToolResult(output=f"Updated iteration '{iteration.get('title', 'Untitled')}'")

    async def _delete_iteration(
        self,
        client: GitLabClient,
        group: str,
        iteration_id: int,
    ) -> ToolResult:
        await client.delete(f"/groups/{group}/iterations/{iteration_id}")
        return ToolResult(output=f"Deleted iteration #{iteration_id}")

    async def _list_cadences(
        self,
        client: GitLabClient,
        group: str,
    ) -> ToolResult:
        cadences = [
            cadence async for cadence in
            client.paginate(f"/groups/{group}/iterations/cadences", limit=100)
        ]

        if not cadences:
            return ToolResult(output="No iteration cadences found")

        lines = [f"Found {len(cadences)} cadence(s):"]
        for cadence in cadences:
            title = cadence.get("title", "Untitled")
            duration = cadence.get("duration_in_weeks", "?")
            automatic = "auto" if cadence.get("automatic") else "manual"
            lines.append(f"  #{cadence['id']} {title} ({duration} weeks, {automatic})")

        return ToolResult(output="\n".join(lines))

    async def _create_cadence(
        self,
        client: GitLabClient,
        group: str,
        **kwargs: Any,
    ) -> ToolResult:
        data: dict[str, Any] = {
            "title": kwargs["title"],
            "start_date": kwargs["start_date"],
            "duration_in_weeks": kwargs["duration_in_weeks"],
        }

        if iterations_in_advance := kwargs.get("iterations_in_advance"):
            data["iterations_in_advance"] = iterations_in_advance
        if kwargs.get("automatic") is not None:
            data["automatic"] = kwargs["automatic"]

        cadence = await client.post(f"/groups/{group}/iterations/cadences", **data)

        return ToolResult(
            output=f"Created cadence '{cadence.get('title', 'Untitled')}' (#{cadence['id']})"
        )

    def _state_icon(self, state: str) -> str:
        """Return icon for iteration state."""
        icons = {
            "upcoming": "[>]",
            "current": "[*]",
            "closed": "[x]",
        }
        return icons.get(state, "[ ]")
