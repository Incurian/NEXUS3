"""Lobby mode UI for session selection on REPL startup.

This module provides the interactive session selection screen shown when
starting NEXUS3 without flags. Users can:
- Resume their last session
- Start a fresh temp session
- Choose from saved sessions

Example:
    $ nexus

    NEXUS3 REPL

      1) Resume: my-project (2h ago, 45 messages)
      2) Fresh session
      3) Choose from saved...

    [1/2/3]:
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from pathlib import Path

from rich.console import Console

from nexus3.session.session_manager import SessionManager


class LobbyChoice(Enum):
    """User's choice from the lobby menu."""

    RESUME = auto()  # Resume last session
    FRESH = auto()  # Create fresh temp session
    SELECT = auto()  # User selected from saved list
    QUIT = auto()  # User wants to exit


@dataclass
class LobbyResult:
    """Result from lobby interaction.

    Attributes:
        choice: What the user chose to do.
        session_name: Session name for RESUME or SELECT choices.
        template_path: Custom prompt template path for FRESH with template.
    """

    choice: LobbyChoice
    session_name: str | None = None
    template_path: Path | None = None


def format_time_ago(dt: datetime) -> str:
    """Format datetime as relative time string.

    Args:
        dt: Datetime to format.

    Returns:
        Human-readable relative time like '2h ago', '3d ago', 'just now'.

    Examples:
        >>> format_time_ago(datetime.now())
        'just now'
        >>> format_time_ago(datetime.now() - timedelta(hours=2))
        '2h ago'
    """
    now = datetime.now()
    diff = now - dt

    seconds = int(diff.total_seconds())
    if seconds < 0:
        return "just now"

    if seconds < 60:
        return "just now"

    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"

    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"

    days = hours // 24
    if days < 30:
        return f"{days}d ago"

    months = days // 30
    if months < 12:
        return f"{months}mo ago"

    years = days // 365
    return f"{years}y ago"


async def show_lobby(
    session_manager: SessionManager,
    console: Console,
) -> LobbyResult:
    """Display lobby and get user choice.

    Shows an interactive menu:
    - 1) Resume: <last-session> (if exists)
    - 2) Fresh session
    - 3) Choose from saved... (if any saved)

    Args:
        session_manager: SessionManager instance for checking sessions.
        console: Rich Console for output.

    Returns:
        LobbyResult with user's choice and any associated data.
    """
    # Gather session info
    last_session_info = session_manager.load_last_session()
    saved_sessions = session_manager.list_sessions()

    has_last_session = last_session_info is not None
    has_saved_sessions = len(saved_sessions) > 0

    # Build menu options
    options: list[tuple[str, LobbyChoice, str | None]] = []

    if has_last_session:
        session, name = last_session_info  # type: ignore[misc]
        time_ago = format_time_ago(session.modified_at)
        msg_count = len(session.messages)
        display_name = name if not name.startswith(".") else f"temp ({name})"
        options.append(
            (
                f"Resume: [cyan]{display_name}[/] [dim]({time_ago}, {msg_count} messages)[/]",
                LobbyChoice.RESUME,
                name,
            )
        )

    options.append(("Fresh session", LobbyChoice.FRESH, None))

    if has_saved_sessions:
        options.append(("Choose from saved...", LobbyChoice.SELECT, None))

    # Display header
    console.print()
    console.print("[bold]NEXUS3 REPL[/]")
    console.print()

    # Display options
    for i, (label, _, _) in enumerate(options, 1):
        console.print(f"  {i}) {label}")

    console.print()

    # Build valid choices string
    valid_choices = "/".join(str(i) for i in range(1, len(options) + 1))
    if len(options) == 1:
        prompt_text = "[1/q]: "
    else:
        prompt_text = f"[{valid_choices}/q]: "

    # Get user input
    while True:
        try:
            choice_str = console.input(prompt_text).strip().lower()
        except (EOFError, KeyboardInterrupt):
            return LobbyResult(choice=LobbyChoice.QUIT)

        if choice_str in ("q", "quit", "exit"):
            return LobbyResult(choice=LobbyChoice.QUIT)

        # Try to parse as number
        try:
            choice_num = int(choice_str)
            if 1 <= choice_num <= len(options):
                _, choice_enum, session_name = options[choice_num - 1]

                # Handle "Choose from saved" option
                if choice_enum == LobbyChoice.SELECT:
                    selected = await show_session_list(session_manager, console)
                    if selected is None:
                        # User cancelled - loop back to prompt (no recursion)
                        continue
                    return LobbyResult(choice=LobbyChoice.SELECT, session_name=selected)

                return LobbyResult(choice=choice_enum, session_name=session_name)
        except ValueError:
            pass

        # Invalid input
        console.print(f"[dim]Please enter {valid_choices} or q[/]")


async def show_session_list(
    session_manager: SessionManager,
    console: Console,
) -> str | None:
    """Display saved sessions and let user pick one.

    Shows a numbered list of saved sessions with details.

    Args:
        session_manager: SessionManager instance.
        console: Rich Console for output.

    Returns:
        Selected session name or None if user cancelled.
    """
    sessions = session_manager.list_sessions()

    if not sessions:
        console.print("[dim]No saved sessions found.[/]")
        return None

    console.print()
    console.print("[bold]Saved Sessions[/]")
    console.print()

    # Display sessions
    for i, summary in enumerate(sessions, 1):
        time_ago = format_time_ago(summary.modified_at)
        console.print(
            f"  {i}) [cyan]{summary.name}[/] [dim]({time_ago}, {summary.message_count} messages)[/]"
        )

    console.print()

    # Build valid choices
    valid_range = f"1-{len(sessions)}" if len(sessions) > 1 else "1"

    while True:
        try:
            choice_str = console.input(f"[{valid_range}/b]ack: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return None

        if choice_str in ("b", "back", "q", "quit"):
            return None

        try:
            choice_num = int(choice_str)
            if 1 <= choice_num <= len(sessions):
                return sessions[choice_num - 1].name
        except ValueError:
            pass

        console.print(f"[dim]Please enter {valid_range} or b to go back[/]")
