"""Shared fixtures for VCS skill tests."""

import socket
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus3.core.allowances import SessionAllowances
from nexus3.core.permissions import AgentPermissions, PermissionLevel, PermissionPolicy
from nexus3.skill.services import ServiceContainer
from nexus3.skill.vcs.config import GitLabConfig, GitLabInstance


# Test domains that need to bypass DNS resolution
TEST_DOMAINS = frozenset({
    "gitlab.work.com",
    "work.gitlab.com",
    "gitlab.example.com",
    "gitlab.local",
    "alpha.com",
    "beta.com",
    "gitlab.mycompany.com",
    "work.com",
})


@pytest.fixture(autouse=True)
def mock_dns_for_test_domains(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip DNS resolution for fake test domains in URL validation.

    The URL validator calls socket.getaddrinfo() to verify hostnames resolve.
    For unit tests with fake domains, we mock this to return success.
    """
    original_getaddrinfo = socket.getaddrinfo

    def mock_getaddrinfo(
        host: str,
        port: int | str | None,
        family: int = 0,
        type: int = 0,
        proto: int = 0,
        flags: int = 0,
    ) -> list[tuple[Any, ...]]:
        # For test domains, return a fake successful resolution
        if host in TEST_DOMAINS:
            return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", port or 443))]
        # For real domains (gitlab.com, localhost, 127.0.0.1), use actual resolution
        return original_getaddrinfo(host, port, family, type, proto, flags)

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)


@pytest.fixture
def gitlab_instance() -> GitLabInstance:
    """Create a GitLabInstance with a direct token."""
    return GitLabInstance(
        url="https://gitlab.com",
        token="test-token-12345",
    )


@pytest.fixture
def gitlab_instance_env() -> GitLabInstance:
    """Create a GitLabInstance using environment variable for token."""
    return GitLabInstance(
        url="https://gitlab.work.com",
        token_env="GITLAB_WORK_TOKEN",
    )


@pytest.fixture
def gitlab_config(gitlab_instance: GitLabInstance, gitlab_instance_env: GitLabInstance) -> GitLabConfig:
    """Create a GitLabConfig with multiple instances."""
    return GitLabConfig(
        instances={
            "default": gitlab_instance,
            "work": gitlab_instance_env,
        },
        default_instance="default",
    )


@pytest.fixture
def mock_services(tmp_path: Path, gitlab_config: GitLabConfig) -> ServiceContainer:
    """Create a mock ServiceContainer with GitLab config."""
    services = ServiceContainer()
    services.register("cwd", str(tmp_path))
    services.register("gitlab_config", gitlab_config)
    return services


@pytest.fixture
def yolo_permissions(tmp_path: Path) -> AgentPermissions:
    """Create YOLO permissions."""
    policy = PermissionPolicy(
        level=PermissionLevel.YOLO,
        cwd=tmp_path,
    )
    return AgentPermissions(
        base_preset="yolo",
        effective_policy=policy,
    )


@pytest.fixture
def trusted_permissions(tmp_path: Path) -> AgentPermissions:
    """Create TRUSTED permissions."""
    policy = PermissionPolicy(
        level=PermissionLevel.TRUSTED,
        cwd=tmp_path,
    )
    return AgentPermissions(
        base_preset="trusted",
        effective_policy=policy,
    )


@pytest.fixture
def sandboxed_permissions(tmp_path: Path) -> AgentPermissions:
    """Create SANDBOXED permissions."""
    policy = PermissionPolicy(
        level=PermissionLevel.SANDBOXED,
        cwd=tmp_path,
        allowed_paths=[tmp_path],
    )
    return AgentPermissions(
        base_preset="sandboxed",
        effective_policy=policy,
    )


@pytest.fixture
def mock_http_client() -> AsyncMock:
    """Create a mock httpx.AsyncClient."""
    client = AsyncMock()
    client.is_closed = False
    client.aclose = AsyncMock()
    return client


# Sample API responses from GitLab
SAMPLE_USER = {
    "id": 1,
    "username": "testuser",
    "email": "test@example.com",
    "name": "Test User",
}

SAMPLE_PROJECT = {
    "id": 123,
    "path_with_namespace": "group/project",
    "name": "Project",
    "description": "A test project",
    "web_url": "https://gitlab.com/group/project",
    "default_branch": "main",
}

SAMPLE_ISSUE = {
    "id": 1001,
    "iid": 1,
    "title": "Test Issue",
    "description": "This is a test issue",
    "state": "opened",
    "author": {"username": "testuser", "id": 1},
    "assignees": [{"username": "assignee1", "id": 2}],
    "labels": ["bug", "priority::high"],
    "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-01-02T00:00:00Z",
    "web_url": "https://gitlab.com/group/project/-/issues/1",
}

SAMPLE_MR = {
    "id": 2001,
    "iid": 10,
    "title": "Test MR",
    "description": "This is a test merge request",
    "state": "opened",
    "author": {"username": "testuser", "id": 1},
    "source_branch": "feature-branch",
    "target_branch": "main",
    "assignees": [],
    "reviewers": [{"username": "reviewer1", "id": 3}],
    "labels": [],
    "draft": False,
    "merge_status": "can_be_merged",
    "has_conflicts": False,
    "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-01-02T00:00:00Z",
    "web_url": "https://gitlab.com/group/project/-/merge_requests/10",
}

SAMPLE_BRANCH = {
    "name": "main",
    "commit": {
        "id": "abc123def456",
        "short_id": "abc123d",
        "title": "Initial commit",
        "author_name": "testuser",
        "author_email": "test@example.com",
        "created_at": "2026-01-01T00:00:00Z",
    },
    "protected": True,
    "default": True,
    "merged": False,
}

SAMPLE_PIPELINE = {
    "id": 3001,
    "status": "success",
    "ref": "main",
    "sha": "abc123def456",
    "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-01-01T01:00:00Z",
    "web_url": "https://gitlab.com/group/project/-/pipelines/3001",
}

SAMPLE_JOB = {
    "id": 4001,
    "name": "test",
    "status": "success",
    "stage": "test",
    "ref": "main",
    "created_at": "2026-01-01T00:00:00Z",
    "started_at": "2026-01-01T00:01:00Z",
    "finished_at": "2026-01-01T00:05:00Z",
    "duration": 240.5,
    "web_url": "https://gitlab.com/group/project/-/jobs/4001",
}
