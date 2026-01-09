"""Whisper mode state management for NEXUS3 REPL.

Whisper mode enables persistent send mode for extended conversations
with another agent. While in whisper mode:
- All input is redirected to the target agent
- The prompt displays the target agent name
- Use /over to return to the original agent

Example:
    /whisper worker-1
    worker-1> What is 2+2?
    worker-1: 4
    worker-1> /over
    (returns to original agent)
"""

from dataclasses import dataclass


@dataclass
class WhisperMode:
    """Manages whisper mode state in REPL.

    Whisper mode allows the user to temporarily redirect their input
    to a different agent for an extended conversation, then return
    to the original agent with /over.

    Attributes:
        active: Whether whisper mode is currently active.
        target_agent_id: The agent receiving messages in whisper mode.
        original_agent_id: The agent we switched away from.
    """

    active: bool = False
    target_agent_id: str | None = None
    original_agent_id: str | None = None

    def enter(self, target: str, current: str) -> None:
        """Enter whisper mode targeting another agent.

        Args:
            target: The agent ID to send messages to.
            current: The current agent ID to return to on /over.
        """
        self.active = True
        self.target_agent_id = target
        self.original_agent_id = current

    def exit(self) -> str | None:
        """Exit whisper mode, return to original agent.

        Clears the whisper state and returns the agent ID that
        we should switch back to.

        Returns:
            The original agent ID to switch back to, or None if
            whisper mode wasn't active.
        """
        if not self.active:
            return None

        self.active = False
        original = self.original_agent_id
        self.target_agent_id = None
        self.original_agent_id = None
        return original

    def is_active(self) -> bool:
        """Check if whisper mode is currently active.

        Returns:
            True if in whisper mode, False otherwise.
        """
        return self.active

    def get_target(self) -> str | None:
        """Get the current whisper target agent ID.

        Returns:
            The target agent ID if in whisper mode, None otherwise.
        """
        if self.active:
            return self.target_agent_id
        return None

    def get_prompt_prefix(self) -> str:
        """Get the prompt prefix for whisper mode display.

        Returns a string like "agent-1> " when in whisper mode,
        or empty string when not.

        Returns:
            Prompt prefix string for the target agent, or empty string.
        """
        if self.active and self.target_agent_id:
            return f"{self.target_agent_id}> "
        return ""

    def __repr__(self) -> str:
        """String representation for debugging."""
        if self.active:
            return (
                f"WhisperMode(active=True, target={self.target_agent_id!r}, "
                f"original={self.original_agent_id!r})"
            )
        return "WhisperMode(active=False)"
