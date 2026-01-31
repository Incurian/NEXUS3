"""Tests for GitLab configuration models."""

import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from nexus3.skill.vcs.config import (
    GitLabConfig,
    GitLabInstance,
    load_gitlab_config,
)


class TestGitLabInstance:
    """Tests for GitLabInstance model."""

    def test_create_with_direct_token(self) -> None:
        """GitLabInstance can be created with a direct token."""
        instance = GitLabInstance(
            url="https://gitlab.com",
            token="my-secret-token",
        )
        assert instance.url == "https://gitlab.com"
        assert instance.token == "my-secret-token"
        assert instance.token_env is None

    def test_create_with_token_env(self) -> None:
        """GitLabInstance can be created with an environment variable reference."""
        instance = GitLabInstance(
            url="https://gitlab.work.com",
            token_env="GITLAB_WORK_TOKEN",
        )
        assert instance.url == "https://gitlab.work.com"
        assert instance.token is None
        assert instance.token_env == "GITLAB_WORK_TOKEN"

    def test_create_with_both_token_and_token_env(self) -> None:
        """GitLabInstance can have both token and token_env (direct takes priority)."""
        instance = GitLabInstance(
            url="https://gitlab.com",
            token="direct-token",
            token_env="ENV_TOKEN",
        )
        # get_token() returns direct token first
        assert instance.get_token() == "direct-token"

    def test_get_token_from_direct(self) -> None:
        """get_token() returns direct token when set."""
        instance = GitLabInstance(url="https://gitlab.com", token="my-token")
        assert instance.get_token() == "my-token"

    def test_get_token_from_env(self) -> None:
        """get_token() resolves token from environment variable."""
        instance = GitLabInstance(
            url="https://gitlab.com",
            token_env="TEST_GITLAB_TOKEN",
        )
        with patch.dict(os.environ, {"TEST_GITLAB_TOKEN": "env-token-value"}):
            assert instance.get_token() == "env-token-value"

    def test_get_token_missing_env(self) -> None:
        """get_token() returns None when env var is not set."""
        instance = GitLabInstance(
            url="https://gitlab.com",
            token_env="NONEXISTENT_TOKEN_VAR",
        )
        # Ensure the var is not set
        with patch.dict(os.environ, {}, clear=True):
            result = instance.get_token()
            assert result is None

    def test_get_token_none_when_not_configured(self) -> None:
        """get_token() returns None when neither token nor token_env is set."""
        instance = GitLabInstance(url="https://gitlab.com")
        assert instance.get_token() is None

    def test_host_property(self) -> None:
        """host property extracts hostname from URL."""
        instance = GitLabInstance(url="https://gitlab.example.com", token="x")
        assert instance.host == "gitlab.example.com"

    def test_host_with_port(self) -> None:
        """host property includes port if present."""
        instance = GitLabInstance(url="https://gitlab.local:8443", token="x")
        assert instance.host == "gitlab.local:8443"

    def test_url_validation_valid(self) -> None:
        """Valid URLs pass validation."""
        # Standard HTTPS
        GitLabInstance(url="https://gitlab.com", token="x")
        # With path
        GitLabInstance(url="https://gitlab.com/api", token="x")
        # Local development
        GitLabInstance(url="http://localhost:8080", token="x")
        GitLabInstance(url="http://127.0.0.1:8080", token="x")

    def test_url_validation_rejects_invalid(self) -> None:
        """Invalid URLs are rejected."""
        # Missing scheme
        with pytest.raises(ValidationError) as exc_info:
            GitLabInstance(url="gitlab.com", token="x")
        assert "url" in str(exc_info.value).lower()

        # Empty URL
        with pytest.raises(ValidationError):
            GitLabInstance(url="", token="x")

    def test_extra_fields_rejected(self) -> None:
        """Extra fields are rejected (model_config extra='forbid')."""
        with pytest.raises(ValidationError) as exc_info:
            GitLabInstance(
                url="https://gitlab.com",
                token="x",
                extra_field="not allowed",  # type: ignore
            )
        assert "extra" in str(exc_info.value).lower()


class TestGitLabConfig:
    """Tests for GitLabConfig model."""

    def test_create_empty(self) -> None:
        """GitLabConfig can be created with no instances."""
        config = GitLabConfig()
        assert config.instances == {}
        assert config.default_instance is None

    def test_create_with_single_instance(self) -> None:
        """GitLabConfig with one instance sets it as default."""
        instance = GitLabInstance(url="https://gitlab.com", token="x")
        config = GitLabConfig(instances={"default": instance})

        assert len(config.instances) == 1
        # When no default_instance is set, first one is used
        assert config.default_instance == "default"

    def test_create_with_multiple_instances(self) -> None:
        """GitLabConfig with multiple instances."""
        config = GitLabConfig(
            instances={
                "gitlab": GitLabInstance(url="https://gitlab.com", token="x"),
                "work": GitLabInstance(url="https://work.gitlab.com", token="y"),
            },
            default_instance="work",
        )

        assert len(config.instances) == 2
        assert config.default_instance == "work"

    def test_auto_default_instance(self) -> None:
        """When no default set but instances exist, first is used."""
        config = GitLabConfig(
            instances={
                "alpha": GitLabInstance(url="https://alpha.com", token="a"),
                "beta": GitLabInstance(url="https://beta.com", token="b"),
            }
        )
        # First key in dict becomes default
        assert config.default_instance == "alpha"

    def test_invalid_default_instance(self) -> None:
        """Error when default_instance doesn't exist in instances."""
        with pytest.raises(ValidationError) as exc_info:
            GitLabConfig(
                instances={
                    "gitlab": GitLabInstance(url="https://gitlab.com", token="x"),
                },
                default_instance="nonexistent",
            )
        assert "default_instance" in str(exc_info.value).lower()

    def test_get_instance_by_name(self) -> None:
        """get_instance() retrieves instance by name."""
        gitlab = GitLabInstance(url="https://gitlab.com", token="x")
        work = GitLabInstance(url="https://work.com", token="y")
        config = GitLabConfig(
            instances={"gitlab": gitlab, "work": work},
            default_instance="gitlab",
        )

        assert config.get_instance("gitlab") is gitlab
        assert config.get_instance("work") is work

    def test_get_instance_default(self) -> None:
        """get_instance() returns default when name not specified."""
        gitlab = GitLabInstance(url="https://gitlab.com", token="x")
        config = GitLabConfig(
            instances={"gitlab": gitlab},
            default_instance="gitlab",
        )

        assert config.get_instance() is gitlab
        assert config.get_instance(None) is gitlab

    def test_get_instance_missing(self) -> None:
        """get_instance() returns None for missing instance."""
        config = GitLabConfig(
            instances={"gitlab": GitLabInstance(url="https://gitlab.com", token="x")},
        )

        assert config.get_instance("nonexistent") is None

    def test_get_instance_empty_config(self) -> None:
        """get_instance() returns None when no instances configured."""
        config = GitLabConfig()
        assert config.get_instance() is None


class TestLoadGitLabConfig:
    """Tests for load_gitlab_config function."""

    def test_load_from_dict(self) -> None:
        """load_gitlab_config() creates GitLabConfig from dict."""
        config_dict = {
            "gitlab": {
                "instances": {
                    "default": {
                        "url": "https://gitlab.com",
                        "token": "my-token",
                    }
                },
                "default_instance": "default",
            }
        }

        config = load_gitlab_config(config_dict)

        assert config is not None
        assert len(config.instances) == 1
        assert config.default_instance == "default"
        assert config.get_instance("default") is not None
        assert config.get_instance("default").token == "my-token"

    def test_load_returns_none_when_missing(self) -> None:
        """load_gitlab_config() returns None when no gitlab key."""
        config = load_gitlab_config({})
        assert config is None

        config = load_gitlab_config({"other": "data"})
        assert config is None

    def test_load_with_multiple_instances(self) -> None:
        """load_gitlab_config() handles multiple instances."""
        config_dict = {
            "gitlab": {
                "instances": {
                    "public": {
                        "url": "https://gitlab.com",
                        "token_env": "GITLAB_TOKEN",
                    },
                    "private": {
                        "url": "https://gitlab.mycompany.com",
                        "token_env": "GITLAB_PRIVATE_TOKEN",
                    },
                },
                "default_instance": "public",
            }
        }

        config = load_gitlab_config(config_dict)

        assert config is not None
        assert len(config.instances) == 2
        assert config.default_instance == "public"
        assert config.get_instance("private") is not None
        assert config.get_instance("private").token_env == "GITLAB_PRIVATE_TOKEN"

    def test_load_validation_error(self) -> None:
        """load_gitlab_config() raises on invalid config."""
        config_dict = {
            "gitlab": {
                "instances": {
                    "bad": {
                        "url": "not-a-valid-url",  # Invalid
                        "token": "x",
                    }
                },
            }
        }

        with pytest.raises(ValidationError):
            load_gitlab_config(config_dict)
