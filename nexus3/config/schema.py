"""Pydantic models for NEXUS3 configuration validation."""

import os
import warnings
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _normalize_paths(paths: list[str] | None) -> list[str] | None:
    """Normalize and validate a list of paths.

    - Expands ~ to home directory
    - Converts to absolute paths
    - Warns if path doesn't exist or isn't a directory

    Args:
        paths: List of path strings, or None.

    Returns:
        List of normalized absolute path strings, or None.
    """
    if paths is None:
        return None

    normalized = []
    for path_str in paths:
        # Expand ~ and make absolute
        expanded = os.path.expanduser(path_str)
        absolute = os.path.abspath(expanded)

        # Warn if path doesn't exist
        if not os.path.exists(absolute):
            warnings.warn(
                f"Config path does not exist: {path_str!r} -> {absolute}",
                UserWarning,
                stacklevel=4,
            )
        elif not os.path.isdir(absolute):
            warnings.warn(
                f"Config path is not a directory: {path_str!r} -> {absolute}",
                UserWarning,
                stacklevel=4,
            )

        normalized.append(absolute)

    return normalized

# Supported provider types
ProviderType = Literal["openrouter", "openai", "azure", "anthropic", "ollama", "vllm"]


class AuthMethod(str, Enum):
    """Authentication method for API requests."""

    BEARER = "bearer"  # Authorization: Bearer <key>
    API_KEY = "api-key"  # api-key: <key> header (Azure)
    X_API_KEY = "x-api-key"  # x-api-key: <key> header (Anthropic)
    NONE = "none"  # No auth (local Ollama)


class ModelConfig(BaseModel):
    """Configuration for a model under a provider.

    Example in config.json:
        "providers": {
            "openrouter": {
                "models": {
                    "haiku": {
                        "id": "anthropic/claude-haiku-4.5",
                        "context_window": 200000
                    }
                }
            }
        }
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    """Full model identifier sent to the API (e.g., 'anthropic/claude-sonnet-4')."""

    context_window: int = 131072
    """Context window size in tokens."""

    reasoning: bool = False
    """Enable extended thinking/reasoning."""

    guidance: str | None = None
    """Brief usage guidance for this model (e.g., 'Fast, cheap. Good for research.')."""


class ProviderConfig(BaseModel):
    """Configuration for an LLM provider with its models.

    Provider types:
        - openrouter: OpenRouter.ai
        - openai: Direct OpenAI API
        - azure: Azure OpenAI Service
        - anthropic: Anthropic Claude API
        - ollama: Local Ollama server
        - vllm: vLLM OpenAI-compatible server
    """

    model_config = ConfigDict(extra="forbid")

    type: ProviderType = "openrouter"
    """Provider type: openrouter, openai, azure, anthropic, ollama, vllm."""

    api_key_env: str = "OPENROUTER_API_KEY"
    """Environment variable containing API key."""

    base_url: str = "https://openrouter.ai/api/v1"
    """Base URL for API requests."""

    auth_method: AuthMethod = AuthMethod.BEARER
    """How to send the API key (bearer, api-key, x-api-key, none)."""

    extra_headers: dict[str, str] = {}
    """Additional headers to include in API requests."""

    api_version: str | None = None
    """API version string (for Azure: e.g., '2024-02-01')."""

    deployment: str | None = None
    """Azure deployment name (if different from model)."""

    request_timeout: float = Field(default=120.0, gt=0)
    """Timeout in seconds for API requests."""

    max_retries: int = Field(default=3, ge=0, le=10)
    """Maximum number of retry attempts for failed requests."""

    retry_backoff: float = Field(default=1.5, ge=1.0, le=5.0)
    """Exponential backoff multiplier between retries."""

    prompt_caching: bool = True
    """Enable prompt caching. Required for Anthropic, automatic for OpenAI/Azure.
    Reduces cost by ~90% on cached system prompt tokens."""

    allow_insecure_http: bool = False
    """Allow HTTP (non-HTTPS) for non-localhost URLs. SECURITY WARNING: Only enable for
    development/testing. Enabling this on untrusted networks could expose credentials."""

    verify_ssl: bool = True
    """Verify SSL certificates. Set to false for self-signed certificates (on-prem/corporate).
    SECURITY WARNING: Disabling SSL verification makes connections vulnerable to MITM attacks.
    Only disable when connecting to trusted internal servers with self-signed certs."""

    ssl_ca_cert: str | None = None
    """Path to CA certificate file for SSL verification. Use this instead of disabling
    verify_ssl when your on-prem server uses a corporate CA certificate."""

    models: dict[str, ModelConfig] = {}
    """Model aliases available through this provider."""


class ToolPermissionConfig(BaseModel):
    """Per-tool permission configuration in config.json.

    Attributes:
        enabled: Whether the tool is enabled.
        allowed_paths: Per-tool path restrictions.
            - null/omitted: Inherit from preset (default)
            - []: Empty list means tool cannot access any paths (deny all)
            - ["path", ...]: Tool can only access paths within these directories
        timeout: Tool-specific timeout in seconds.
        requires_confirmation: Override confirmation requirement.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    # null = inherit from preset, [] = deny all, ["paths"...] = only these
    allowed_paths: list[str] | None = None
    timeout: float | None = None
    requires_confirmation: bool | None = None

    @field_validator("allowed_paths", mode="before")
    @classmethod
    def normalize_allowed_paths(cls, v: list[str] | None) -> list[str] | None:
        """Normalize allowed_paths to absolute paths with warnings."""
        return _normalize_paths(v)


class PermissionPresetConfig(BaseModel):
    """Custom permission preset in config.json.

    Attributes:
        extends: Base preset to extend (e.g., "trusted").
        description: Human-readable description.
        allowed_paths: Path restrictions for the preset.
            - null/omitted: Unrestricted access (can access any path)
            - []: Empty list means NO paths allowed (deny all)
            - ["path", ...]: Only paths within listed directories allowed
        blocked_paths: Paths always blocked regardless of allowed_paths.
        network_access: Derived from level (SANDBOXED = no network).
        tool_permissions: Per-tool configuration overrides.
        default_tool_timeout: Default timeout for tools in this preset.
    """

    model_config = ConfigDict(extra="forbid")

    extends: str | None = None  # Base preset to extend
    description: str = ""
    # null = unrestricted, [] = deny all, ["paths"...] = only within these
    allowed_paths: list[str] | None = None
    blocked_paths: list[str] = []
    # network_access is derived from level (SANDBOXED = no network), field kept for documentation
    network_access: bool | None = None
    tool_permissions: dict[str, ToolPermissionConfig] = {}
    default_tool_timeout: float | None = None

    @field_validator("allowed_paths", mode="before")
    @classmethod
    def normalize_allowed_paths(cls, v: list[str] | None) -> list[str] | None:
        """Normalize allowed_paths to absolute paths with warnings."""
        return _normalize_paths(v)

    @field_validator("blocked_paths", mode="before")
    @classmethod
    def normalize_blocked_paths(cls, v: list[str]) -> list[str]:
        """Normalize blocked_paths to absolute paths with warnings."""
        return _normalize_paths(v) or []


class PermissionsConfig(BaseModel):
    """Top-level permissions configuration."""

    model_config = ConfigDict(extra="forbid")

    default_preset: str = "sandboxed"
    presets: dict[str, PermissionPresetConfig] = {}
    destructive_tools: list[str] = [
        "write_file",
        "edit_file",
        "bash_safe",
        "shell_UNSAFE",
        "run_python",
        "nexus_destroy",
        "nexus_shutdown",
    ]


class CompactionConfig(BaseModel):
    """Configuration for context compaction/summarization."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    """Whether automatic compaction is enabled."""

    model: str | None = None
    """Model alias for summarization. None = use default_model."""

    summary_budget_ratio: float = 0.25
    """Ratio of available budget for the summary (0.25 = 25%)."""

    recent_preserve_ratio: float = 0.25
    """Ratio to preserve as recent messages (0.25 = 25%)."""

    trigger_threshold: float = 0.9
    """Compact when context exceeds this ratio of available budget."""

    redact_secrets: bool = Field(
        default=True,
        description=(
            "Redact secrets (API keys, passwords, tokens) from conversation "
            "history before sending to the summarization LLM."
        ),
    )
    """Whether to redact secrets before summarization."""


class ClipboardConfig(BaseModel):
    """Configuration for clipboard system."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=True,
        description="Enable clipboard tools",
    )
    inject_into_context: bool = Field(
        default=True,
        description="Auto-inject clipboard index into system prompt",
    )
    max_injected_entries: int = Field(
        default=10,
        ge=0,
        le=50,
        description="Maximum entries to show in context injection",
    )
    show_source_in_injection: bool = Field(
        default=True,
        description="Show source path/lines in context injection",
    )
    max_entry_bytes: int = Field(
        default=1 * 1024 * 1024,  # 1 MB
        ge=1024,
        le=10 * 1024 * 1024,
        description="Maximum size of a single clipboard entry",
    )
    warn_entry_bytes: int = Field(
        default=100 * 1024,  # 100 KB
        ge=1024,
        description="Size threshold for warning on large entries",
    )
    default_ttl_seconds: int | None = Field(
        default=None,
        description="Default TTL for new entries (seconds). None = permanent.",
    )


class ContextConfig(BaseModel):
    """Configuration for context loading.

    Controls how NEXUS.md prompts are loaded from multiple directory layers.

    Example in config.json:
        "context": {
            "ancestor_depth": 2,
            "include_readme": false,
            "readme_as_fallback": true
        }
    """

    model_config = ConfigDict(extra="forbid")

    ancestor_depth: int = Field(
        default=2,
        ge=0,
        le=10,
        description="How many directory levels above CWD to search for .nexus3/",
    )
    include_readme: bool = Field(
        default=False,
        description="Always include README.md in context alongside NEXUS.md",
    )
    readme_as_fallback: bool = Field(
        default=False,
        description=(
            "Use README.md as context when no NEXUS.md exists. "
            "Opt-in for security: READMEs may contain untrusted content."
        ),
    )


class ServerConfig(BaseModel):
    """Configuration for the NEXUS3 HTTP server.

    Controls server behavior when running in --serve mode.

    Example in config.json:
        "server": {
            "host": "0.0.0.0",
            "port": 8765,
            "log_level": "INFO"
        }
    """

    model_config = ConfigDict(extra="forbid")

    host: str = "127.0.0.1"
    """Host address to bind to (use 0.0.0.0 for all interfaces)."""

    port: int = Field(default=8765, ge=1, le=65535)
    """Port number for the HTTP server."""

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    """Logging level for server operations."""


class GitLabInstanceConfig(BaseModel):
    """Configuration for a single GitLab instance.

    Each instance represents a GitLab server (gitlab.com or self-hosted)
    with its authentication credentials.

    SECURITY: GitLab tokens should be stored in environment variables,
    not directly in config files. Use `token_env` to specify the
    environment variable name.

    Example in config.json:
        "gitlab": {
            "instances": {
                "default": {
                    "url": "https://gitlab.com",
                    "token_env": "GITLAB_TOKEN"
                },
                "work": {
                    "url": "https://gitlab.company.com",
                    "token_env": "WORK_GITLAB_TOKEN"
                }
            }
        }
    """

    model_config = ConfigDict(extra="forbid")

    url: str = "https://gitlab.com"
    """Base URL for the GitLab instance (e.g., 'https://gitlab.com')."""

    token_env: str | None = None
    """Environment variable containing the GitLab API token."""

    token: str | None = None
    """Direct token value (NOT RECOMMENDED - use token_env instead).
    If both token and token_env are set, token takes precedence."""

    @model_validator(mode="after")
    def validate_token_config(self) -> "GitLabInstanceConfig":
        """Ensure at least one authentication method is configured."""
        if not self.token and not self.token_env:
            raise ValueError(
                "GitLabInstanceConfig: Must specify either 'token' or 'token_env'"
            )
        return self


class GitLabConfig(BaseModel):
    """Top-level GitLab configuration.

    Supports multiple GitLab instances (e.g., gitlab.com and self-hosted)
    with a default instance for convenience.

    Example in config.json:
        "gitlab": {
            "instances": {
                "default": {
                    "url": "https://gitlab.com",
                    "token_env": "GITLAB_TOKEN"
                }
            },
            "default_instance": "default"
        }
    """

    model_config = ConfigDict(extra="forbid")

    instances: dict[str, GitLabInstanceConfig] = {}
    """Named GitLab instance configurations."""

    default_instance: str | None = None
    """Name of the default instance to use when not specified."""

    @model_validator(mode="after")
    def validate_default_instance(self) -> "GitLabConfig":
        """Ensure default_instance references a valid instance."""
        if self.default_instance and self.default_instance not in self.instances:
            raise ValueError(
                f"GitLabConfig: default_instance '{self.default_instance}' "
                f"not found in instances"
            )
        return self


class MCPServerConfig(BaseModel):
    """Configuration for an MCP server.

    MCP (Model Context Protocol) servers provide additional tools that
    agents can use. Each server is configured with either a command
    (for stdio transport) or URL (for HTTP transport).

    SECURITY: MCP servers receive only safe environment variables by default
    (PATH, HOME, USER, etc.). To pass additional vars:
    - Use `env` for explicit key-value pairs (e.g., secrets from config)
    - Use `env_passthrough` to copy vars from host environment

    Supports two command formats:
    1. NEXUS3 format: command as list ["npx", "-y", "@anthropic/mcp-server-github"]
    2. Official format: command as string + args array
       {"command": "npx", "args": ["-y", "@anthropic/mcp-server-github"]}

    Example in config.json:
        "mcp_servers": [
            {
                "name": "test",
                "command": ["python", "-m", "nexus3.mcp.test_server"]
            },
            {
                "name": "github",
                "command": "npx",
                "args": ["-y", "@anthropic/mcp-server-github"],
                "env_passthrough": ["GITHUB_TOKEN"]
            },
            {
                "name": "postgres",
                "command": ["npx", "-y", "@anthropic/mcp-server-postgres"],
                "env": {"DATABASE_URL": "postgresql://localhost/mydb"}
            }
        ]
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    """Friendly name for the server (used in skill prefixes)."""

    command: str | list[str] | None = None
    """Command to launch server (for stdio transport).
    Can be a list (NEXUS3 format) or string (official format, use with args)."""

    args: list[str] | None = None
    """Arguments for command when command is a string (official format)."""

    url: str | None = None
    """URL for HTTP transport (not yet implemented)."""

    env: dict[str, str] | None = None
    """Explicit environment variables for subprocess (highest priority)."""

    env_passthrough: list[str] | None = None
    """Names of host env vars to pass to subprocess (e.g., ["GITHUB_TOKEN"])."""

    cwd: str | None = None
    """Working directory for the server subprocess."""

    enabled: bool = True
    """Whether this server is enabled."""

    def get_command_list(self) -> list[str]:
        """Return command as list, merging command + args if needed.

        Returns:
            Command as list of strings suitable for subprocess execution.
            Empty list if no command configured.
        """
        if isinstance(self.command, list):
            return self.command  # NEXUS3 format
        elif isinstance(self.command, str):
            # Official format: command string + args array
            cmd = [self.command]
            if self.args:
                cmd.extend(self.args)
            return cmd
        return []

    @model_validator(mode="after")
    def validate_transport(self) -> "MCPServerConfig":
        """Ensure exactly one of command or url is set."""
        if self.command and self.url:
            raise ValueError("MCPServerConfig: Cannot specify both 'command' and 'url'")
        if not self.command and not self.url:
            raise ValueError("MCPServerConfig: Must specify either 'command' or 'url'")
        return self


class ResolvedModel:
    """Result of resolving a model alias.

    Contains the effective model settings after resolving an alias
    and finding its provider.
    """

    def __init__(
        self,
        model_id: str,
        context_window: int,
        reasoning: bool,
        alias: str,
        provider_name: str,
        guidance: str | None = None,
    ) -> None:
        self.model_id = model_id
        self.context_window = context_window
        self.reasoning = reasoning
        self.alias = alias
        self.provider_name = provider_name
        self.guidance = guidance


class Config(BaseModel):
    """Root configuration model.

    Example config.json:
        {
            "default_model": "openrouter/haiku",
            "providers": {
                "openrouter": {
                    "type": "openrouter",
                    "api_key_env": "OPENROUTER_API_KEY",
                    "models": {
                        "haiku": {"id": "anthropic/claude-haiku-4.5", "context_window": 200000}
                    }
                },
                "anthropic": {
                    "type": "anthropic",
                    "api_key_env": "ANTHROPIC_API_KEY",
                    "models": {
                        "haiku-native": {"id": "claude-haiku-4-5", "context_window": 200000}
                    }
                }
            }
        }
    """

    model_config = ConfigDict(extra="forbid")

    default_model: str = "haiku"
    """Default model alias (or 'provider/alias' format)."""

    providers: dict[str, ProviderConfig] = {}
    """Provider configurations with their models."""

    stream_output: bool = True
    max_tool_iterations: int = 10
    default_permission_level: str = "trusted"
    skill_timeout: float = 30.0
    max_concurrent_tools: int = 10
    permissions: PermissionsConfig = PermissionsConfig()
    compaction: CompactionConfig = CompactionConfig()
    clipboard: ClipboardConfig = ClipboardConfig()
    context: ContextConfig = ContextConfig()
    mcp_servers: list[MCPServerConfig] = []
    server: ServerConfig = ServerConfig()
    gitlab: GitLabConfig = GitLabConfig()

    @model_validator(mode="after")
    def validate_unique_aliases(self) -> "Config":
        """Ensure model aliases are globally unique across all providers."""
        seen: dict[str, str] = {}  # alias -> provider_name
        for provider_name, provider_config in self.providers.items():
            for alias in provider_config.models:
                if alias in seen:
                    raise ValueError(
                        f"Duplicate model alias '{alias}' found in providers "
                        f"'{seen[alias]}' and '{provider_name}'"
                    )
                seen[alias] = provider_name
        return self

    @model_validator(mode="after")
    def validate_default_model(self) -> "Config":
        """Ensure default_model references a valid alias."""
        if "/" in self.default_model:
            # Explicit provider/alias format
            provider_name, alias = self.default_model.split("/", 1)
            if provider_name not in self.providers:
                raise ValueError(f"Unknown provider in default_model: {provider_name}")
            if alias not in self.providers[provider_name].models:
                raise ValueError(
                    f"Unknown model alias '{alias}' in provider '{provider_name}'"
                )
        else:
            # Just an alias - look it up across all providers
            alias = self.default_model
            found = False
            for provider_config in self.providers.values():
                if alias in provider_config.models:
                    found = True
                    break
            if not found:
                raise ValueError(f"Unknown model alias: {alias}")
        return self

    def get_provider_config(self, name: str) -> ProviderConfig:
        """Get provider configuration by name.

        Args:
            name: Provider name.

        Returns:
            ProviderConfig for the named provider.

        Raises:
            KeyError: If provider name not found.
        """
        if name in self.providers:
            return self.providers[name]
        raise KeyError(f"Unknown provider: {name}")

    def find_model(self, alias: str) -> tuple[str, ModelConfig]:
        """Find which provider owns a model alias.

        Args:
            alias: Model alias to find.

        Returns:
            Tuple of (provider_name, ModelConfig).

        Raises:
            KeyError: If alias not found in any provider.
        """
        for provider_name, provider_config in self.providers.items():
            if alias in provider_config.models:
                return provider_name, provider_config.models[alias]
        raise KeyError(f"Unknown model alias: {alias}")

    def resolve_model(self, alias: str | None = None) -> ResolvedModel:
        """Resolve a model alias to full model settings.

        Args:
            alias: Model alias. If None, uses default_model.

        Returns:
            ResolvedModel with model_id, context_window, reasoning,
            alias, and provider_name.

        Examples:
            # Use default model
            resolved = config.resolve_model()

            # Resolve an alias
            resolved = config.resolve_model("haiku")

            # Explicit provider/alias format also works
            resolved = config.resolve_model("anthropic/sonnet")
        """
        if alias is None:
            # Use default_model (can be "alias" or "provider/alias")
            alias = self.default_model

        # Check for explicit provider/alias format
        if "/" in alias:
            provider_name, model_alias = alias.split("/", 1)
            if provider_name in self.providers:
                if model_alias in self.providers[provider_name].models:
                    model_config = self.providers[provider_name].models[model_alias]
                    return ResolvedModel(
                        model_id=model_config.id,
                        context_window=model_config.context_window,
                        reasoning=model_config.reasoning,
                        alias=model_alias,
                        provider_name=provider_name,
                        guidance=model_config.guidance,
                    )

        # Search for alias across all providers
        provider_name, model_config = self.find_model(alias)
        return ResolvedModel(
            model_id=model_config.id,
            context_window=model_config.context_window,
            reasoning=model_config.reasoning,
            alias=alias,
            provider_name=provider_name,
            guidance=model_config.guidance,
        )

    def list_models(self) -> list[str]:
        """List all available model aliases.

        Returns:
            List of alias names from all providers.
        """
        aliases = []
        for provider_config in self.providers.values():
            aliases.extend(provider_config.models.keys())
        return aliases

    def list_providers(self) -> list[str]:
        """List all available provider names.

        Returns:
            List of provider names.
        """
        return list(self.providers.keys())

    def get_model_guidance_table(self) -> list[tuple[str, int, str]]:
        """Get model aliases with context and guidance for prompt injection.

        Returns:
            List of (alias, context_window, guidance) tuples.
            Only includes models that have guidance defined.
            Sorted by context_window descending.
        """
        models: list[tuple[str, int, str]] = []
        for provider_config in self.providers.values():
            for alias, model_config in provider_config.models.items():
                if model_config.guidance:
                    models.append((
                        alias,
                        model_config.context_window,
                        model_config.guidance,
                    ))
        # Sort by context_window descending
        models.sort(key=lambda x: x[1], reverse=True)
        return models
