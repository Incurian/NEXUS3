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

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol, TypeVar, runtime_checkable
import asyncio
import json
import os

from nexus3.core.paths import validate_path
from nexus3.core.types import ToolResult

# Import ServiceContainer type for factory decorator
# Using TYPE_CHECKING to avoid circular imports
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from nexus3.skill.services import ServiceContainer
    from nexus3.client import NexusClient
    from nexus3.core.permissions import PermissionLevel


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

    Path validation semantics:
    - allowed_paths=None: Unrestricted access (TRUSTED/YOLO modes)
    - allowed_paths=[]: Deny all access
    - allowed_paths=[Path(...)]: Only allow within these directories

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
        ...     async def execute(self, path: str = "", **kwargs: Any) -> ToolResult:
        ...         validated = self._validate_path(path)
        ...         content = validated.read_text()
        ...         return ToolResult(output=content)
    """

    def __init__(self, allowed_paths: list[Path] | None = None) -> None:
        """Initialize FileSkill with path restrictions.

        Args:
            allowed_paths: List of allowed directories for path validation.
                - None: No sandbox validation (unrestricted access)
                - []: Empty list means NO paths allowed (all operations denied)
                - [Path(...)]: Only allow operations within these directories
        """
        self._allowed_paths = allowed_paths

    def _validate_path(self, path: str | Path) -> Path:
        """Validate and resolve a path against allowed_paths.

        Resolves symlinks and checks that the resolved path is within
        allowed directories (if restrictions are set).

        Args:
            path: The path to validate.

        Returns:
            The validated, resolved Path.

        Raises:
            PathSecurityError: If path is outside allowed directories.
        """
        return validate_path(path, allowed_paths=self._allowed_paths)

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

    Creates a standard factory function that extracts 'allowed_paths'
    from the ServiceContainer and passes it to the skill constructor.

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
        allowed_paths: list[Path] | None = services.get("allowed_paths")
        return cls(allowed_paths=allowed_paths)

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
        from nexus3.rpc.auth import discover_api_key
        api_key: str | None = self._services.get("api_key")
        if api_key:
            return api_key
        return discover_api_key(port=port)

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

    async def _execute_with_client(
        self,
        port: int | None,
        operation: Callable[["NexusClient"], Awaitable[dict[str, Any]]],
        agent_id: str | None = None,
    ) -> ToolResult:
        """Execute an operation with a NexusClient, handling common patterns.

        This method handles:
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
        from nexus3.core.url_validator import UrlSecurityError, validate_url

        actual_port = self._get_port(port)
        url = self._build_url(actual_port, agent_id)
        api_key = self._get_api_key(actual_port)

        try:
            validated_url = validate_url(url, allow_localhost=True)
        except UrlSecurityError as e:
            return ToolResult(error=f"URL validation failed: {e}")

        try:
            async with NexusClient(validated_url, api_key=api_key) as client:
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
        return cls(services)

    cls.factory = factory  # type: ignore[attr-defined]
    return factory


# =============================================================================
# ExecutionSkill - Base class for skills that run subprocesses
# =============================================================================

class ExecutionSkill(ABC):
    """Base class for skills that execute subprocesses.

    Provides common functionality for timeout enforcement, working directory
    resolution, subprocess output capture, and result formatting.

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

    def __init__(self) -> None:
        """Initialize ExecutionSkill."""
        pass

    def _enforce_timeout(self, timeout: int) -> int:
        """Enforce timeout limits (1 to MAX_TIMEOUT seconds)."""
        return min(max(timeout, 1), self.MAX_TIMEOUT)

    def _resolve_working_directory(self, cwd: str | None) -> tuple[str | None, str | None]:
        """Resolve and validate working directory.

        Args:
            cwd: Working directory path (or None for current)

        Returns:
            Tuple of (resolved_path_or_none, error_message_or_none)
        """
        if not cwd:
            return None, None

        work_path = Path(cwd).expanduser()
        if not work_path.is_absolute():
            work_path = Path.cwd() / work_path
        if not work_path.is_dir():
            return None, f"Working directory not found: {cwd}"
        return str(work_path), None

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
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
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


def execution_skill_factory(cls: type["ExecutionSkill"]) -> Callable[["ServiceContainer"], "ExecutionSkill"]:
    """Factory decorator for ExecutionSkill subclasses.

    Args:
        cls: An ExecutionSkill subclass to create a factory for.

    Returns:
        A factory function that creates instances of the skill.
    """
    def factory(services: "ServiceContainer") -> "ExecutionSkill":
        return cls()

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

    def __init__(
        self,
        allowed_paths: list[Path] | None = None,
        permission_level: "PermissionLevel | None" = None,
    ) -> None:
        """Initialize FilteredCommandSkill.

        Args:
            allowed_paths: Paths where cwd is allowed (None = unrestricted)
            permission_level: Permission level for command filtering
        """
        self._allowed_paths = allowed_paths
        self._permission_level = permission_level

    def _validate_cwd(self, cwd: str) -> tuple[Path, str | None]:
        """Validate working directory against allowed paths.

        Args:
            cwd: Working directory path

        Returns:
            Tuple of (resolved_path, error_message_or_none)
        """
        from nexus3.core.errors import PathSecurityError

        try:
            work_dir = validate_path(cwd, allowed_paths=self._allowed_paths)
            if not work_dir.is_dir():
                return work_dir, f"Not a directory: {cwd}"
            return work_dir, None
        except PathSecurityError as e:
            return Path(cwd), str(e)

    def _is_command_allowed(self, command: str) -> tuple[bool, str | None]:
        """Check if command is allowed based on permission level.

        Args:
            command: The command string to check

        Returns:
            Tuple of (is_allowed, error_message_or_none)
        """
        from nexus3.core.permissions import PermissionLevel
        import re

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
                return False, f"Command '{subcommand}' not allowed in sandboxed mode. Allowed: {sorted(read_only)}"
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

    Creates a standard factory function that extracts 'allowed_paths' and
    'permission_level' from the ServiceContainer.

    Args:
        cls: A FilteredCommandSkill subclass to create a factory for.

    Returns:
        A factory function that creates instances of the skill.
    """
    def factory(services: "ServiceContainer") -> _FC:
        from nexus3.core.permissions import PermissionLevel
        allowed_paths: list[Path] | None = services.get("allowed_paths")
        permission_level: PermissionLevel | None = services.get("permission_level")
        return cls(allowed_paths=allowed_paths, permission_level=permission_level)

    cls.factory = factory  # type: ignore[attr-defined]
    return factory
