"""Configuration models for VCS integrations."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from nexus3.core.url_validator import UrlSecurityError, validate_url


class GitLabInstance(BaseModel):
    """Configuration for a single GitLab instance."""

    model_config = ConfigDict(extra="forbid")

    url: str
    token: str | None = None
    token_env: str | None = None
    username: str | None = None
    email: str | None = None
    user_id: int | None = None

    @field_validator("url")
    @classmethod
    def validate_url_format(cls, v: str) -> str:
        """Validate URL is well-formed and safe."""
        # Use existing SSRF protection
        # allow_localhost=True for local GitLab development instances
        # Convert UrlSecurityError to ValueError for Pydantic wrapping
        try:
            return validate_url(v, allow_localhost=True, allow_private=False)
        except UrlSecurityError as e:
            raise ValueError(str(e)) from e

    def get_token(self) -> str | None:
        """
        Resolve token from config or environment.

        Resolution order:
        1. Direct token value (if set)
        2. Environment variable from token_env
        3. None (caller should prompt interactively)
        """
        if self.token:
            return self.token
        if self.token_env:
            return os.environ.get(self.token_env)
        return None

    @property
    def host(self) -> str:
        """Extract hostname from URL."""
        return urlparse(self.url).netloc


class GitLabConfig(BaseModel):
    """GitLab configuration with multiple instances."""

    model_config = ConfigDict(extra="forbid")

    instances: dict[str, GitLabInstance] = {}
    default_instance: str | None = None

    @model_validator(mode="after")
    def validate_default_instance(self) -> GitLabConfig:
        """Ensure default_instance references a valid instance."""
        if self.default_instance and self.default_instance not in self.instances:
            raise ValueError(
                f"default_instance '{self.default_instance}' not found in instances"
            )
        # If no default set but instances exist, use first one
        if not self.default_instance and self.instances:
            self.default_instance = next(iter(self.instances))
        return self

    def get_instance(self, name: str | None = None) -> GitLabInstance | None:
        """Get instance by name, or default instance."""
        if name:
            return self.instances.get(name)
        if self.default_instance:
            return self.instances.get(self.default_instance)
        return None


def load_gitlab_config(config_dict: dict[str, Any]) -> GitLabConfig | None:
    """
    Load GitLab config from raw config dict.

    Returns None if no GitLab configuration present.
    """
    gitlab_raw = config_dict.get("gitlab")
    if not gitlab_raw:
        return None

    return GitLabConfig.model_validate(gitlab_raw)
