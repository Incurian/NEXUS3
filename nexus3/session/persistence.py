"""Session persistence: serialization and deserialization of sessions.

This module handles converting runtime session state to/from JSON-serializable
format for disk storage. Handles Message/ToolCall objects with their nested
structure.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from nexus3.core.types import Message, Role, ToolCall

# Schema version for future migrations
SESSION_SCHEMA_VERSION = 1


@dataclass
class SavedSession:
    """Serialized session state for disk storage.

    Attributes:
        agent_id: Unique identifier for the agent.
        created_at: When the session was first created.
        modified_at: When the session was last modified.
        messages: Serialized Message objects.
        system_prompt: Current system prompt content.
        system_prompt_path: Path to system prompt file (if loaded from file).
        working_directory: Agent's working directory.
        permission_level: "yolo" | "trusted" | "sandboxed".
        token_usage: Token usage breakdown.
        provenance: "user" or parent agent_id that spawned this agent.
        permission_preset: Permission preset name (e.g., "yolo", "trusted", "sandboxed").
        disabled_tools: List of tool names that are disabled for this agent.
        schema_version: Schema version for migrations.
    """

    agent_id: str
    created_at: datetime
    modified_at: datetime
    messages: list[dict[str, Any]]
    system_prompt: str
    system_prompt_path: str | None
    working_directory: str
    permission_level: str
    token_usage: dict[str, int]
    provenance: str
    # New fields with defaults for backwards compatibility
    permission_preset: str | None = None
    disabled_tools: list[str] = field(default_factory=list)
    schema_version: int = SESSION_SCHEMA_VERSION

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "schema_version": self.schema_version,
            "agent_id": self.agent_id,
            "created_at": self.created_at.isoformat(),
            "modified_at": self.modified_at.isoformat(),
            "messages": self.messages,
            "system_prompt": self.system_prompt,
            "system_prompt_path": self.system_prompt_path,
            "working_directory": self.working_directory,
            "permission_level": self.permission_level,
            "permission_preset": self.permission_preset,
            "disabled_tools": self.disabled_tools,
            "token_usage": self.token_usage,
            "provenance": self.provenance,
        }

    @classmethod
    def from_json(cls, json_str: str) -> "SavedSession":
        """Deserialize from JSON string."""
        data = json.loads(json_str)
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SavedSession":
        """Create from dictionary."""
        return cls(
            agent_id=data["agent_id"],
            created_at=datetime.fromisoformat(data["created_at"]),
            modified_at=datetime.fromisoformat(data["modified_at"]),
            messages=data["messages"],
            system_prompt=data["system_prompt"],
            system_prompt_path=data.get("system_prompt_path"),
            working_directory=data["working_directory"],
            permission_level=data["permission_level"],
            permission_preset=data.get("permission_preset"),
            disabled_tools=data.get("disabled_tools", []),
            token_usage=data.get("token_usage", {}),
            provenance=data.get("provenance", "user"),
            schema_version=data.get("schema_version", 1),
        )


@dataclass
class SessionSummary:
    """Brief summary of a saved session for listing.

    Attributes:
        name: Session name (filename without extension).
        modified_at: When the session was last modified.
        message_count: Number of messages in the session.
        agent_id: The agent ID stored in the session.
    """

    name: str
    modified_at: datetime
    message_count: int
    agent_id: str


def serialize_tool_call(tc: ToolCall) -> dict[str, Any]:
    """Serialize a ToolCall to a dictionary.

    Args:
        tc: ToolCall to serialize.

    Returns:
        Dictionary representation suitable for JSON.
    """
    return {
        "id": tc.id,
        "name": tc.name,
        "arguments": tc.arguments,
    }


def deserialize_tool_call(data: dict[str, Any]) -> ToolCall:
    """Deserialize a ToolCall from a dictionary.

    Args:
        data: Dictionary representation of a ToolCall.

    Returns:
        ToolCall object.
    """
    return ToolCall(
        id=data["id"],
        name=data["name"],
        arguments=data.get("arguments", {}),
    )


def serialize_message(msg: Message) -> dict[str, Any]:
    """Serialize a Message to a dictionary.

    Args:
        msg: Message to serialize.

    Returns:
        Dictionary representation suitable for JSON.
    """
    data: dict[str, Any] = {
        "role": msg.role.value,
        "content": msg.content,
    }

    if msg.tool_calls:
        data["tool_calls"] = [serialize_tool_call(tc) for tc in msg.tool_calls]

    if msg.tool_call_id is not None:
        data["tool_call_id"] = msg.tool_call_id

    return data


def deserialize_message(data: dict[str, Any]) -> Message:
    """Deserialize a Message from a dictionary.

    Args:
        data: Dictionary representation of a Message.

    Returns:
        Message object.
    """
    role = Role(data["role"])
    content = data.get("content", "")

    tool_calls: tuple[ToolCall, ...] = ()
    if "tool_calls" in data and data["tool_calls"]:
        tool_calls = tuple(deserialize_tool_call(tc) for tc in data["tool_calls"])

    tool_call_id = data.get("tool_call_id")

    return Message(
        role=role,
        content=content,
        tool_calls=tool_calls,
        tool_call_id=tool_call_id,
    )


def serialize_messages(messages: list[Message]) -> list[dict[str, Any]]:
    """Serialize a list of Messages.

    Args:
        messages: List of Message objects.

    Returns:
        List of dictionary representations.
    """
    return [serialize_message(msg) for msg in messages]


def deserialize_messages(data: list[dict[str, Any]]) -> list[Message]:
    """Deserialize a list of Messages.

    Args:
        data: List of dictionary representations.

    Returns:
        List of Message objects.
    """
    return [deserialize_message(msg_data) for msg_data in data]


def serialize_session(
    agent_id: str,
    messages: list[Message],
    system_prompt: str,
    system_prompt_path: str | None,
    working_directory: str | Path,
    permission_level: str,
    token_usage: dict[str, int],
    provenance: str = "user",
    created_at: datetime | None = None,
    permission_preset: str | None = None,
    disabled_tools: list[str] | None = None,
) -> SavedSession:
    """Create a SavedSession from runtime state.

    Args:
        agent_id: Unique identifier for the agent.
        messages: Current conversation messages.
        system_prompt: System prompt content.
        system_prompt_path: Path to system prompt file (if any).
        working_directory: Agent's working directory.
        permission_level: "yolo" | "trusted" | "sandboxed".
        token_usage: Token usage breakdown.
        provenance: "user" or parent agent_id.
        created_at: When the session was created (default: now).
        permission_preset: Permission preset name (e.g., "yolo", "trusted", "sandboxed").
        disabled_tools: List of tool names that are disabled for this agent.

    Returns:
        SavedSession ready for disk storage.
    """
    now = datetime.now()
    return SavedSession(
        agent_id=agent_id,
        created_at=created_at or now,
        modified_at=now,
        messages=serialize_messages(messages),
        system_prompt=system_prompt,
        system_prompt_path=system_prompt_path,
        working_directory=str(working_directory),
        permission_level=permission_level,
        token_usage=token_usage,
        provenance=provenance,
        permission_preset=permission_preset,
        disabled_tools=disabled_tools or [],
    )
