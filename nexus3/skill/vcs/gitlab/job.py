"""GitLab job skill."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nexus3.core.types import ToolResult
from nexus3.skill.vcs.gitlab.base import GitLabSkill
from nexus3.skill.vcs.gitlab.client import GitLabClient

if TYPE_CHECKING:
    pass


class GitLabJobSkill(GitLabSkill):
    """View, manage, and control GitLab CI/CD jobs."""

    @property
    def name(self) -> str:
        return "gitlab_job"

    @property
    def description(self) -> str:
        return "View, manage, and control GitLab CI/CD jobs"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "get", "log", "retry", "cancel", "play", "erase"],
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
                "job_id": {
                    "type": "integer",
                    "description": "Job ID (required for get/log/retry/cancel/play/erase)",
                },
                "scope": {
                    "type": "string",
                    "enum": [
                        "created", "pending", "running", "failed",
                        "success", "canceled", "skipped", "manual",
                    ],
                    "description": "Filter jobs by scope (for list action)",
                },
                "tail": {
                    "type": "integer",
                    "description": "Number of lines from end of log (for log action)",
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
                    "description": "Variables to pass when playing manual job",
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
            if k not in ("action", "project", "instance", "job_id")
        }

        match action:
            case "list":
                return await self._list_jobs(client, project_encoded, **filtered)
            case "get":
                job_id = kwargs.get("job_id")
                if not job_id:
                    return ToolResult(error="job_id parameter required for get action")
                return await self._get_job(client, project_encoded, job_id)
            case "log":
                job_id = kwargs.get("job_id")
                if not job_id:
                    return ToolResult(error="job_id parameter required for log action")
                tail = kwargs.get("tail")
                return await self._get_job_log(client, project_encoded, job_id, tail)
            case "retry":
                job_id = kwargs.get("job_id")
                if not job_id:
                    return ToolResult(error="job_id parameter required for retry action")
                return await self._retry_job(client, project_encoded, job_id)
            case "cancel":
                job_id = kwargs.get("job_id")
                if not job_id:
                    return ToolResult(error="job_id parameter required for cancel action")
                return await self._cancel_job(client, project_encoded, job_id)
            case "play":
                job_id = kwargs.get("job_id")
                if not job_id:
                    return ToolResult(error="job_id parameter required for play action")
                return await self._play_job(client, project_encoded, job_id, **filtered)
            case "erase":
                job_id = kwargs.get("job_id")
                if not job_id:
                    return ToolResult(error="job_id parameter required for erase action")
                return await self._erase_job(client, project_encoded, job_id)
            case _:
                return ToolResult(error=f"Unknown action: {action}")

    def _status_icon(self, status: str) -> str:
        """Get status icon for job status."""
        icons = {
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
        return icons.get(status, "❓")

    async def _list_jobs(
        self,
        client: GitLabClient,
        project: str,
        **kwargs: Any,
    ) -> ToolResult:
        """List jobs in project."""
        params: dict[str, Any] = {}

        if scope := kwargs.get("scope"):
            params["scope"] = scope

        limit = kwargs.get("limit", 20)

        jobs = [
            job async for job in
            client.paginate(f"/projects/{project}/jobs", limit=limit, **params)
        ]

        if not jobs:
            return ToolResult(output="No jobs found")

        lines = [f"Found {len(jobs)} job(s):"]
        for job in jobs:
            status = job.get("status", "unknown")
            icon = self._status_icon(status)
            job_id = job["id"]
            name = job.get("name", "unnamed")
            stage = job.get("stage", "unknown")
            ref = job.get("ref", "")
            duration = job.get("duration")
            duration_str = f" ({duration:.1f}s)" if duration else ""

            lines.append(f"  {icon} #{job_id} {name} [{stage}] on {ref}{duration_str}")

        return ToolResult(output="\n".join(lines))

    async def _get_job(
        self,
        client: GitLabClient,
        project: str,
        job_id: int,
    ) -> ToolResult:
        """Get job details."""
        job = await client.get(f"/projects/{project}/jobs/{job_id}")

        status = job.get("status", "unknown")
        icon = self._status_icon(status)

        lines = [
            f"# Job #{job['id']}: {job.get('name', 'unnamed')}",
            "",
            f"Status: {icon} {status}",
            f"Stage: {job.get('stage', 'unknown')}",
            f"Ref: {job.get('ref', 'unknown')}",
            f"Created: {job.get('created_at', 'unknown')}",
        ]

        if job.get("started_at"):
            lines.append(f"Started: {job['started_at']}")
        if job.get("finished_at"):
            lines.append(f"Finished: {job['finished_at']}")
        if job.get("duration"):
            lines.append(f"Duration: {job['duration']:.1f}s")
        if job.get("queued_duration"):
            lines.append(f"Queued: {job['queued_duration']:.1f}s")

        # Pipeline info
        if pipeline := job.get("pipeline"):
            lines.append(f"Pipeline: #{pipeline.get('id', 'unknown')}")

        # Runner info
        if runner := job.get("runner"):
            runner_name = runner.get("description", runner.get("name", "unknown"))
            lines.append(f"Runner: {runner_name}")

        # Artifacts
        if artifacts := job.get("artifacts"):
            artifact_names = [a.get("filename", "unknown") for a in artifacts]
            lines.append(f"Artifacts: {', '.join(artifact_names)}")

        # Coverage
        if coverage := job.get("coverage"):
            lines.append(f"Coverage: {coverage}%")

        # Failure reason
        if reason := job.get("failure_reason"):
            lines.append(f"Failure reason: {reason}")

        # Web URL
        if web_url := job.get("web_url"):
            lines.append("")
            lines.append(f"Web URL: {web_url}")

        return ToolResult(output="\n".join(lines))

    async def _get_job_log(
        self,
        client: GitLabClient,
        project: str,
        job_id: int,
        tail: int | None = None,
    ) -> ToolResult:
        """Get job log (trace)."""
        # The trace endpoint returns plain text, not JSON
        # We need to make a raw request
        log_text = await client.get_raw(f"/projects/{project}/jobs/{job_id}/trace")

        if not log_text:
            return ToolResult(output=f"Job #{job_id} has no log output")

        # If tail is specified, return only last N lines
        if tail and tail > 0:
            lines = log_text.splitlines()
            if len(lines) > tail:
                log_text = "\n".join(lines[-tail:])
                header = f"Job #{job_id} log (last {tail} lines):\n"
            else:
                header = f"Job #{job_id} log ({len(lines)} lines):\n"
        else:
            header = f"Job #{job_id} log:\n"

        return ToolResult(output=header + log_text)

    async def _retry_job(
        self,
        client: GitLabClient,
        project: str,
        job_id: int,
    ) -> ToolResult:
        """Retry a failed or canceled job."""
        job = await client.post(f"/projects/{project}/jobs/{job_id}/retry")

        return ToolResult(
            output=f"Retried job #{job_id} -> new job #{job['id']}"
        )

    async def _cancel_job(
        self,
        client: GitLabClient,
        project: str,
        job_id: int,
    ) -> ToolResult:
        """Cancel a running or pending job."""
        await client.post(f"/projects/{project}/jobs/{job_id}/cancel")

        return ToolResult(output=f"Cancelled job #{job_id}")

    async def _play_job(
        self,
        client: GitLabClient,
        project: str,
        job_id: int,
        **kwargs: Any,
    ) -> ToolResult:
        """Start a manual job."""
        data: dict[str, Any] = {}

        # Handle variables for manual jobs
        if variables := kwargs.get("variables"):
            # GitLab expects job_variables_attributes format
            data["job_variables_attributes"] = [
                {"key": v["key"], "value": v["value"]}
                for v in variables
            ]

        if data:
            job = await client.post(f"/projects/{project}/jobs/{job_id}/play", **data)
        else:
            job = await client.post(f"/projects/{project}/jobs/{job_id}/play")

        return ToolResult(
            output=f"Started manual job #{job_id} (status: {job.get('status', 'unknown')})"
        )

    async def _erase_job(
        self,
        client: GitLabClient,
        project: str,
        job_id: int,
    ) -> ToolResult:
        """Erase job logs and artifacts."""
        await client.post(f"/projects/{project}/jobs/{job_id}/erase")

        return ToolResult(output=f"Erased job #{job_id} (logs and artifacts deleted)")
