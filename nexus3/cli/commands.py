"""Slash command handling for NEXUS3 CLI.

All user input starting with "/" is treated as a command.
Unknown commands show an error rather than being sent to the model.
"""

from dataclasses import dataclass
from enum import Enum, auto


class CommandResult(Enum):
    """Result of processing a command."""

    QUIT = auto()  # Exit the REPL
    HANDLED = auto()  # Command was handled, continue
    UNKNOWN = auto()  # Unknown command


@dataclass
class Command:
    """A parsed command."""

    name: str
    args: str


def parse_command(user_input: str) -> Command | None:
    """Parse user input as a command.

    Args:
        user_input: Raw user input

    Returns:
        Command if input starts with "/", None otherwise
    """
    stripped = user_input.strip()
    if not stripped.startswith("/"):
        return None

    # Split into command and args
    parts = stripped[1:].split(maxsplit=1)
    name = parts[0].lower() if parts else ""
    args = parts[1] if len(parts) > 1 else ""

    return Command(name=name, args=args)


def handle_command(command: Command) -> CommandResult:
    """Handle a parsed command.

    Args:
        command: The command to handle

    Returns:
        CommandResult indicating what happened
    """
    # Quit commands
    if command.name in ("quit", "exit", "q"):
        return CommandResult.QUIT

    # Add more commands here as needed:
    # if command.name == "help":
    #     return CommandResult.HANDLED
    # if command.name == "clear":
    #     return CommandResult.HANDLED

    return CommandResult.UNKNOWN
