"""GitLab time tracking management skill."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nexus3.core.types import ToolResult
from nexus3.skill.vcs.gitlab.base import GitLabSkill
from nexus3.skill.vcs.gitlab.client import GitLabClient

if TYPE_CHECKING:
    pass


class GitLabTimeSkill(GitLabSkill):
    """Manage time tracking on GitLab issues and merge requests."""

    @property
    def name(self) -> str:
        return "gitlab_time"

    @property
    def description(self) -> str:
        return "Manage time tracking on GitLab issues and merge requests"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["estimate", "reset-estimate", "spend", "reset-spent", "stats"],
                    "description": "Action to perform",
                },
                "instance": {
                    "type": "string",
                    "description": "GitLab instance name (uses default if omitted)",
                },
                "project": {
                    "type": "string",
                    "description": "Project path (e.g., 'group/repo'). Auto-detected if omitted.",
                },
                "iid": {
                    "type": "integer",
                    "description": "Issue or MR IID. Required.",
                },
                "target_type": {
                    "type": "string",
                    "enum": ["issue", "mr"],
                    "description": "Target type: 'issue' or 'mr'. Required.",
                },
                "duration": {
                    "type": "string",
                    "description": (
                        "Time duration (e.g., '2d', '8h', '1w 2d'). "
                        "Required for estimate/spend."
                    ),
                },
                "summary": {
                    "type": "string",
                    "description": "Optional summary for spent time log entry",
                },
            },
            "required": ["action", "iid", "target_type"],
        }

    def _get_target_path(
        self,
        client: GitLabClient,
        project: str,
        iid: int,
        target_type: str,
    ) -> str:
        """Get API path for issue or MR."""
        project_encoded = client._encode_path(self._resolve_project(project))
        if target_type == "issue":
            return f"/projects/{project_encoded}/issues/{iid}"
        elif target_type == "mr":
            return f"/projects/{project_encoded}/merge_requests/{iid}"
        raise ValueError("target_type must be 'issue' or 'mr'")

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
        if not iid:
            return ToolResult(error="iid parameter required")
        if target_type not in ("issue", "mr"):
            return ToolResult(error="target_type must be 'issue' or 'mr'")

        # Filter out consumed kwargs to avoid passing them twice
        excluded = ("action", "project", "instance", "iid", "target_type")
        filtered = {k: v for k, v in kwargs.items() if k not in excluded}

        # Get base path for the target
        try:
            base_path = self._get_target_path(client, project, iid, target_type)
        except ValueError as e:
            return ToolResult(error=str(e))

        match action:
            case "estimate":
                return await self._set_estimate(client, base_path, target_type, iid, **filtered)
            case "reset-estimate":
                return await self._reset_estimate(client, base_path, target_type, iid)
            case "spend":
                return await self._add_spent_time(client, base_path, target_type, iid, **filtered)
            case "reset-spent":
                return await self._reset_spent_time(client, base_path, target_type, iid)
            case "stats":
                return await self._get_stats(client, base_path, target_type, iid)
            case _:
                return ToolResult(error=f"Unknown action: {action}")

    async def _set_estimate(
        self,
        client: GitLabClient,
        base_path: str,
        target_type: str,
        iid: int,
        **kwargs: Any,
    ) -> ToolResult:
        duration = kwargs.get("duration")
        if not duration:
            return ToolResult(error="duration parameter required for estimate action")

        result = await client.post(f"{base_path}/time_estimate", duration=duration)

        target_name = "issue" if target_type == "issue" else "merge request"
        estimate = result.get("human_time_estimate", duration)
        return ToolResult(
            output=f"Set time estimate for {target_name} !{iid} to {estimate}"
        )

    async def _reset_estimate(
        self,
        client: GitLabClient,
        base_path: str,
        target_type: str,
        iid: int,
    ) -> ToolResult:
        await client.post(f"{base_path}/reset_time_estimate")

        target_name = "issue" if target_type == "issue" else "merge request"
        return ToolResult(output=f"Reset time estimate for {target_name} !{iid}")

    async def _add_spent_time(
        self,
        client: GitLabClient,
        base_path: str,
        target_type: str,
        iid: int,
        **kwargs: Any,
    ) -> ToolResult:
        duration = kwargs.get("duration")
        if not duration:
            return ToolResult(error="duration parameter required for spend action")

        data: dict[str, Any] = {"duration": duration}
        if summary := kwargs.get("summary"):
            data["summary"] = summary

        result = await client.post(f"{base_path}/add_spent_time", **data)

        target_name = "issue" if target_type == "issue" else "merge request"
        total = result.get("human_total_time_spent", "unknown")
        return ToolResult(
            output=f"Added {duration} to {target_name} !{iid}. Total time spent: {total}"
        )

    async def _reset_spent_time(
        self,
        client: GitLabClient,
        base_path: str,
        target_type: str,
        iid: int,
    ) -> ToolResult:
        await client.post(f"{base_path}/reset_spent_time")

        target_name = "issue" if target_type == "issue" else "merge request"
        return ToolResult(output=f"Reset time spent for {target_name} !{iid}")

    async def _get_stats(
        self,
        client: GitLabClient,
        base_path: str,
        target_type: str,
        iid: int,
    ) -> ToolResult:
        stats = await client.get(f"{base_path}/time_stats")

        target_name = "Issue" if target_type == "issue" else "Merge Request"
        lines = [
            f"# Time Tracking for {target_name} !{iid}",
            "",
        ]

        # Time estimate
        estimate = stats.get("human_time_estimate")
        if estimate:
            lines.append(f"Estimate: {estimate}")
        else:
            lines.append("Estimate: Not set")

        # Time spent
        spent = stats.get("human_total_time_spent")
        if spent:
            lines.append(f"Time Spent: {spent}")
        else:
            lines.append("Time Spent: None")

        # Raw values for programmatic use
        lines.append("")
        lines.append("## Raw Values (seconds)")
        lines.append(f"  time_estimate: {stats.get('time_estimate', 0)}")
        lines.append(f"  total_time_spent: {stats.get('total_time_spent', 0)}")

        return ToolResult(output="\n".join(lines))
