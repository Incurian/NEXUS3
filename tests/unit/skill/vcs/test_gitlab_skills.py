"""Tests for GitLab skill implementations.

Tests a representative sample of GitLab skills with mocked client.
"""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus3.skill.services import ServiceContainer
from nexus3.skill.vcs.config import GitLabConfig, GitLabInstance
from nexus3.skill.vcs.gitlab.client import GitLabAPIError, GitLabClient
from nexus3.skill.vcs.gitlab.issue import GitLabIssueSkill
from nexus3.skill.vcs.gitlab.mr import GitLabMRSkill
from nexus3.skill.vcs.gitlab.branch import GitLabBranchSkill
from nexus3.skill.vcs.gitlab.base import GitLabSkill

from .conftest import (
    SAMPLE_ISSUE,
    SAMPLE_MR,
    SAMPLE_BRANCH,
    SAMPLE_PROJECT,
)


class GitLabSkillTestBase:
    """Base class for GitLab skill tests."""

    @pytest.fixture
    def gitlab_instance(self) -> GitLabInstance:
        """Create GitLab instance for tests."""
        return GitLabInstance(url="https://gitlab.com", token="test-token")

    @pytest.fixture
    def gitlab_config(self, gitlab_instance: GitLabInstance) -> GitLabConfig:
        """Create GitLab config for tests."""
        return GitLabConfig(
            instances={"default": gitlab_instance},
            default_instance="default",
        )

    @pytest.fixture
    def services(self, tmp_path: Path, gitlab_config: GitLabConfig) -> ServiceContainer:
        """Create mock service container."""
        services = ServiceContainer()
        services.register("cwd", str(tmp_path))
        services.register("gitlab_config", gitlab_config)
        return services

    @pytest.fixture
    def mock_client(self) -> AsyncMock:
        """Create a mock GitLab client."""
        client = AsyncMock(spec=GitLabClient)
        client._encode_path = lambda x: x.replace("/", "%2F")
        return client


class TestGitLabIssueSkill(GitLabSkillTestBase):
    """Tests for GitLabIssueSkill."""

    @pytest.fixture
    def skill(
        self, services: ServiceContainer, gitlab_config: GitLabConfig
    ) -> GitLabIssueSkill:
        """Create skill instance."""
        return GitLabIssueSkill(services, gitlab_config)

    @pytest.mark.asyncio
    async def test_list_issues_success(
        self, skill: GitLabIssueSkill, mock_client: AsyncMock
    ) -> None:
        """list action returns issues list."""
        # Mock paginate to return issues
        async def mock_paginate(path: str, limit: int = 20, **kwargs: Any):
            for issue in [SAMPLE_ISSUE]:
                yield issue

        mock_client.paginate = mock_paginate

        with patch.object(skill, "_get_client", return_value=mock_client):
            with patch.object(skill, "_resolve_project", return_value="group/project"):
                result = await skill.execute(action="list")

        assert result.success
        assert "1 issue(s)" in result.output
        assert "Test Issue" in result.output

    @pytest.mark.asyncio
    async def test_list_issues_empty(
        self, skill: GitLabIssueSkill, mock_client: AsyncMock
    ) -> None:
        """list action with no results."""
        async def mock_paginate(path: str, limit: int = 20, **kwargs: Any):
            return
            yield  # Empty generator

        mock_client.paginate = mock_paginate

        with patch.object(skill, "_get_client", return_value=mock_client):
            with patch.object(skill, "_resolve_project", return_value="group/project"):
                result = await skill.execute(action="list")

        assert result.success
        assert "No issues found" in result.output

    @pytest.mark.asyncio
    async def test_get_issue_success(
        self, skill: GitLabIssueSkill, mock_client: AsyncMock
    ) -> None:
        """get action returns issue details."""
        mock_client.get.return_value = SAMPLE_ISSUE

        with patch.object(skill, "_get_client", return_value=mock_client):
            with patch.object(skill, "_resolve_project", return_value="group/project"):
                result = await skill.execute(action="get", iid=1)

        assert result.success
        assert "Test Issue" in result.output
        assert "#1" in result.output
        assert "testuser" in result.output

    @pytest.mark.asyncio
    async def test_get_issue_requires_iid(
        self, skill: GitLabIssueSkill, mock_client: AsyncMock
    ) -> None:
        """get action requires iid parameter."""
        with patch.object(skill, "_get_client", return_value=mock_client):
            with patch.object(skill, "_resolve_project", return_value="group/project"):
                result = await skill.execute(action="get")

        assert not result.success
        assert "iid" in result.error.lower()

    @pytest.mark.asyncio
    async def test_create_issue_success(
        self, skill: GitLabIssueSkill, mock_client: AsyncMock
    ) -> None:
        """create action creates issue."""
        mock_client.post.return_value = {
            **SAMPLE_ISSUE,
            "title": "New Issue",
        }

        with patch.object(skill, "_get_client", return_value=mock_client):
            with patch.object(skill, "_resolve_project", return_value="group/project"):
                result = await skill.execute(
                    action="create",
                    title="New Issue",
                    description="Description here",
                )

        assert result.success
        assert "Created issue" in result.output
        assert "New Issue" in result.output
        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_issue_requires_title(
        self, skill: GitLabIssueSkill, mock_client: AsyncMock
    ) -> None:
        """create action requires title parameter."""
        with patch.object(skill, "_get_client", return_value=mock_client):
            with patch.object(skill, "_resolve_project", return_value="group/project"):
                result = await skill.execute(action="create")

        assert not result.success
        assert "title" in result.error.lower()

    @pytest.mark.asyncio
    async def test_update_issue_success(
        self, skill: GitLabIssueSkill, mock_client: AsyncMock
    ) -> None:
        """update action updates issue."""
        mock_client.put.return_value = {
            **SAMPLE_ISSUE,
            "title": "Updated Title",
        }

        with patch.object(skill, "_get_client", return_value=mock_client):
            with patch.object(skill, "_resolve_project", return_value="group/project"):
                result = await skill.execute(
                    action="update",
                    iid=1,
                    title="Updated Title",
                )

        assert result.success
        assert "Updated issue" in result.output

    @pytest.mark.asyncio
    async def test_update_issue_no_fields(
        self, skill: GitLabIssueSkill, mock_client: AsyncMock
    ) -> None:
        """update action requires at least one field."""
        with patch.object(skill, "_get_client", return_value=mock_client):
            with patch.object(skill, "_resolve_project", return_value="group/project"):
                result = await skill.execute(action="update", iid=1)

        assert not result.success
        assert "no fields" in result.error.lower()

    @pytest.mark.asyncio
    async def test_close_issue(
        self, skill: GitLabIssueSkill, mock_client: AsyncMock
    ) -> None:
        """close action closes issue."""
        mock_client.put.return_value = {**SAMPLE_ISSUE, "state": "closed"}

        with patch.object(skill, "_get_client", return_value=mock_client):
            with patch.object(skill, "_resolve_project", return_value="group/project"):
                result = await skill.execute(action="close", iid=1)

        assert result.success
        assert "Closed issue" in result.output
        mock_client.put.assert_called_once()

    @pytest.mark.asyncio
    async def test_reopen_issue(
        self, skill: GitLabIssueSkill, mock_client: AsyncMock
    ) -> None:
        """reopen action reopens issue."""
        mock_client.put.return_value = {**SAMPLE_ISSUE, "state": "opened"}

        with patch.object(skill, "_get_client", return_value=mock_client):
            with patch.object(skill, "_resolve_project", return_value="group/project"):
                result = await skill.execute(action="reopen", iid=1)

        assert result.success
        assert "Reopened issue" in result.output

    @pytest.mark.asyncio
    async def test_comment_on_issue(
        self, skill: GitLabIssueSkill, mock_client: AsyncMock
    ) -> None:
        """comment action adds comment."""
        mock_client.post.return_value = {"id": 123, "body": "Comment text"}

        with patch.object(skill, "_get_client", return_value=mock_client):
            with patch.object(skill, "_resolve_project", return_value="group/project"):
                result = await skill.execute(
                    action="comment",
                    iid=1,
                    body="Comment text",
                )

        assert result.success
        assert "Added comment" in result.output

    @pytest.mark.asyncio
    async def test_comment_requires_body(
        self, skill: GitLabIssueSkill, mock_client: AsyncMock
    ) -> None:
        """comment action requires body parameter."""
        with patch.object(skill, "_get_client", return_value=mock_client):
            with patch.object(skill, "_resolve_project", return_value="group/project"):
                result = await skill.execute(action="comment", iid=1)

        assert not result.success
        assert "body" in result.error.lower()

    @pytest.mark.asyncio
    async def test_unknown_action(
        self, skill: GitLabIssueSkill, mock_client: AsyncMock
    ) -> None:
        """Unknown action returns error."""
        with patch.object(skill, "_get_client", return_value=mock_client):
            with patch.object(skill, "_resolve_project", return_value="group/project"):
                result = await skill.execute(action="invalid")

        assert not result.success
        assert "Unknown action" in result.error


class TestGitLabMRSkill(GitLabSkillTestBase):
    """Tests for GitLabMRSkill."""

    @pytest.fixture
    def skill(
        self, services: ServiceContainer, gitlab_config: GitLabConfig
    ) -> GitLabMRSkill:
        """Create skill instance."""
        return GitLabMRSkill(services, gitlab_config)

    @pytest.mark.asyncio
    async def test_list_mrs_success(
        self, skill: GitLabMRSkill, mock_client: AsyncMock
    ) -> None:
        """list action returns MR list."""
        async def mock_paginate(path: str, limit: int = 20, **kwargs: Any):
            for mr in [SAMPLE_MR]:
                yield mr

        mock_client.paginate = mock_paginate

        with patch.object(skill, "_get_client", return_value=mock_client):
            with patch.object(skill, "_resolve_project", return_value="group/project"):
                result = await skill.execute(action="list")

        assert result.success
        assert "1 merge request(s)" in result.output
        assert "Test MR" in result.output
        assert "feature-branch" in result.output

    @pytest.mark.asyncio
    async def test_get_mr_success(
        self, skill: GitLabMRSkill, mock_client: AsyncMock
    ) -> None:
        """get action returns MR details."""
        mock_client.get.return_value = SAMPLE_MR

        with patch.object(skill, "_get_client", return_value=mock_client):
            with patch.object(skill, "_resolve_project", return_value="group/project"):
                result = await skill.execute(action="get", iid=10)

        assert result.success
        assert "Test MR" in result.output
        assert "feature-branch" in result.output
        assert "main" in result.output

    @pytest.mark.asyncio
    async def test_create_mr_success(
        self, skill: GitLabMRSkill, mock_client: AsyncMock
    ) -> None:
        """create action creates MR."""
        mock_client.post.return_value = SAMPLE_MR

        with patch.object(skill, "_get_client", return_value=mock_client):
            with patch.object(skill, "_resolve_project", return_value="group/project"):
                result = await skill.execute(
                    action="create",
                    source_branch="feature-branch",
                    title="Test MR",
                    target_branch="main",
                )

        assert result.success
        assert "Created MR" in result.output

    @pytest.mark.asyncio
    async def test_create_mr_requires_source_branch(
        self, skill: GitLabMRSkill, mock_client: AsyncMock
    ) -> None:
        """create action requires source_branch."""
        with patch.object(skill, "_get_client", return_value=mock_client):
            with patch.object(skill, "_resolve_project", return_value="group/project"):
                result = await skill.execute(
                    action="create",
                    title="Test MR",
                )

        assert not result.success
        assert "source_branch" in result.error.lower()

    @pytest.mark.asyncio
    async def test_merge_mr(
        self, skill: GitLabMRSkill, mock_client: AsyncMock
    ) -> None:
        """merge action merges MR."""
        mock_client.put.return_value = {**SAMPLE_MR, "state": "merged"}

        with patch.object(skill, "_get_client", return_value=mock_client):
            with patch.object(skill, "_resolve_project", return_value="group/project"):
                result = await skill.execute(action="merge", iid=10)

        assert result.success
        assert "Merged MR" in result.output

    @pytest.mark.asyncio
    async def test_diff_mr(
        self, skill: GitLabMRSkill, mock_client: AsyncMock
    ) -> None:
        """diff action returns MR changes."""
        mock_client.get.return_value = [
            {
                "old_path": "file.py",
                "new_path": "file.py",
                "new_file": False,
                "deleted_file": False,
                "renamed_file": False,
                "diff": "+line1\n+line2\n-oldline",
            }
        ]

        with patch.object(skill, "_get_client", return_value=mock_client):
            with patch.object(skill, "_resolve_project", return_value="group/project"):
                result = await skill.execute(action="diff", iid=10)

        assert result.success
        assert "file.py" in result.output
        assert "M " in result.output  # Modified indicator

    @pytest.mark.asyncio
    async def test_commits_mr(
        self, skill: GitLabMRSkill, mock_client: AsyncMock
    ) -> None:
        """commits action returns MR commits."""
        mock_client.get.return_value = [
            {
                "short_id": "abc123",
                "title": "Initial commit",
                "author_name": "testuser",
            }
        ]

        with patch.object(skill, "_get_client", return_value=mock_client):
            with patch.object(skill, "_resolve_project", return_value="group/project"):
                result = await skill.execute(action="commits", iid=10)

        assert result.success
        assert "abc123" in result.output
        assert "Initial commit" in result.output

    @pytest.mark.asyncio
    async def test_pipelines_mr(
        self, skill: GitLabMRSkill, mock_client: AsyncMock
    ) -> None:
        """pipelines action returns MR pipelines."""
        mock_client.get.return_value = [
            {
                "id": 3001,
                "status": "success",
                "ref": "feature-branch",
                "created_at": "2026-01-01T00:00:00Z",
            }
        ]

        with patch.object(skill, "_get_client", return_value=mock_client):
            with patch.object(skill, "_resolve_project", return_value="group/project"):
                result = await skill.execute(action="pipelines", iid=10)

        assert result.success
        assert "#3001" in result.output
        assert "success" in result.output


class TestGitLabBranchSkill(GitLabSkillTestBase):
    """Tests for GitLabBranchSkill."""

    @pytest.fixture
    def skill(
        self, services: ServiceContainer, gitlab_config: GitLabConfig
    ) -> GitLabBranchSkill:
        """Create skill instance."""
        return GitLabBranchSkill(services, gitlab_config)

    @pytest.mark.asyncio
    async def test_list_branches(
        self, skill: GitLabBranchSkill, mock_client: AsyncMock
    ) -> None:
        """list action returns branches."""
        async def mock_paginate(path: str, limit: int = 20, **kwargs: Any):
            for branch in [SAMPLE_BRANCH]:
                yield branch

        mock_client.paginate = mock_paginate

        with patch.object(skill, "_get_client", return_value=mock_client):
            with patch.object(skill, "_resolve_project", return_value="group/project"):
                result = await skill.execute(action="list")

        assert result.success
        assert "1 branch(es)" in result.output
        assert "main" in result.output
        assert "(default)" in result.output

    @pytest.mark.asyncio
    async def test_get_branch(
        self, skill: GitLabBranchSkill, mock_client: AsyncMock
    ) -> None:
        """get action returns branch details."""
        mock_client.get.return_value = SAMPLE_BRANCH

        with patch.object(skill, "_get_client", return_value=mock_client):
            with patch.object(skill, "_resolve_project", return_value="group/project"):
                result = await skill.execute(action="get", name="main")

        assert result.success
        assert "main" in result.output
        assert "Protected: Yes" in result.output

    @pytest.mark.asyncio
    async def test_create_branch(
        self, skill: GitLabBranchSkill, mock_client: AsyncMock
    ) -> None:
        """create action creates branch."""
        mock_client.post.return_value = {"name": "feature-new", "commit": {}}

        with patch.object(skill, "_get_client", return_value=mock_client):
            with patch.object(skill, "_resolve_project", return_value="group/project"):
                result = await skill.execute(
                    action="create",
                    name="feature-new",
                    ref="main",
                )

        assert result.success
        assert "Created branch" in result.output
        assert "feature-new" in result.output

    @pytest.mark.asyncio
    async def test_create_branch_requires_ref(
        self, skill: GitLabBranchSkill, mock_client: AsyncMock
    ) -> None:
        """create action requires ref parameter."""
        with patch.object(skill, "_get_client", return_value=mock_client):
            with patch.object(skill, "_resolve_project", return_value="group/project"):
                result = await skill.execute(action="create", name="feature-new")

        assert not result.success
        assert "ref" in result.error.lower()

    @pytest.mark.asyncio
    async def test_delete_branch(
        self, skill: GitLabBranchSkill, mock_client: AsyncMock
    ) -> None:
        """delete action deletes branch."""
        mock_client.delete.return_value = None

        with patch.object(skill, "_get_client", return_value=mock_client):
            with patch.object(skill, "_resolve_project", return_value="group/project"):
                result = await skill.execute(action="delete", name="feature-old")

        assert result.success
        assert "Deleted branch" in result.output

    @pytest.mark.asyncio
    async def test_protect_branch(
        self, skill: GitLabBranchSkill, mock_client: AsyncMock
    ) -> None:
        """protect action protects branch."""
        mock_client.post.return_value = {"name": "main"}

        with patch.object(skill, "_get_client", return_value=mock_client):
            with patch.object(skill, "_resolve_project", return_value="group/project"):
                result = await skill.execute(
                    action="protect",
                    name="main",
                    push_level="maintainer",
                    merge_level="developer",
                )

        assert result.success
        assert "Protected branch" in result.output
        assert "main" in result.output

    @pytest.mark.asyncio
    async def test_unprotect_branch(
        self, skill: GitLabBranchSkill, mock_client: AsyncMock
    ) -> None:
        """unprotect action removes protection."""
        mock_client.delete.return_value = None

        with patch.object(skill, "_get_client", return_value=mock_client):
            with patch.object(skill, "_resolve_project", return_value="group/project"):
                result = await skill.execute(action="unprotect", name="main")

        assert result.success
        assert "Removed protection" in result.output

    @pytest.mark.asyncio
    async def test_list_protected_branches(
        self, skill: GitLabBranchSkill, mock_client: AsyncMock
    ) -> None:
        """list-protected action returns protected branches."""
        async def mock_paginate(path: str, limit: int = 20, **kwargs: Any):
            yield {
                "name": "main",
                "push_access_levels": [{"access_level": 40}],
                "merge_access_levels": [{"access_level": 40}],
                "allow_force_push": False,
            }

        mock_client.paginate = mock_paginate

        with patch.object(skill, "_get_client", return_value=mock_client):
            with patch.object(skill, "_resolve_project", return_value="group/project"):
                result = await skill.execute(action="list-protected")

        assert result.success
        assert "protected branch(es)" in result.output
        assert "main" in result.output
        assert "maintainer" in result.output


class TestGitLabSkillBaseErrorHandling(GitLabSkillTestBase):
    """Tests for GitLabSkill base class error handling."""

    @pytest.fixture
    def skill(
        self, services: ServiceContainer, gitlab_config: GitLabConfig
    ) -> GitLabIssueSkill:
        """Create skill instance."""
        return GitLabIssueSkill(services, gitlab_config)

    @pytest.mark.asyncio
    async def test_api_error_401_handling(
        self, skill: GitLabIssueSkill
    ) -> None:
        """401 error is formatted appropriately."""
        with patch.object(
            skill, "_resolve_instance",
            side_effect=GitLabAPIError(401, "Unauthorized"),
        ):
            result = await skill.execute(action="list")

        assert not result.success
        assert "Authentication failed" in result.error

    @pytest.mark.asyncio
    async def test_api_error_403_handling(
        self, skill: GitLabIssueSkill
    ) -> None:
        """403 error is formatted appropriately."""
        with patch.object(
            skill, "_resolve_instance",
            side_effect=GitLabAPIError(403, "Forbidden"),
        ):
            result = await skill.execute(action="list")

        assert not result.success
        assert "Permission denied" in result.error

    @pytest.mark.asyncio
    async def test_api_error_404_handling(
        self, skill: GitLabIssueSkill
    ) -> None:
        """404 error is formatted appropriately."""
        with patch.object(
            skill, "_resolve_instance",
            side_effect=GitLabAPIError(404, "Not found"),
        ):
            result = await skill.execute(action="list")

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_value_error_handling(
        self, skill: GitLabIssueSkill
    ) -> None:
        """ValueError is caught and formatted."""
        with patch.object(
            skill, "_resolve_instance",
            side_effect=ValueError("No GitLab instance configured"),
        ):
            result = await skill.execute(action="list")

        assert not result.success
        assert "No GitLab instance" in result.error

    @pytest.mark.asyncio
    async def test_unexpected_error_handling(
        self, skill: GitLabIssueSkill
    ) -> None:
        """Unexpected errors are caught."""
        with patch.object(
            skill, "_resolve_instance",
            side_effect=RuntimeError("Something unexpected"),
        ):
            result = await skill.execute(action="list")

        assert not result.success
        assert "Unexpected error" in result.error


class TestGitLabSkillProjectResolution(GitLabSkillTestBase):
    """Tests for project resolution logic."""

    @pytest.fixture
    def skill(
        self, services: ServiceContainer, gitlab_config: GitLabConfig
    ) -> GitLabIssueSkill:
        """Create skill instance."""
        return GitLabIssueSkill(services, gitlab_config)

    def test_resolve_project_explicit(self, skill: GitLabIssueSkill) -> None:
        """Explicit project parameter is used."""
        result = skill._resolve_project("my-org/my-project")
        assert result == "my-org/my-project"

    def test_resolve_project_from_https_remote(
        self, skill: GitLabIssueSkill, tmp_path: Path
    ) -> None:
        """Project is detected from HTTPS git remote."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="https://gitlab.com/org/project.git\n",
            )

            result = skill._resolve_project(None, cwd=str(tmp_path))

            assert result == "org/project"

    def test_resolve_project_from_ssh_remote(
        self, skill: GitLabIssueSkill, tmp_path: Path
    ) -> None:
        """Project is detected from SSH git remote."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="git@gitlab.com:org/project.git\n",
            )

            result = skill._resolve_project(None, cwd=str(tmp_path))

            assert result == "org/project"

    def test_resolve_project_no_remote_raises(
        self, skill: GitLabIssueSkill, tmp_path: Path
    ) -> None:
        """Error when no project and no git remote."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
            )

            with pytest.raises(ValueError) as exc_info:
                skill._resolve_project(None, cwd=str(tmp_path))

            assert "No project specified" in str(exc_info.value)


class TestGitLabSkillInstanceResolution(GitLabSkillTestBase):
    """Tests for instance resolution logic."""

    @pytest.fixture
    def multi_instance_config(self, gitlab_instance: GitLabInstance) -> GitLabConfig:
        """Config with multiple instances."""
        return GitLabConfig(
            instances={
                "default": gitlab_instance,
                "work": GitLabInstance(url="https://work.gitlab.com", token="work-token"),
            },
            default_instance="default",
        )

    @pytest.fixture
    def skill(
        self, services: ServiceContainer, multi_instance_config: GitLabConfig
    ) -> GitLabIssueSkill:
        """Create skill with multi-instance config."""
        services.register("gitlab_config", multi_instance_config)
        return GitLabIssueSkill(services, multi_instance_config)

    def test_resolve_instance_explicit(self, skill: GitLabIssueSkill) -> None:
        """Explicit instance name is used."""
        instance = skill._resolve_instance("work")
        assert instance.host == "work.gitlab.com"

    def test_resolve_instance_default(self, skill: GitLabIssueSkill) -> None:
        """Default instance is used when not specified."""
        with patch.object(skill, "_detect_instance_from_remote", return_value=None):
            instance = skill._resolve_instance(None)
            assert instance.host == "gitlab.com"

    def test_resolve_instance_nonexistent_raises(self, skill: GitLabIssueSkill) -> None:
        """Error when requesting non-existent instance."""
        with pytest.raises(ValueError) as exc_info:
            skill._resolve_instance("nonexistent")

        assert "not configured" in str(exc_info.value)


class TestGitLabSkillProperties:
    """Tests for skill property methods."""

    def test_issue_skill_properties(
        self,
        tmp_path: Path,
    ) -> None:
        """GitLabIssueSkill has correct properties."""
        services = ServiceContainer()
        services.register("cwd", str(tmp_path))
        config = GitLabConfig()

        skill = GitLabIssueSkill(services, config)

        assert skill.name == "gitlab_issue"
        assert "issue" in skill.description.lower()
        assert skill.parameters["required"] == ["action"]
        assert "list" in skill.parameters["properties"]["action"]["enum"]

    def test_mr_skill_properties(
        self,
        tmp_path: Path,
    ) -> None:
        """GitLabMRSkill has correct properties."""
        services = ServiceContainer()
        services.register("cwd", str(tmp_path))
        config = GitLabConfig()

        skill = GitLabMRSkill(services, config)

        assert skill.name == "gitlab_mr"
        assert "merge request" in skill.description.lower()
        assert "diff" in skill.parameters["properties"]["action"]["enum"]
        assert "merge" in skill.parameters["properties"]["action"]["enum"]

    def test_branch_skill_properties(
        self,
        tmp_path: Path,
    ) -> None:
        """GitLabBranchSkill has correct properties."""
        services = ServiceContainer()
        services.register("cwd", str(tmp_path))
        config = GitLabConfig()

        skill = GitLabBranchSkill(services, config)

        assert skill.name == "gitlab_branch"
        assert "branch" in skill.description.lower()
        assert "protect" in skill.parameters["properties"]["action"]["enum"]
        assert "list-protected" in skill.parameters["properties"]["action"]["enum"]
