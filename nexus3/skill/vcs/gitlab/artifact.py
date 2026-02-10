"""GitLab artifact skill."""

from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nexus3.core.types import ToolResult
from nexus3.skill.vcs.gitlab.base import GitLabSkill
from nexus3.skill.vcs.gitlab.client import GitLabAPIError, GitLabClient

if TYPE_CHECKING:
    pass


class GitLabArtifactSkill(GitLabSkill):
    """Download, browse, and manage GitLab job artifacts.

    Actions: download, download-file, browse, delete, keep, download-ref. Use
    browse to list contents before downloading. download-ref gets artifacts by
    branch+job name without a job ID.
    """

    @property
    def name(self) -> str:
        return "gitlab_artifact"

    @property
    def description(self) -> str:
        return (
            "Download, browse, and manage GitLab job artifacts. "
            "Actions: download, download-file, browse, delete, keep, download-ref. "
            "Use browse to list contents before downloading. "
            "download-ref gets artifacts by branch+job name without a job ID."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "download",
                        "download-file",
                        "browse",
                        "delete",
                        "keep",
                        "download-ref",
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
                "job_id": {
                    "type": "integer",
                    "description": (
                        "Job ID (required for download/download-file/browse/delete/keep)"
                    ),
                },
                "output_path": {
                    "type": "string",
                    "description": (
                        "Path to save downloaded artifacts "
                        "(required for download/download-file/download-ref)"
                    ),
                },
                "artifact_path": {
                    "type": "string",
                    "description": (
                        "Path to specific file within artifacts (for download-file)"
                    ),
                },
                "ref": {
                    "type": "string",
                    "description": "Git ref (branch/tag) for download-ref action",
                },
                "job_name": {
                    "type": "string",
                    "description": "Job name for download-ref action",
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
            k: v
            for k, v in kwargs.items()
            if k
            not in (
                "action",
                "project",
                "instance",
                "job_id",
                "output_path",
                "artifact_path",
                "ref",
                "job_name",
            )
        }

        match action:
            case "download":
                job_id = kwargs.get("job_id")
                output_path = kwargs.get("output_path")
                if not job_id:
                    return ToolResult(error="job_id parameter required for download action")
                if not output_path:
                    return ToolResult(
                        error="output_path parameter required for download action"
                    )
                return await self._download_artifacts(
                    client, project_encoded, job_id, output_path, **filtered
                )

            case "download-file":
                job_id = kwargs.get("job_id")
                artifact_path = kwargs.get("artifact_path")
                output_path = kwargs.get("output_path")
                if not job_id:
                    return ToolResult(
                        error="job_id parameter required for download-file action"
                    )
                if not artifact_path:
                    return ToolResult(
                        error="artifact_path parameter required for download-file action"
                    )
                if not output_path:
                    return ToolResult(
                        error="output_path parameter required for download-file action"
                    )
                return await self._download_single_file(
                    client, project_encoded, job_id, artifact_path, output_path, **filtered
                )

            case "browse":
                job_id = kwargs.get("job_id")
                if not job_id:
                    return ToolResult(error="job_id parameter required for browse action")
                return await self._browse_artifacts(
                    client, project_encoded, job_id, **filtered
                )

            case "delete":
                job_id = kwargs.get("job_id")
                if not job_id:
                    return ToolResult(error="job_id parameter required for delete action")
                return await self._delete_artifacts(
                    client, project_encoded, job_id, **filtered
                )

            case "keep":
                job_id = kwargs.get("job_id")
                if not job_id:
                    return ToolResult(error="job_id parameter required for keep action")
                return await self._keep_artifacts(
                    client, project_encoded, job_id, **filtered
                )

            case "download-ref":
                ref = kwargs.get("ref")
                job_name = kwargs.get("job_name")
                output_path = kwargs.get("output_path")
                if not ref:
                    return ToolResult(
                        error="ref parameter required for download-ref action"
                    )
                if not job_name:
                    return ToolResult(
                        error="job_name parameter required for download-ref action"
                    )
                if not output_path:
                    return ToolResult(
                        error="output_path parameter required for download-ref action"
                    )
                return await self._download_by_ref(
                    client, project_encoded, ref, job_name, output_path, **filtered
                )

            case _:
                return ToolResult(error=f"Unknown action: {action}")

    async def _download_artifacts(
        self,
        client: GitLabClient,
        project: str,
        job_id: int,
        output_path: str,
        **kwargs: Any,
    ) -> ToolResult:
        """Download job artifacts (zip archive)."""
        http_client = await client._ensure_client()
        url = f"{client._base_url}/projects/{project}/jobs/{job_id}/artifacts"

        try:
            response = await http_client.get(url)

            if response.status_code == 404:
                return ToolResult(
                    error=f"No artifacts found for job {job_id}. "
                    "The job may not have produced artifacts or they may have expired."
                )
            if response.status_code >= 400:
                return ToolResult(
                    error=f"Failed to download artifacts: HTTP {response.status_code}"
                )

            # Write binary content to file
            out_path = Path(output_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(response.content)

            size_kb = len(response.content) / 1024
            if size_kb >= 1024:
                size_str = f"{size_kb / 1024:.1f} MB"
            else:
                size_str = f"{size_kb:.1f} KB"

            return ToolResult(
                output=f"Downloaded artifacts for job {job_id} to {output_path} ({size_str})"
            )

        except Exception as e:
            return ToolResult(error=f"Failed to download artifacts: {e}")

    async def _download_single_file(
        self,
        client: GitLabClient,
        project: str,
        job_id: int,
        artifact_path: str,
        output_path: str,
        **kwargs: Any,
    ) -> ToolResult:
        """Download a single file from job artifacts."""
        http_client = await client._ensure_client()
        # URL-encode the artifact path (slashes become %2F)
        encoded_artifact = artifact_path.replace("/", "%2F")
        url = f"{client._base_url}/projects/{project}/jobs/{job_id}/artifacts/{encoded_artifact}"

        try:
            response = await http_client.get(url)

            if response.status_code == 404:
                return ToolResult(
                    error=f"Artifact file '{artifact_path}' not found in job {job_id}. "
                    "Use 'browse' action to list available files."
                )
            if response.status_code >= 400:
                return ToolResult(
                    error=f"Failed to download artifact file: HTTP {response.status_code}"
                )

            # Write binary content to file
            out_path = Path(output_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(response.content)

            size_kb = len(response.content) / 1024
            if size_kb >= 1024:
                size_str = f"{size_kb / 1024:.1f} MB"
            else:
                size_str = f"{size_kb:.1f} KB"

            return ToolResult(
                output=(
                    f"Downloaded '{artifact_path}' from job {job_id} "
                    f"to {output_path} ({size_str})"
                )
            )

        except Exception as e:
            return ToolResult(error=f"Failed to download artifact file: {e}")

    async def _browse_artifacts(
        self,
        client: GitLabClient,
        project: str,
        job_id: int,
        **kwargs: Any,
    ) -> ToolResult:
        """List artifact contents by downloading zip and inspecting."""
        # First get job info to show context
        try:
            job = await client.get(f"/projects/{project}/jobs/{job_id}")
        except GitLabAPIError as e:
            if e.status_code == 404:
                return ToolResult(error=f"Job {job_id} not found")
            raise

        job_name = job.get("name", "unknown")
        job_status = job.get("status", "unknown")
        artifacts_info = job.get("artifacts", [])

        # Check if job has artifacts
        if not artifacts_info and not job.get("artifacts_file"):
            return ToolResult(
                output=f"Job {job_id} ({job_name}) has no artifacts.\n"
                f"Status: {job_status}"
            )

        # Download artifacts to temp file and list contents
        http_client = await client._ensure_client()
        url = f"{client._base_url}/projects/{project}/jobs/{job_id}/artifacts"

        try:
            response = await http_client.get(url)

            if response.status_code == 404:
                return ToolResult(
                    output=f"Job {job_id} ({job_name}) artifacts not available.\n"
                    f"Status: {job_status}\n"
                    "Artifacts may have expired or were not produced."
                )
            if response.status_code >= 400:
                return ToolResult(
                    error=f"Failed to fetch artifacts: HTTP {response.status_code}"
                )

            # Write to temp file and inspect
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
                tmp.write(response.content)
                tmp_path = tmp.name

            try:
                with zipfile.ZipFile(tmp_path, "r") as zf:
                    file_list = zf.namelist()
                    total_size = sum(info.file_size for info in zf.infolist())
            finally:
                Path(tmp_path).unlink(missing_ok=True)

            # Format output
            lines = [
                f"Job {job_id} ({job_name}) artifacts:",
                f"Status: {job_status}",
                f"Total: {len(file_list)} file(s), {total_size / 1024:.1f} KB uncompressed",
                "",
                "Files:",
            ]

            # Show file list (limit to prevent huge output)
            max_files = 50
            for i, fname in enumerate(sorted(file_list)):
                if i >= max_files:
                    lines.append(f"  ... and {len(file_list) - max_files} more files")
                    break
                lines.append(f"  {fname}")

            return ToolResult(output="\n".join(lines))

        except zipfile.BadZipFile:
            return ToolResult(
                error=f"Job {job_id} artifacts are not a valid zip archive"
            )
        except Exception as e:
            return ToolResult(error=f"Failed to browse artifacts: {e}")

    async def _delete_artifacts(
        self,
        client: GitLabClient,
        project: str,
        job_id: int,
        **kwargs: Any,
    ) -> ToolResult:
        """Delete job artifacts."""
        await client.delete(f"/projects/{project}/jobs/{job_id}/artifacts")
        return ToolResult(output=f"Deleted artifacts for job {job_id}")

    async def _keep_artifacts(
        self,
        client: GitLabClient,
        project: str,
        job_id: int,
        **kwargs: Any,
    ) -> ToolResult:
        """Prevent job artifacts from expiring."""
        job = await client.post(f"/projects/{project}/jobs/{job_id}/artifacts/keep")
        job_name = job.get("name", "unknown")
        return ToolResult(
            output=f"Artifacts for job {job_id} ({job_name}) will be kept indefinitely"
        )

    async def _download_by_ref(
        self,
        client: GitLabClient,
        project: str,
        ref: str,
        job_name: str,
        output_path: str,
        **kwargs: Any,
    ) -> ToolResult:
        """Download artifacts by git ref and job name."""
        http_client = await client._ensure_client()
        # URL-encode the ref (branches can contain slashes)
        encoded_ref = ref.replace("/", "%2F")
        url = (
            f"{client._base_url}/projects/{project}/jobs/artifacts/"
            f"{encoded_ref}/download?job={job_name}"
        )

        try:
            response = await http_client.get(url)

            if response.status_code == 404:
                return ToolResult(
                    error=f"No artifacts found for job '{job_name}' on ref '{ref}'. "
                    "Check that the job name and ref are correct, and that artifacts exist."
                )
            if response.status_code >= 400:
                return ToolResult(
                    error=f"Failed to download artifacts: HTTP {response.status_code}"
                )

            # Write binary content to file
            out_path = Path(output_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(response.content)

            size_kb = len(response.content) / 1024
            if size_kb >= 1024:
                size_str = f"{size_kb / 1024:.1f} MB"
            else:
                size_str = f"{size_kb:.1f} KB"

            return ToolResult(
                output=f"Downloaded artifacts for job '{job_name}' on '{ref}' "
                f"to {output_path} ({size_str})"
            )

        except Exception as e:
            return ToolResult(error=f"Failed to download artifacts: {e}")
