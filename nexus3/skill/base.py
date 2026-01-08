"""Base skill interface for NEXUS3.

This module defines the Skill protocol that all skills must implement,
and a BaseSkill convenience class for common implementation patterns.

Skills are the tool system in NEXUS3 - they provide capabilities like
file reading, command execution, and other actions the agent can perform.
"""

from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable

from nexus3.core.types import ToolResult


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
