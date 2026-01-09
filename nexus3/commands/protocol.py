"""Types for the unified command system.

This module defines the protocols and types used by unified commands that
work for both CLI and REPL contexts.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nexus3.rpc.pool import AgentPool
    from nexus3.session.session_manager import SessionManager


class CommandResult(Enum):
    """Result status of a command execution.

    Attributes:
        SUCCESS: Command completed successfully.
        ERROR: Command failed with an error.
        QUIT: User requested to quit the REPL.
        SWITCH_AGENT: Command requests switching to a different agent.
        ENTER_WHISPER: Command requests entering whisper mode.
    """

    SUCCESS = auto()
    ERROR = auto()
    QUIT = auto()
    SWITCH_AGENT = auto()
    ENTER_WHISPER = auto()


@dataclass
class CommandOutput:
    """Output from a command execution.

    Commands return structured output rather than printing directly.
    The caller (CLI or REPL) decides how to format and display the output.

    Attributes:
        result: The result status of the command.
        message: Human-readable message (for display).
        data: Structured data (for JSON output or further processing).
        new_agent_id: For SWITCH_AGENT, the agent to switch to.
        whisper_target: For ENTER_WHISPER, the agent to whisper to.
    """

    result: CommandResult
    message: str | None = None
    data: dict[str, Any] | None = None
    new_agent_id: str | None = None
    whisper_target: str | None = None

    @classmethod
    def success(
        cls,
        message: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> CommandOutput:
        """Create a successful output.

        Args:
            message: Optional human-readable message.
            data: Optional structured data.

        Returns:
            CommandOutput with SUCCESS result.
        """
        return cls(result=CommandResult.SUCCESS, message=message, data=data)

    @classmethod
    def error(cls, message: str) -> CommandOutput:
        """Create an error output.

        Args:
            message: Error message describing what went wrong.

        Returns:
            CommandOutput with ERROR result.
        """
        return cls(result=CommandResult.ERROR, message=message)

    @classmethod
    def quit(cls) -> CommandOutput:
        """Create a quit output.

        Returns:
            CommandOutput with QUIT result.
        """
        return cls(result=CommandResult.QUIT)

    @classmethod
    def switch_agent(cls, agent_id: str) -> CommandOutput:
        """Create a switch agent output.

        Args:
            agent_id: The agent to switch to.

        Returns:
            CommandOutput with SWITCH_AGENT result.
        """
        return cls(result=CommandResult.SWITCH_AGENT, new_agent_id=agent_id)

    @classmethod
    def enter_whisper(cls, target: str) -> CommandOutput:
        """Create an enter whisper output.

        Args:
            target: The agent to whisper to.

        Returns:
            CommandOutput with ENTER_WHISPER result.
        """
        return cls(result=CommandResult.ENTER_WHISPER, whisper_target=target)


@dataclass
class CommandContext:
    """Context for command execution.

    Provides access to shared resources needed by commands.
    Different contexts may be created for CLI vs REPL use cases.

    Attributes:
        pool: The agent pool for managing agents.
        session_manager: Manager for session persistence.
        current_agent_id: ID of the currently active agent (if any).
        is_repl: True if running in REPL mode (affects prompts/display).
    """

    pool: AgentPool
    session_manager: SessionManager
    current_agent_id: str | None = None
    is_repl: bool = False
