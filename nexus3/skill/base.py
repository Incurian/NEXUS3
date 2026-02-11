"""Base skill interface for NEXUS3.

This module defines the Skill protocol that all skills must implement,
and specialized base classes for different skill categories:

- BaseSkill: Generic base with name/description/parameters storage
- FileSkill: Skills that operate on files (path validation)
- NexusSkill: Skills that communicate with Nexus server (port/api_key/client)
- ExecutionSkill: Skills that run subprocesses (timeout/cwd/output formatting)
- FilteredCommandSkill: Skills with permission-based command filtering (git, etc.)

Skills are the tool system in NEXUS3 - they provide capabilities like
file reading, command execution, and other actions the agent can perform.
"""

import asyncio
import json
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Coroutine
from functools import wraps
from pathlib import Path

# Import ServiceContainer type for factory decorator
# Using TYPE_CHECKING to avoid circular imports
from typing import TYPE_CHECKING, Any, Protocol, TypeVar, runtime_checkable

from nexus3.core.types import ToolResult
from nexus3.core.validation import ALLOWED_INTERNAL_PARAMS, ValidationError

if TYPE_CHECKING:
    from nexus3.client import NexusClient
    from nexus3.core.permissions import PermissionLevel
    from nexus3.skill.services import ServiceContainer


# =============================================================================
# Parameter Validation Decorator
# =============================================================================

def handle_file_errors(
    func: Callable[..., Coroutine[Any, Any, ToolResult]],
) -> Callable[..., Coroutine[Any, Any, ToolResult]]:
    """Decorator that converts PathSecurityError and ValueError to ToolResult errors.

    Use this decorator on FileSkill.execute() methods to automatically handle
    path validation errors without explicit isinstance() checks.

    Example:
        @handle_file_errors
        async def execute(self, path: str = "", **kwargs: Any) -> ToolResult:
            p = self._validate_path(path)  # Now guaranteed to be Path
            content = p.read_text()
            return ToolResult(output=content)
    """
    from nexus3.core.errors import PathSecurityError

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> ToolResult:
        try:
            return await func(*args, **kwargs)
        except PathSecurityError as e:
            return ToolResult(error=str(e))
        except ValueError as e:
            # Catches "No path provided" and similar validation errors
            return ToolResult(error=str(e))

    return wrapper


def validate_skill_parameters(
    strict: bool = False,
) -> Callable[
    [Callable[..., Coroutine[Any, Any, ToolResult]]],
    Callable[..., Coroutine[Any, Any, ToolResult]],
]:
    """Decorator for skill execute() methods that validates kwargs against the skill's schema.

    Validates parameters using JSON Schema before calling the decorated method.
    Returns a ToolResult with error on validation failure instead of raising.

    Args:
        strict: If True, reject unexpected parameters (beyond ALLOWED_INTERNAL_PARAMS).
                If False (default), unknown params are filtered out with a warning.

    Usage:
        class MySkill(FileSkill):
            @validate_skill_parameters()
            async def execute(self, path: str = "", **kwargs) -> ToolResult:
                # 'path' is guaranteed to be valid if we reach here
                ...

    Notes:
        - Requires the skill instance to have a `parameters` property (JSON Schema).
        - This is defense-in-depth; session.py also validates before calling execute().
        - Useful for testing skills directly without going through session layer.
    """
    import jsonschema

    def decorator(
        func: Callable[..., Coroutine[Any, Any, ToolResult]],
    ) -> Callable[..., Coroutine[Any, Any, ToolResult]]:
        @wraps(func)
        async def wrapper(self: "Skill", **kwargs: Any) -> ToolResult:
            schema = self.parameters

            # Validate against JSON Schema
            try:
                jsonschema.validate(kwargs, schema)
            except jsonschema.ValidationError as e:
                # Format a user-friendly error message
                return ToolResult(error=_format_validation_error(e, self.name))

            # Get known properties from schema
            schema_props = set(schema.get("properties", {}).keys())

            # Check for unexpected parameters
            provided = set(kwargs.keys())
            extras = provided - schema_props - ALLOWED_INTERNAL_PARAMS

            if extras:
                if strict:
                    return ToolResult(
                        error=f"Unexpected parameters for {self.name}: {sorted(extras)}"
                    )
                # Non-strict: filter out extras (session.py logs a warning)

            # Filter to known properties + allowed internal params
            validated = {
                k: v
                for k, v in kwargs.items()
                if k in schema_props or k in ALLOWED_INTERNAL_PARAMS
            }

            return await func(self, **validated)

        return wrapper

    return decorator


def _format_validation_error(error: Any, skill_name: str) -> str:
    """Format a jsonschema ValidationError into a user-friendly message.

    Args:
        error: The jsonschema validation error.
        skill_name: Name of the skill for context.

    Returns:
        Human-readable error message.
    """
    # Extract the path to the problematic field
    path = ".".join(str(p) for p in error.absolute_path) if error.absolute_path else ""

    # Common error types with friendly messages
    validator = error.validator

    if validator == "required":
        # error.message is like "'path' is a required property"
        return f"{skill_name}: {error.message}"

    if validator == "type":
        # error.message is like "'foo' is not of type 'integer'"
        if path:
            return f"{skill_name}: Parameter '{path}' has wrong type - {error.message}"
        return f"{skill_name}: {error.message}"

    if validator == "enum":
        if path:
            return f"{skill_name}: Parameter '{path}' must be one of {error.validator_value}"
        return f"{skill_name}: Value must be one of {error.validator_value}"

    if validator == "minimum" or validator == "maximum":
        if path:
            return f"{skill_name}: Parameter '{path}' {error.message}"
        return f"{skill_name}: {error.message}"

    if validator == "minLength" or validator == "maxLength":
        if path:
            return f"{skill_name}: Parameter '{path}' {error.message}"
        return f"{skill_name}: {error.message}"

    # Fallback: use jsonschema's message
    if path:
        return f"{skill_name}: Parameter '{path}' - {error.message}"
    return f"{skill_name}: {error.message}"


def _wrap_with_validation(skill: "Skill") -> None:
    """Wrap a skill's execute method with parameter validation.

    This is called by factory functions to automatically add validation
    to all skills created through the standard factories.

    Args:
        skill: The skill instance to wrap. Modified in place.
    """
    import jsonschema

    original_execute = skill.execute  # Already bound method

    @wraps(original_execute)
    async def validated_execute(**kwargs: Any) -> ToolResult:
        schema = skill.parameters

        # Validate against JSON Schema
        try:
            jsonschema.validate(kwargs, schema)
        except jsonschema.ValidationError as e:
            return ToolResult(error=_format_validation_error(e, skill.name))

        # Get known properties from schema
        schema_props = set(schema.get("properties", {}).keys())

        # Filter to known properties + allowed internal params
        validated = {
            k: v
            for k, v in kwargs.items()
            if k in schema_props or k in ALLOWED_INTERNAL_PARAMS
        }

        return await original_execute(**validated)

    skill.execute = validated_execute  # type: ignore[method-assign]


# Type variable for base_skill_factory
_BS = TypeVar("_BS", bound="BaseSkill")


def base_skill_factory(cls: type[_BS]) -> type[_BS]:
    """Factory decorator for BaseSkill subclasses.

    Attaches a .factory method to the class that wraps execute with parameter validation.
    Use for simple utility skills that don't need FileSkill/ExecutionSkill infrastructure.

    Unlike file_skill_factory (which returns the factory function), this decorator
    returns the class itself, preserving the ability to instantiate it directly
    for testing purposes.

    Usage:
        @base_skill_factory
        class EchoSkill:
            ...

        # The decorated class has a .factory attribute:
        skill = EchoSkill.factory(services)

        # Direct instantiation still works (without validation wrapper):
        raw_skill = EchoSkill()

    Args:
        cls: A BaseSkill subclass (or Skill protocol implementer) to create a factory for.

    Returns:
        The same class with a .factory attribute attached.
    """
    def factory(services: "ServiceContainer") -> _BS:
        skill = cls(services)
        _wrap_with_validation(skill)
        return skill

    # Attach factory to class for convenient access
    cls.factory = factory  # type: ignore[attr-defined]
    return cls


@runtime_checkable
class Skill(Protocol):
    """Protocol for all skills.

    Skills are the fundamental unit of capability in NEXUS3. Each skill
    provides a single, well-defined action that the agent can invoke.

    The protocol defines four required members:
    - name: Unique identifier used in tool calls
    - description: Human-readable text shown to the LLM
    - parameters: JSON Schema defining the expected arguments
    - execute: Async method that performs the skill's action

    Example:
        >>> class ReadFileSkill:
        ...     @property
        ...     def name(self) -> str:
        ...         return "read_file"
        ...
        ...     @property
        ...     def description(self) -> str:
        ...         return "Read contents of a file"
        ...
        ...     @property
        ...     def parameters(self) -> dict[str, Any]:
        ...         return {
        ...             "type": "object",
        ...             "properties": {
        ...                 "path": {"type": "string", "description": "File path to read"}
        ...             },
        ...             "required": ["path"]
        ...         }
        ...
        ...     async def execute(self, **kwargs: Any) -> ToolResult:
        ...         path = kwargs["path"]
        ...         # ... read file ...
        ...         return ToolResult(output=content)
    """

    @property
    def name(self) -> str:
        """Unique skill name (used in tool calls).

        This name is used as the function name when the skill is presented
        to the LLM. It should be snake_case and descriptive.
        """
        ...

    @property
    def description(self) -> str:
        """Human-readable description for LLM.

        This description helps the LLM understand when and how to use
        the skill. Be specific about what the skill does and any
        limitations or requirements.
        """
        ...

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for parameters.

        Returns a JSON Schema object describing the parameters this skill
        accepts. The schema should follow the JSON Schema specification
        and include property descriptions to help the LLM provide
        appropriate arguments.

        Example:
            {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file to read"
                    }
                },
                "required": ["path"]
            }
        """
        ...

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the skill with given arguments.

        Args:
            **kwargs: Arguments matching the parameters schema.

        Returns:
            ToolResult with output on success, or error message on failure.
            The success property of ToolResult indicates whether the
            execution succeeded.
        """
        ...


class BaseSkill(ABC):
    """Convenience base class for implementing skills.

    Provides a structured way to implement skills by storing name,
    description, and parameters as instance attributes set in __init__.
    Subclasses only need to implement the execute() method.

    This is optional - you can implement the Skill protocol directly
    without inheriting from BaseSkill.

    Example:
        >>> class EchoSkill(BaseSkill):
        ...     def __init__(self):
        ...         super().__init__(
        ...             name="echo",
        ...             description="Echo back the input text",
        ...             parameters={
        ...                 "type": "object",
        ...                 "properties": {
        ...                     "text": {"type": "string", "description": "Text to echo"}
        ...                 },
        ...                 "required": ["text"]
        ...             }
        ...         )
        ...
        ...     async def execute(self, **kwargs: Any) -> ToolResult:
        ...         return ToolResult(output=kwargs["text"])
    """

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
    ) -> None:
        """Initialize the skill with its metadata.

        Args:
            name: Unique skill name (snake_case recommended).
            description: Human-readable description for the LLM.
            parameters: JSON Schema for the skill's parameters.
        """
        self._name = name
        self._description = description
        self._parameters = parameters

    @property
    def name(self) -> str:
        """Unique skill name (used in tool calls)."""
        return self._name

    @property
    def description(self) -> str:
        """Human-readable description for LLM."""
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for parameters."""
        return self._parameters

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the skill with given arguments.

        Subclasses must implement this method to provide the skill's
        actual functionality.

        Args:
            **kwargs: Arguments matching the parameters schema.

        Returns:
            ToolResult with output on success, or error message on failure.
        """
        ...


class FileSkill(ABC):
    """Base class for skills that operate on files.

    Provides unified path validation via validate_path(). All file-based
    skills should inherit from this class to ensure consistent security
    behavior across permission modes.

    Path validation semantics (resolved per-tool at validation time):
    - allowed_paths=None: Unrestricted access (TRUSTED/YOLO modes)
    - allowed_paths=[]: Deny all access
    - allowed_paths=[Path(...)]: Only allow within these directories

    Per-tool path overrides (e.g., allowed_write_paths) are automatically
    resolved via ServiceContainer.get_tool_allowed_paths(). This allows
    different tools to have different path restrictions within the same agent.

    Symlinks are always resolved before checking against allowed_paths,
    so a symlink pointing outside the sandbox will be rejected.

    Example:
        >>> class ReadFileSkill(FileSkill):
        ...     @property
        ...     def name(self) -> str:
        ...         return "read_file"
        ...
        ...     @property
        ...     def description(self) -> str:
        ...         return "Read file contents"
        ...
        ...     @property
        ...     def parameters(self) -> dict[str, Any]:
        ...         return {
        ...             "type": "object",
        ...             "properties": {
        ...                 "path": {"type": "string", "description": "File path"}
        ...             },
        ...             "required": ["path"]
        ...         }
        ...
        ...     @handle_file_errors
        ...     async def execute(self, path: str = "", **kwargs: Any) -> ToolResult:
        ...         p = self._validate_path(path)  # Returns Path, raises on error
        ...         content = p.read_text()
        ...         return ToolResult(output=content)
    """

    def __init__(self, services: "ServiceContainer") -> None:
        """Initialize FileSkill with ServiceContainer for path resolution.

        Args:
            services: ServiceContainer for accessing permissions and resolving
                per-tool allowed_paths at validation time.
        """
        self._services = services

    @property
    def _allowed_paths(self) -> list[Path] | None:
        """Get effective allowed_paths for this skill.

        Resolves per-tool path overrides via ServiceContainer.
        This property is provided for skills that need raw access to
        allowed_paths (e.g., glob/grep that check many paths in a loop).

        Returns:
            List of allowed Path objects, or None for unrestricted access.
        """
        return self._services.get_tool_allowed_paths(self.name)

    def _validate_path(self, path: str) -> Path:
        """Validate and resolve a path for file operations.

        Uses PathResolver for unified path resolution that:
        - Resolves relative paths against agent's cwd (not process cwd)
        - Applies per-tool allowed_paths restrictions
        - Follows symlinks and validates containment

        Use @handle_file_errors decorator on execute() to convert exceptions
        to ToolResult errors automatically.

        Args:
            path: Path string to validate.

        Returns:
            Resolved Path if valid.

        Raises:
            ValueError: If path is empty.
            PathSecurityError: If path validation fails.
        """
        from nexus3.core.resolver import PathResolver

        if not path:
            raise ValueError("No path provided")

        resolver = PathResolver(self._services)
        return resolver.resolve(path, tool_name=self.name)

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique skill name (used in tool calls)."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description for LLM."""
        ...

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for parameters."""
        ...

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the skill with given arguments."""
        ...


# Type variable for the factory decorator
_T = TypeVar("_T", bound=FileSkill)


def file_skill_factory(cls: type[_T]) -> Callable[["ServiceContainer"], _T]:
    """Factory decorator for FileSkill subclasses.

    Creates a standard factory function that passes ServiceContainer
    to the skill constructor. The skill uses ServiceContainer at
    validation time to resolve per-tool allowed_paths.

    Usage:
        @file_skill_factory
        class MyFileSkill(FileSkill):
            ...

        # The decorated class now has a .factory attribute:
        skill = MyFileSkill.factory(services)

        # Or use directly:
        factory_fn = file_skill_factory(MyFileSkill)
        skill = factory_fn(services)

    Args:
        cls: A FileSkill subclass to create a factory for.

    Returns:
        A factory function that creates instances of the skill.
    """
    def factory(services: "ServiceContainer") -> _T:
        skill = cls(services)
        _wrap_with_validation(skill)
        return skill

    # Also attach as class attribute for convenience
    cls.factory = factory  # type: ignore[attr-defined]
    return factory


# =============================================================================
# NexusSkill - Base class for skills that communicate with Nexus server
# =============================================================================

class NexusSkill(ABC):
    """Base class for skills that communicate with a Nexus server.

    Provides common functionality for port resolution, API key discovery,
    URL construction, and client connection handling.

    All nexus_* skills should inherit from this class to ensure consistent
    behavior and reduce code duplication.

    Example:
        >>> class NexusSendSkill(NexusSkill):
        ...     @property
        ...     def name(self) -> str:
        ...         return "nexus_send"
        ...
        ...     @property
        ...     def description(self) -> str:
        ...         return "Send a message to a Nexus agent"
        ...
        ...     @property
        ...     def parameters(self) -> dict[str, Any]:
        ...         return {...}
        ...
        ...     async def execute(self, agent_id: str = "", content: str = "",
        ...                       port: int | None = None, **kwargs) -> ToolResult:
        ...         if not agent_id:
        ...             return ToolResult(error="No agent_id provided")
        ...         return await self._execute_with_client(
        ...             port=port,
        ...             agent_id=agent_id,
        ...             operation=lambda client: client.send(content)
        ...         )
    """

    _default_port: int | None = None  # Class-level cache
    DEFAULT_TIMEOUT: float = 300.0  # 5 minutes - agent operations can take a while

    def __init__(self, services: "ServiceContainer") -> None:
        """Initialize NexusSkill with service container.

        Args:
            services: ServiceContainer for accessing shared services like
                      api_key, port, agent_id, and permissions.
        """
        self._services = services

    @classmethod
    def _get_default_port(cls) -> int:
        """Get default port from config, with class-level caching."""
        if cls._default_port is None:
            try:
                from nexus3.config.loader import load_config
                config = load_config()
                cls._default_port = config.server.port
            except Exception:
                cls._default_port = 8765
        return cls._default_port

    def _get_port(self, port: int | None) -> int:
        """Get the port to use, checking parameter, services, then default."""
        if port is not None:
            return port
        svc_port: int | None = self._services.get("port")
        if svc_port is not None:
            return svc_port
        return self._get_default_port()

    def _get_api_key(self, port: int) -> str | None:
        """Get API key from ServiceContainer or auto-discover."""
        from nexus3.rpc.auth import discover_rpc_token
        api_key: str | None = self._services.get("api_key")
        if api_key:
            return api_key
        return discover_rpc_token(port=port)

    def _build_url(self, port: int, agent_id: str | None = None) -> str:
        """Build URL for the Nexus server.

        Args:
            port: Server port
            agent_id: Optional agent ID for agent-specific endpoints

        Returns:
            URL string (e.g., "http://127.0.0.1:8765" or
            "http://127.0.0.1:8765/agent/worker-1")
        """
        base = f"http://127.0.0.1:{port}"
        if agent_id:
            return f"{base}/agent/{agent_id}"
        return base

    def _can_use_direct_api(self, port: int | None) -> bool:
        """Check if we can use DirectAgentAPI for in-process communication.

        Returns True if:
        - agent_api is available in services
        - port is None or matches the default port (same process)

        Using direct API bypasses HTTP for same-process agent communication,
        eliminating network overhead and JSON serialization.
        """
        if not self._services.has("agent_api"):
            return False
        # If explicit port specified and differs from default, use HTTP
        if port is not None and port != self._get_default_port():
            return False
        return True

    def _validate_agent_id(self, agent_id: str) -> ToolResult | None:
        """Validate agent_id parameter, returning ToolResult error if invalid.

        Common pattern used by most nexus_* skills. Returns None if valid,
        or a ToolResult with error message if invalid.

        Args:
            agent_id: The agent ID to validate.

        Returns:
            None if valid, ToolResult(error=...) if invalid.
        """
        from nexus3.core.validation import validate_agent_id

        if not agent_id:
            return ToolResult(error="No agent_id provided")
        try:
            validate_agent_id(agent_id)
        except ValidationError as e:
            return ToolResult(error=f"Invalid agent_id: {e.message}")
        return None

    async def _execute_with_client(
        self,
        port: int | None,
        operation: Callable[["NexusClient"], Awaitable[dict[str, Any]]],
        agent_id: str | None = None,
    ) -> ToolResult:
        """Execute an operation with a NexusClient, handling common patterns.

        This method handles:
        - In-process path (DirectAgentAPI) when available - bypasses HTTP
        - HTTP path (NexusClient) as fallback
        - Port resolution
        - URL construction and validation
        - API key discovery
        - Client context management
        - JSON serialization of results
        - Error handling

        Args:
            port: Optional port override
            operation: Async callable that takes a NexusClient and returns a dict
            agent_id: Optional agent ID for agent-specific endpoints

        Returns:
            ToolResult with JSON output or error message
        """
        from nexus3.client import ClientError, NexusClient

        # Try in-process path first (bypasses HTTP for same-process communication)
        if self._can_use_direct_api(port):
            from nexus3.rpc.agent_api import ClientAdapter, DirectAgentAPI

            api: DirectAgentAPI = self._services.get("agent_api")
            scoped = api.for_agent(agent_id) if agent_id else None
            adapter = ClientAdapter(api, scoped)
            try:
                result = await operation(adapter)
                return ToolResult(output=json.dumps(result))
            except ClientError as e:
                return ToolResult(error=str(e))

        # Fall back to HTTP path
        from nexus3.core.url_validator import UrlSecurityError, validate_url

        actual_port = self._get_port(port)
        url = self._build_url(actual_port, agent_id)
        api_key = self._get_api_key(actual_port)

        try:
            validated_url = validate_url(url, allow_localhost=True)
        except UrlSecurityError as e:
            return ToolResult(error=f"URL validation failed: {e}")

        try:
            async with NexusClient(
                validated_url, api_key=api_key, timeout=self.DEFAULT_TIMEOUT
            ) as client:
                result = await operation(client)
                return ToolResult(output=json.dumps(result))
        except ClientError as e:
            return ToolResult(error=str(e))

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique skill name (used in tool calls)."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description for LLM."""
        ...

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for parameters."""
        ...

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the skill with given arguments."""
        ...


_NS = TypeVar("_NS", bound=NexusSkill)


def nexus_skill_factory(cls: type[_NS]) -> Callable[["ServiceContainer"], _NS]:
    """Factory decorator for NexusSkill subclasses.

    Creates a standard factory function that passes the ServiceContainer
    to the skill constructor.

    Args:
        cls: A NexusSkill subclass to create a factory for.

    Returns:
        A factory function that creates instances of the skill.
    """
    def factory(services: "ServiceContainer") -> _NS:
        skill = cls(services)
        _wrap_with_validation(skill)
        return skill

    cls.factory = factory  # type: ignore[attr-defined]
    return factory


# =============================================================================
# ExecutionSkill - Base class for skills that run subprocesses
# =============================================================================

class ExecutionSkill(ABC):
    """Base class for skills that execute subprocesses.

    Provides common functionality for timeout enforcement, working directory
    resolution with sandbox validation, subprocess output capture, and result formatting.

    Security: Working directory is validated against allowed_paths from the
    ServiceContainer's permissions. This prevents sandbox escape via cwd parameter.

    Used by bash and run_python skills.

    Example:
        >>> class BashSkill(ExecutionSkill):
        ...     @property
        ...     def name(self) -> str:
        ...         return "bash"
        ...
        ...     async def _create_process(self, work_dir: str | None):
        ...         return await asyncio.create_subprocess_shell(
        ...             self._command,
        ...             stdout=asyncio.subprocess.PIPE,
        ...             stderr=asyncio.subprocess.PIPE,
        ...             cwd=work_dir,
        ...             env={**os.environ},
        ...         )
        ...
        ...     async def execute(self, command: str = "", **kwargs) -> ToolResult:
        ...         if not command:
        ...             return ToolResult(error="Command is required")
        ...         self._command = command
        ...         return await self._execute_subprocess(
        ...             timeout=kwargs.get("timeout", 30),
        ...             cwd=kwargs.get("cwd"),
        ...             timeout_message="Command timed out after {timeout}s"
        ...         )
    """

    MAX_TIMEOUT: int = 300
    DEFAULT_TIMEOUT: int = 30

    def __init__(self, services: "ServiceContainer") -> None:
        """Initialize ExecutionSkill with ServiceContainer.

        Args:
            services: ServiceContainer for accessing permissions and resolving
                allowed_paths at validation time.
        """
        self._services = services

    @property
    def _allowed_paths(self) -> list[Path] | None:
        """Get effective allowed_paths for this skill.

        Resolves per-tool path overrides via ServiceContainer.

        Returns:
            List of allowed Path objects, or None for unrestricted access.
        """
        return self._services.get_tool_allowed_paths(self.name)

    def _enforce_timeout(self, timeout: int) -> int:
        """Enforce timeout limits (1 to MAX_TIMEOUT seconds)."""
        return min(max(timeout, 1), self.MAX_TIMEOUT)

    def _resolve_working_directory(self, cwd: str | None) -> tuple[str | None, str | None]:
        """Resolve working directory for subprocess execution.

        Uses PathResolver for unified path resolution that:
        - Returns agent's cwd if no cwd specified
        - Resolves relative paths against agent's cwd
        - Validates against per-tool allowed_paths
        - Ensures path exists and is a directory

        Args:
            cwd: Working directory path or None for agent's default.

        Returns:
            Tuple of (resolved_cwd_string, error_message).
            If error_message is not None, resolved_cwd will be None.
        """
        from nexus3.core.resolver import PathResolver

        resolver = PathResolver(self._services)
        return resolver.resolve_cwd(cwd, tool_name=self.name)

    def _format_output(
        self,
        stdout: bytes,
        stderr: bytes,
        exit_code: int | None
    ) -> str:
        """Format subprocess output for return.

        Args:
            stdout: Raw stdout bytes
            stderr: Raw stderr bytes
            exit_code: Process exit code

        Returns:
            Formatted output string
        """
        stdout_str = stdout.decode("utf-8", errors="replace").strip()
        stderr_str = stderr.decode("utf-8", errors="replace").strip()

        parts = []
        if stdout_str:
            parts.append(stdout_str)
        if stderr_str:
            if stdout_str:
                parts.append(f"\n[stderr]\n{stderr_str}")
            else:
                parts.append(f"[stderr]\n{stderr_str}")

        output = "\n".join(parts) if parts else "(no output)"

        if exit_code is not None and exit_code != 0:
            output += f"\n\n[exit code: {exit_code}]"

        return output

    @abstractmethod
    async def _create_process(
        self,
        work_dir: str | None
    ) -> asyncio.subprocess.Process:
        """Create the subprocess. Subclasses implement this.

        Args:
            work_dir: Working directory for the process

        Returns:
            The created subprocess
        """
        ...

    async def _execute_subprocess(
        self,
        timeout: int,
        cwd: str | None,
        timeout_message: str = "Execution timed out after {timeout}s"
    ) -> ToolResult:
        """Execute subprocess with common handling.

        Args:
            timeout: Timeout in seconds
            cwd: Working directory
            timeout_message: Message template for timeout errors

        Returns:
            ToolResult with output or error
        """
        timeout = self._enforce_timeout(timeout)

        work_dir, error = self._resolve_working_directory(cwd)
        if error:
            return ToolResult(error=error)

        try:
            process = await self._create_process(work_dir)

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
            except TimeoutError:
                from nexus3.core.process import terminate_process_tree
                await terminate_process_tree(process)
                return ToolResult(error=timeout_message.format(timeout=timeout))

            output = self._format_output(stdout, stderr, process.returncode)
            return ToolResult(output=output)

        except OSError as e:
            return ToolResult(error=f"Failed to execute: {e}")
        except Exception as e:
            return ToolResult(error=f"Error during execution: {e}")

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique skill name (used in tool calls)."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description for LLM."""
        ...

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for parameters."""
        ...

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the skill with given arguments."""
        ...


def execution_skill_factory(
    cls: type["ExecutionSkill"],
) -> Callable[["ServiceContainer"], "ExecutionSkill"]:
    """Factory decorator for ExecutionSkill subclasses.

    Args:
        cls: An ExecutionSkill subclass to create a factory for.

    Returns:
        A factory function that creates instances of the skill with
        ServiceContainer for sandbox validation.
    """
    def factory(services: "ServiceContainer") -> "ExecutionSkill":
        skill = cls(services)  # Pass services for sandbox validation
        _wrap_with_validation(skill)
        return skill

    cls.factory = factory  # type: ignore[attr-defined]
    return factory


# =============================================================================
# FilteredCommandSkill - Base class for permission-filtered command execution
# =============================================================================

class FilteredCommandSkill(ABC):
    """Base class for skills that filter commands based on permission level.

    Provides common functionality for:
    - Command filtering based on permission level (allow/block lists)
    - Working directory validation against allowed paths
    - Subprocess execution with output capture

    Used by git skill, and potentially future skills like docker, kubectl, etc.

    The filtering model:
    - YOLO: All commands allowed
    - TRUSTED: Commands not matching blocked patterns allowed
    - SANDBOXED: Only whitelisted read-only commands allowed

    Example:
        >>> class GitSkill(FilteredCommandSkill):
        ...     @property
        ...     def name(self) -> str:
        ...         return "git"
        ...
        ...     def get_read_only_commands(self) -> frozenset[str]:
        ...         return frozenset({"status", "log", "diff", "branch", "show"})
        ...
        ...     def get_blocked_patterns(self) -> list[tuple[str, str]]:
        ...         return [
        ...             ("push.*--force", "Force push is blocked"),
        ...             ("reset.*--hard", "Hard reset is blocked"),
        ...         ]
    """

    def __init__(self, services: "ServiceContainer") -> None:
        """Initialize FilteredCommandSkill with ServiceContainer.

        Args:
            services: ServiceContainer for accessing permissions and resolving
                per-tool allowed_paths at validation time.
        """
        self._services = services

    @property
    def _allowed_paths(self) -> list[Path] | None:
        """Get effective allowed_paths for this skill.

        Resolves per-tool path overrides via ServiceContainer.

        Returns:
            List of allowed Path objects, or None for unrestricted access.
        """
        return self._services.get_tool_allowed_paths(self.name)

    @property
    def _permission_level(self) -> "PermissionLevel | None":
        """Get permission level from ServiceContainer.

        Uses the typed accessor which automatically resolves from
        permissions if not directly set.

        Returns:
            The permission level, or None if not determinable.
        """
        return self._services.get_permission_level()

    def _validate_cwd(self, cwd: str) -> tuple[Path, str | None]:
        """Validate working directory for filtered command execution.

        Uses PathResolver for unified path resolution that:
        - Resolves relative paths against agent's cwd
        - Validates against per-tool allowed_paths
        - Ensures path exists and is a directory

        Args:
            cwd: Working directory path to validate.

        Returns:
            Tuple of (resolved_Path, error_message).
            If error_message is not None, the Path value should not be used.
        """
        from nexus3.core.errors import PathSecurityError
        from nexus3.core.resolver import PathResolver

        resolver = PathResolver(self._services)
        try:
            resolved = resolver.resolve(cwd, tool_name=self.name, must_exist=True, must_be_dir=True)
            return resolved, None
        except PathSecurityError as e:
            return Path(cwd), str(e)  # Return original path with error for logging

    def _is_command_allowed(self, command: str) -> tuple[bool, str | None]:
        """Check if command is allowed based on permission level.

        Args:
            command: The command string to check

        Returns:
            Tuple of (is_allowed, error_message_or_none)
        """
        import re

        from nexus3.core.permissions import PermissionLevel

        # No permission level set = unrestricted
        if self._permission_level is None:
            return True, None

        # YOLO = everything allowed
        if self._permission_level == PermissionLevel.YOLO:
            return True, None

        # Extract the subcommand (first word after the tool name)
        parts = command.split()
        subcommand = parts[0] if parts else ""

        # SANDBOXED = only read-only commands
        if self._permission_level == PermissionLevel.SANDBOXED:
            read_only = self.get_read_only_commands()
            if subcommand not in read_only:
                return (
                    False,
                    f"Command '{subcommand}' not allowed in"
                    f" sandboxed mode. Allowed: {sorted(read_only)}",
                )
            return True, None

        # TRUSTED = block dangerous patterns
        for pattern, message in self.get_blocked_patterns():
            if re.search(pattern, command):
                return False, message

        return True, None

    @abstractmethod
    def get_read_only_commands(self) -> frozenset[str]:
        """Get commands allowed in SANDBOXED mode.

        Returns:
            Frozenset of allowed command names (e.g., {"status", "log", "diff"})
        """
        ...

    @abstractmethod
    def get_blocked_patterns(self) -> list[tuple[str, str]]:
        """Get regex patterns blocked in TRUSTED mode.

        Returns:
            List of (pattern, error_message) tuples
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique skill name (used in tool calls)."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description for LLM."""
        ...

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for parameters."""
        ...

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the skill with given arguments."""
        ...


_FC = TypeVar("_FC", bound=FilteredCommandSkill)


def filtered_command_skill_factory(cls: type[_FC]) -> Callable[["ServiceContainer"], _FC]:
    """Factory decorator for FilteredCommandSkill subclasses.

    Creates a standard factory function that passes ServiceContainer to
    the skill constructor. The skill resolves allowed_paths and permission_level
    at validation time.

    Args:
        cls: A FilteredCommandSkill subclass to create a factory for.

    Returns:
        A factory function that creates instances of the skill.
    """
    def factory(services: "ServiceContainer") -> _FC:
        skill = cls(services)
        _wrap_with_validation(skill)
        return skill

    cls.factory = factory  # type: ignore[attr-defined]
    return factory
