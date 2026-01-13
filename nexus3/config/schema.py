"""Pydantic models for NEXUS3 configuration validation."""

from pydantic import BaseModel, ConfigDict, Field


class ModelAliasConfig(BaseModel):
    """Configuration for a model alias.

    Allows defining friendly names for models with their settings.

    Example in config.json:
        "models": {
            "fast": {
                "id": "x-ai/grok-code-fast-1",
                "context_window": 131072
            },
            "smart": {
                "id": "anthropic/claude-sonnet-4",
                "context_window": 200000,
                "reasoning": true
            }
        }
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    """Full model identifier (e.g., 'anthropic/claude-sonnet-4')."""

    context_window: int | None = None
    """Context window size. If None, uses provider default."""

    reasoning: bool | None = None
    """Enable extended thinking. If None, uses provider default."""


class ProviderConfig(BaseModel):
    """Configuration for LLM provider."""

    model_config = ConfigDict(extra="forbid")

    type: str = "openrouter"
    api_key_env: str = "OPENROUTER_API_KEY"  # env var name containing API key
    model: str = "x-ai/grok-code-fast-1"
    """Model ID or alias name (resolved via models dict)."""
    base_url: str = "https://openrouter.ai/api/v1"
    context_window: int = 131072
    """Default context window size in tokens. Used for truncation and compaction."""

    reasoning: bool = False
    """Default extended thinking/reasoning setting."""


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


class PermissionsConfig(BaseModel):
    """Top-level permissions configuration."""

    model_config = ConfigDict(extra="forbid")

    default_preset: str = "trusted"
    presets: dict[str, PermissionPresetConfig] = {}
    destructive_tools: list[str] = [
        "write_file",
        "edit_file",
        "bash",
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
    """Model for summarization. None = use main provider.model."""

    summary_budget_ratio: float = 0.25
    """Ratio of available budget for the summary (0.25 = 25%)."""

    recent_preserve_ratio: float = 0.25
    """Ratio to preserve as recent messages (0.25 = 25%)."""

    trigger_threshold: float = 0.9
    """Compact when context exceeds this ratio of available budget."""


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
        default=True,
        description="Use README.md as context when no NEXUS.md exists",
    )


class MCPServerConfig(BaseModel):
    """Configuration for an MCP server.

    MCP (Model Context Protocol) servers provide additional tools that
    agents can use. Each server is configured with either a command
    (for stdio transport) or URL (for HTTP transport).

    Example in config.json:
        "mcp_servers": [
            {
                "name": "test",
                "command": ["python", "-m", "nexus3.mcp.test_server"]
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

    command: list[str] | None = None
    """Command to launch server (for stdio transport)."""

    url: str | None = None
    """URL for HTTP transport (not yet implemented)."""

    env: dict[str, str] | None = None
    """Environment variables for subprocess."""

    enabled: bool = True
    """Whether this server is enabled."""


class ResolvedModel:
    """Result of resolving a model name/alias.

    Contains the effective model settings after resolving an alias
    and merging with provider defaults.
    """

    def __init__(
        self,
        model_id: str,
        context_window: int,
        reasoning: bool,
        alias: str | None = None,
    ) -> None:
        self.model_id = model_id
        self.context_window = context_window
        self.reasoning = reasoning
        self.alias = alias  # Original alias if resolved, None if literal


class Config(BaseModel):
    """Root configuration model."""

    model_config = ConfigDict(extra="forbid")

    provider: ProviderConfig = ProviderConfig()
    models: dict[str, ModelAliasConfig] = {}
    """Model aliases mapping friendly names to model configs."""
    stream_output: bool = True
    max_tool_iterations: int = 10  # Maximum iterations of the tool execution loop
    default_permission_level: str = "trusted"  # yolo, trusted, or sandboxed
    skill_timeout: float = 30.0  # Seconds, 0 = no timeout
    max_concurrent_tools: int = 10  # Max parallel tool executions
    permissions: PermissionsConfig = PermissionsConfig()  # Permission system config
    compaction: CompactionConfig = CompactionConfig()  # Context compaction config
    context: ContextConfig = ContextConfig()  # Context loading config
    mcp_servers: list[MCPServerConfig] = []
    """MCP server configurations for external tool providers."""

    def resolve_model(self, name_or_id: str | None = None) -> ResolvedModel:
        """Resolve a model name/alias to full model settings.

        Args:
            name_or_id: Model alias or full model ID. If None, uses provider.model.

        Returns:
            ResolvedModel with effective model_id, context_window, and reasoning.

        Examples:
            # Use default model from provider config
            resolved = config.resolve_model()

            # Resolve an alias
            resolved = config.resolve_model("fast")

            # Use literal model ID (not in aliases)
            resolved = config.resolve_model("anthropic/claude-sonnet-4")
        """
        effective_name = name_or_id or self.provider.model

        # Check if it's an alias
        if effective_name in self.models:
            alias_config = self.models[effective_name]
            return ResolvedModel(
                model_id=alias_config.id,
                context_window=alias_config.context_window or self.provider.context_window,
                reasoning=alias_config.reasoning if alias_config.reasoning is not None else self.provider.reasoning,
                alias=effective_name,
            )

        # Not an alias - treat as literal model ID, use provider defaults
        return ResolvedModel(
            model_id=effective_name,
            context_window=self.provider.context_window,
            reasoning=self.provider.reasoning,
            alias=None,
        )

    def list_models(self) -> list[str]:
        """List all available model aliases.

        Returns:
            List of alias names defined in config.
        """
        return list(self.models.keys())
