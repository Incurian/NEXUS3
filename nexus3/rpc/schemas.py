"""Typed schema inventory for RPC and MCP boundary payloads.

This module is intentionally behavior-preserving scaffold for Plan H Phase 1.
Schemas are not wired into dispatch paths yet.
"""

from __future__ import annotations

from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from nexus3.core.validation import ValidationError, validate_agent_id

# JSON-RPC IDs can be strings or integers, but bool must be rejected explicitly.
JsonRpcId: TypeAlias = str | int


class StrictSchemaModel(BaseModel):
    """Base model enforcing strict/explicit boundary contracts."""

    model_config = ConfigDict(extra="forbid")


class RpcRequestEnvelopeSchema(StrictSchemaModel):
    """Strict JSON-RPC request envelope schema."""

    jsonrpc: Literal["2.0"]
    method: str = Field(min_length=1)
    params: dict[str, Any] | None = None
    id: JsonRpcId | None = None

    @field_validator("id", mode="before")
    @classmethod
    def reject_boolean_request_id(cls, value: JsonRpcId | None) -> JsonRpcId | None:
        if isinstance(value, bool):
            raise ValueError("id must be string, integer, or null")
        return value


class RpcErrorObjectSchema(StrictSchemaModel):
    """Strict JSON-RPC error object schema."""

    code: int
    message: str = Field(min_length=1)
    data: Any | None = None


class RpcResponseEnvelopeSchema(StrictSchemaModel):
    """Strict JSON-RPC response envelope schema."""

    # Keep response ingress compat-safe: unknown top-level fields are ignored.
    model_config = ConfigDict(extra="ignore")

    jsonrpc: Literal["2.0"]
    id: JsonRpcId | None
    result: Any | None = None
    error: dict[str, Any] | None = None

    @model_validator(mode="before")
    @classmethod
    def validate_result_error_presence(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        has_result = "result" in data
        has_error = "error" in data
        if has_result and has_error:
            raise ValueError("response cannot have both 'result' and 'error'")
        if not has_result and not has_error:
            raise ValueError("response must have either 'result' or 'error'")
        return data

    @field_validator("id", mode="before")
    @classmethod
    def reject_boolean_response_id(cls, value: JsonRpcId | None) -> JsonRpcId | None:
        if isinstance(value, bool):
            raise ValueError("id must be string, integer, or null")
        return value

    @field_validator("error", mode="before")
    @classmethod
    def validate_error_shape(cls, value: Any) -> dict[str, Any] | None:
        if value is None:
            return value
        if not isinstance(value, dict):
            raise ValueError("error must be an object")
        if "code" not in value or "message" not in value:
            raise ValueError("error must have 'code' and 'message' fields")
        return value


class EmptyParamsSchema(StrictSchemaModel):
    """Schema for RPC methods that do not accept parameters."""


class SendParamsSchema(StrictSchemaModel):
    """Params schema for dispatcher.send."""

    content: str
    request_id: JsonRpcId | None = None
    source: str | None = None
    source_agent_id: str | int | None = None

    @field_validator("request_id", mode="before")
    @classmethod
    def reject_boolean_or_empty_request_id(cls, value: JsonRpcId | None) -> JsonRpcId | None:
        if value is None:
            return value
        if isinstance(value, bool):
            raise ValueError("request_id must be string or integer")
        if isinstance(value, str) and value == "":
            raise ValueError("request_id cannot be empty")
        return value

    @field_validator("source_agent_id", mode="before")
    @classmethod
    def reject_boolean_source_agent_id(cls, value: str | int | None) -> str | int | None:
        if isinstance(value, bool):
            raise ValueError("source_agent_id must be string or integer")
        return value


class CancelParamsSchema(StrictSchemaModel):
    """Params schema for dispatcher.cancel."""

    request_id: JsonRpcId

    @field_validator("request_id", mode="before")
    @classmethod
    def reject_boolean_or_empty_request_id(cls, value: JsonRpcId) -> JsonRpcId:
        if isinstance(value, bool):
            raise ValueError("request_id must be string or integer")
        if isinstance(value, str) and value == "":
            raise ValueError("request_id cannot be empty")
        return value


class CompactParamsSchema(StrictSchemaModel):
    """Params schema for dispatcher.compact."""

    force: bool = True


class GetMessagesParamsSchema(StrictSchemaModel):
    """Params schema for dispatcher.get_messages."""

    offset: int = 0
    limit: int = 200

    @field_validator("offset")
    @classmethod
    def validate_offset(cls, value: int) -> int:
        if value < 0:
            raise ValueError("offset must be a non-negative integer")
        return value

    @field_validator("limit")
    @classmethod
    def validate_limit(cls, value: int) -> int:
        if value < 1 or value > 2000:
            raise ValueError("limit must be an integer between 1 and 2000")
        return value


class CreateAgentParamsSchema(StrictSchemaModel):
    """Params schema for global_dispatcher.create_agent."""

    agent_id: str | None = None
    system_prompt: str | None = None
    preset: Literal["trusted", "sandboxed"] | None = None
    disable_tools: list[str] | None = None
    parent_agent_id: str | None = None
    cwd: str | None = None
    allowed_write_paths: list[str] | None = None
    model: str | None = None
    initial_message: str | None = None
    wait_for_initial_response: bool = False

    @field_validator("agent_id", "parent_agent_id")
    @classmethod
    def validate_agent_identifier_fields(
        cls,
        value: str | None,
        info: ValidationInfo,
    ) -> str | None:
        if value is None:
            return value
        try:
            return validate_agent_id(value)
        except ValidationError as exc:
            raise ValueError(f"{info.field_name} invalid: {exc.message}") from exc

    @field_validator("initial_message")
    @classmethod
    def validate_initial_message(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not value.strip():
            raise ValueError("initial_message cannot be empty")
        return value


class DestroyAgentParamsSchema(StrictSchemaModel):
    """Params schema for global_dispatcher.destroy_agent."""

    agent_id: str

    @field_validator("agent_id")
    @classmethod
    def validate_agent_identifier(cls, value: str) -> str:
        try:
            return validate_agent_id(value)
        except ValidationError as exc:
            raise ValueError(exc.message) from exc


RPC_AGENT_METHOD_PARAM_SCHEMAS: dict[str, type[StrictSchemaModel]] = {
    "send": SendParamsSchema,
    "shutdown": EmptyParamsSchema,
    "cancel": CancelParamsSchema,
    "compact": CompactParamsSchema,
    "get_tokens": EmptyParamsSchema,
    "get_context": EmptyParamsSchema,
    "get_messages": GetMessagesParamsSchema,
}

RPC_GLOBAL_METHOD_PARAM_SCHEMAS: dict[str, type[StrictSchemaModel]] = {
    "create_agent": CreateAgentParamsSchema,
    "destroy_agent": DestroyAgentParamsSchema,
    "list_agents": EmptyParamsSchema,
    "shutdown_server": EmptyParamsSchema,
}

RPC_ALL_METHOD_PARAM_SCHEMAS: dict[str, type[StrictSchemaModel]] = {
    **RPC_AGENT_METHOD_PARAM_SCHEMAS,
    **RPC_GLOBAL_METHOD_PARAM_SCHEMAS,
}


class MCPServerEntrySchema(StrictSchemaModel):
    """Strict MCP server entry schema used in mcp.json envelopes."""

    name: str = Field(min_length=1)
    command: str | list[str] | None = None
    args: list[str] | None = None
    url: str | None = None
    env: dict[str, str] | None = None
    env_passthrough: list[str] | None = None
    cwd: str | None = None
    enabled: bool = True

    @field_validator("command")
    @classmethod
    def validate_command(cls, value: str | list[str] | None) -> str | list[str] | None:
        if isinstance(value, list):
            if not value:
                raise ValueError("command list cannot be empty")
            for i, item in enumerate(value):
                if not isinstance(item, str) or not item:
                    raise ValueError(f"command[{i}] must be a non-empty string")
        elif isinstance(value, str) and not value:
            raise ValueError("command cannot be empty")
        return value

    @model_validator(mode="after")
    def validate_transport(self) -> MCPServerEntrySchema:
        has_command = self.command is not None
        has_url = self.url is not None
        if has_command == has_url:
            raise ValueError("must specify exactly one of 'command' or 'url'")
        return self


class MCPServerEntryNoNameSchema(StrictSchemaModel):
    """Official mcpServers entry schema where name comes from map key."""

    command: str | list[str] | None = None
    args: list[str] | None = None
    url: str | None = None
    env: dict[str, str] | None = None
    env_passthrough: list[str] | None = None
    cwd: str | None = None
    enabled: bool = True

    @field_validator("command")
    @classmethod
    def validate_command(cls, value: str | list[str] | None) -> str | list[str] | None:
        if isinstance(value, list):
            if not value:
                raise ValueError("command list cannot be empty")
            for i, item in enumerate(value):
                if not isinstance(item, str) or not item:
                    raise ValueError(f"command[{i}] must be a non-empty string")
        elif isinstance(value, str) and not value:
            raise ValueError("command cannot be empty")
        return value

    @model_validator(mode="after")
    def validate_transport(self) -> MCPServerEntryNoNameSchema:
        has_command = self.command is not None
        has_url = self.url is not None
        if has_command == has_url:
            raise ValueError("must specify exactly one of 'command' or 'url'")
        return self


class MCPConfigEnvelopeSchema(StrictSchemaModel):
    """Strict mcp.json envelope schema supporting official and NEXUS3 formats."""

    mcpServers: dict[str, MCPServerEntryNoNameSchema] | None = None
    servers: list[MCPServerEntrySchema] | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> MCPConfigEnvelopeSchema:
        if self.mcpServers is None and self.servers is None:
            raise ValueError("mcp.json must define 'mcpServers' or 'servers'")
        if self.mcpServers is not None and self.servers is not None:
            raise ValueError("mcp.json cannot define both 'mcpServers' and 'servers'")
        return self


__all__ = [
    "CancelParamsSchema",
    "CompactParamsSchema",
    "CreateAgentParamsSchema",
    "DestroyAgentParamsSchema",
    "EmptyParamsSchema",
    "GetMessagesParamsSchema",
    "JsonRpcId",
    "MCPConfigEnvelopeSchema",
    "MCPServerEntryNoNameSchema",
    "MCPServerEntrySchema",
    "RPC_AGENT_METHOD_PARAM_SCHEMAS",
    "RPC_ALL_METHOD_PARAM_SCHEMAS",
    "RPC_GLOBAL_METHOD_PARAM_SCHEMAS",
    "RpcErrorObjectSchema",
    "RpcRequestEnvelopeSchema",
    "RpcResponseEnvelopeSchema",
    "SendParamsSchema",
    "StrictSchemaModel",
]
