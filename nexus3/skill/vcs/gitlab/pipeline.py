"""GitLab pipeline skill."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nexus3.core.types import ToolResult
from nexus3.skill.vcs.gitlab.base import GitLabSkill
from nexus3.skill.vcs.gitlab.client import GitLabClient

if TYPE_CHECKING:
    pass


class GitLabPipelineSkill(GitLabSkill):
    """Manage GitLab CI/CD pipelines.

    Actions: list, get, create, retry, cancel, delete, jobs, variables. Use list
    with status/ref to filter. Create triggers a new pipeline on a ref. Use jobs
    to list pipeline jobs, variables to see pipeline variables.
    """

    @property
    def name(self) -> str:
        return "gitlab_pipeline"

    @property
    def description(self) -> str:
        return (
            "Manage GitLab CI/CD pipelines. "
            "Actions: list, get, create, retry, cancel, delete, jobs, variables. "
            "Use list with status/ref to filter. Create triggers a new pipeline on a ref. "
            "Use jobs to list pipeline jobs, variables to see pipeline variables."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "list", "get", "create", "retry", "cancel",
                        "delete", "jobs", "variables",
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
                "pipeline_id": {
                    "type": "integer",
                    "description": (
                        "Pipeline ID (required for get/retry/cancel/delete/jobs/variables)"
                    ),
                },
                "ref": {
                    "type": "string",
                    "description": (
                        "Branch or tag ref (required for create, optional filter for list)"
                    ),
                },
                "status": {
                    "type": "string",
                    "enum": [
                        "created", "waiting_for_resource", "preparing", "pending",
                        "running", "success", "failed", "canceled", "skipped", "manual",
                        "scheduled",
                    ],
                    "description": "Filter by pipeline status (for list)",
                },
                "source": {
                    "type": "string",
                    "enum": [
                        "push", "web", "trigger", "schedule", "api", "external",
                        "pipeline", "chat", "webide", "merge_request_event",
                        "external_pull_request_event", "parent_pipeline",
                        "ondemand_dast_scan", "ondemand_dast_validation",
                    ],
                    "description": "Filter by pipeline source (for list)",
                },
                "scope": {
                    "type": "string",
                    "enum": [
                        "created", "pending", "running", "failed",
                        "success", "canceled", "skipped", "manual",
                    ],
                    "description": "Filter jobs by scope (for jobs action)",
                },
                "variables": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string"},
                            "value": {"type": "string"},
                        },
                        "required": ["key", "value"],
                    },
                    "description": "Pipeline variables for create (array of {key, value})",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results (default: 20)",
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
        filtered = {
            k: v for k, v in kwargs.items()
            if k not in ("action", "project", "instance", "pipeline_id")
        }

        match action:
            case "list":
                return await self._list_pipelines(client, project_encoded, **filtered)
            case "get":
                pipeline_id = kwargs.get("pipeline_id")
                if not pipeline_id:
                    return ToolResult(error="pipeline_id parameter required for get action")
                return await self._get_pipeline(client, project_encoded, pipeline_id)
            case "create":
                ref = kwargs.get("ref")
                if not ref:
                    return ToolResult(error="ref parameter required for create action")
                return await self._create_pipeline(client, project_encoded, **filtered)
            case "retry":
                pipeline_id = kwargs.get("pipeline_id")
                if not pipeline_id:
                    return ToolResult(error="pipeline_id parameter required for retry action")
                return await self._retry_pipeline(client, project_encoded, pipeline_id)
            case "cancel":
                pipeline_id = kwargs.get("pipeline_id")
                if not pipeline_id:
                    return ToolResult(error="pipeline_id parameter required for cancel action")
                return await self._cancel_pipeline(client, project_encoded, pipeline_id)
            case "delete":
                pipeline_id = kwargs.get("pipeline_id")
                if not pipeline_id:
                    return ToolResult(error="pipeline_id parameter required for delete action")
                return await self._delete_pipeline(client, project_encoded, pipeline_id)
            case "jobs":
                pipeline_id = kwargs.get("pipeline_id")
                if not pipeline_id:
                    return ToolResult(error="pipeline_id parameter required for jobs action")
                return await self._list_jobs(client, project_encoded, pipeline_id, **filtered)
            case "variables":
                pipeline_id = kwargs.get("pipeline_id")
                if not pipeline_id:
                    return ToolResult(error="pipeline_id parameter required for variables action")
                return await self._get_variables(client, project_encoded, pipeline_id)
            case _:
                return ToolResult(error=f"Unknown action: {action}")

    def _status_icon(self, status: str) -> str:
        """Get status icon for pipeline/job status."""
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
            "waiting_for_resource": "🟡",
            "preparing": "🟡",
            "scheduled": "🟡",
        }
        return status_icons.get(status, "❓")

    async def _list_pipelines(
        self,
        client: GitLabClient,
        project: str,
        **kwargs: Any,
    ) -> ToolResult:
        params: dict[str, Any] = {}

        if ref := kwargs.get("ref"):
            params["ref"] = ref
        if status := kwargs.get("status"):
            params["status"] = status
        if source := kwargs.get("source"):
            params["source"] = source

        limit = kwargs.get("limit", 20)

        pipelines = [
            p async for p in
            client.paginate(f"/projects/{project}/pipelines", limit=limit, **params)
        ]

        if not pipelines:
            return ToolResult(output="No pipelines found")

        lines = [f"Found {len(pipelines)} pipeline(s):"]
        for p in pipelines:
            status = p.get("status", "unknown")
            icon = self._status_icon(status)
            ref = p.get("ref", "")
            created_at = p.get("created_at", "")[:19]  # Trim timezone
            sha = p.get("sha", "")[:8]
            source = p.get("source", "")
            lines.append(f"  {icon} #{p['id']} {status} | {ref} ({sha}) | {source}")
            lines.append(f"      created: {created_at}")

        return ToolResult(output="\n".join(lines))

    async def _get_pipeline(
        self,
        client: GitLabClient,
        project: str,
        pipeline_id: int,
    ) -> ToolResult:
        pipeline = await client.get(f"/projects/{project}/pipelines/{pipeline_id}")

        status = pipeline.get("status", "unknown")
        icon = self._status_icon(status)

        lines = [
            f"# Pipeline #{pipeline['id']} {icon} {status}",
            "",
            f"Ref: {pipeline.get('ref', 'N/A')} | SHA: {pipeline.get('sha', 'N/A')[:12]}",
            f"Source: {pipeline.get('source', 'N/A')}",
            f"Created: {pipeline.get('created_at', 'N/A')}",
        ]

        if pipeline.get("started_at"):
            lines.append(f"Started: {pipeline['started_at']}")
        if pipeline.get("finished_at"):
            lines.append(f"Finished: {pipeline['finished_at']}")
        if pipeline.get("duration"):
            duration = pipeline["duration"]
            mins, secs = divmod(duration, 60)
            lines.append(f"Duration: {int(mins)}m {int(secs)}s")
        if pipeline.get("queued_duration"):
            lines.append(f"Queued: {pipeline['queued_duration']}s")

        if pipeline.get("user"):
            lines.append(f"Triggered by: @{pipeline['user'].get('username', 'unknown')}")

        # Coverage if available
        if pipeline.get("coverage"):
            lines.append(f"Coverage: {pipeline['coverage']}%")

        lines.append("")
        lines.append(f"Web URL: {pipeline.get('web_url', 'N/A')}")

        return ToolResult(output="\n".join(lines))

    async def _create_pipeline(
        self,
        client: GitLabClient,
        project: str,
        **kwargs: Any,
    ) -> ToolResult:
        data: dict[str, Any] = {
            "ref": kwargs["ref"],
        }

        # Handle variables array
        if variables := kwargs.get("variables"):
            # Variables should be array of {key, value} objects
            data["variables"] = variables

        pipeline = await client.post(f"/projects/{project}/pipeline", **data)

        status = pipeline.get("status", "unknown")
        icon = self._status_icon(status)

        return ToolResult(
            output=(
                f"Created pipeline #{pipeline['id']} {icon} {status}\n"
                f"Ref: {pipeline.get('ref', 'N/A')}\n"
                f"Web URL: {pipeline.get('web_url', 'N/A')}"
            )
        )

    async def _retry_pipeline(
        self,
        client: GitLabClient,
        project: str,
        pipeline_id: int,
    ) -> ToolResult:
        pipeline = await client.post(f"/projects/{project}/pipelines/{pipeline_id}/retry")

        status = pipeline.get("status", "unknown")
        icon = self._status_icon(status)

        url = pipeline.get('web_url', '')
        return ToolResult(
            output=f"Retried pipeline #{pipeline['id']} {icon} {status}\n{url}"
        )

    async def _cancel_pipeline(
        self,
        client: GitLabClient,
        project: str,
        pipeline_id: int,
    ) -> ToolResult:
        pipeline = await client.post(f"/projects/{project}/pipelines/{pipeline_id}/cancel")

        status = pipeline.get("status", "unknown")
        icon = self._status_icon(status)

        return ToolResult(
            output=f"Canceled pipeline #{pipeline['id']} {icon} {status}"
        )

    async def _delete_pipeline(
        self,
        client: GitLabClient,
        project: str,
        pipeline_id: int,
    ) -> ToolResult:
        await client.delete(f"/projects/{project}/pipelines/{pipeline_id}")
        return ToolResult(output=f"Deleted pipeline #{pipeline_id}")

    async def _list_jobs(
        self,
        client: GitLabClient,
        project: str,
        pipeline_id: int,
        **kwargs: Any,
    ) -> ToolResult:
        params: dict[str, Any] = {}

        if scope := kwargs.get("scope"):
            params["scope"] = scope

        # Jobs endpoint doesn't support pagination params the same way
        jobs = await client.get(
            f"/projects/{project}/pipelines/{pipeline_id}/jobs",
            **params,
        )

        if not jobs:
            return ToolResult(output=f"Pipeline #{pipeline_id} has no jobs")

        lines = [f"Pipeline #{pipeline_id} has {len(jobs)} job(s):"]

        # Group by stage for better readability
        stages: dict[str, list[dict[str, Any]]] = {}
        for job in jobs:
            stage = job.get("stage", "unknown")
            if stage not in stages:
                stages[stage] = []
            stages[stage].append(job)

        for stage, stage_jobs in stages.items():
            lines.append(f"\n  Stage: {stage}")
            for job in stage_jobs:
                status = job.get("status", "unknown")
                icon = self._status_icon(status)
                name = job.get("name", "unknown")
                job_id = job.get("id", "?")
                duration = job.get("duration")
                duration_str = f" ({int(duration)}s)" if duration else ""
                lines.append(f"    {icon} {name} (#{job_id}) {status}{duration_str}")

        return ToolResult(output="\n".join(lines))

    async def _get_variables(
        self,
        client: GitLabClient,
        project: str,
        pipeline_id: int,
    ) -> ToolResult:
        variables = await client.get(
            f"/projects/{project}/pipelines/{pipeline_id}/variables"
        )

        if not variables:
            return ToolResult(output=f"Pipeline #{pipeline_id} has no variables")

        lines = [f"Pipeline #{pipeline_id} variables:"]
        for var in variables:
            key = var.get("key", "?")
            value = var.get("value", "")
            var_type = var.get("variable_type", "env_var")
            # Mask if it looks like a secret
            if any(s in key.lower() for s in ["token", "secret", "password", "key", "auth"]):
                value = "****"
            lines.append(f"  {key}={value} ({var_type})")

        return ToolResult(output="\n".join(lines))
