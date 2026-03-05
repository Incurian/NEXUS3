"""Unit tests for RPC/MCP schema inventory models (Plan H, Phase 1 scaffold)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from nexus3.rpc.schemas import (
    RPC_AGENT_METHOD_PARAM_SCHEMAS,
    RPC_ALL_METHOD_PARAM_SCHEMAS,
    RPC_GLOBAL_METHOD_PARAM_SCHEMAS,
    CancelParamsSchema,
    CreateAgentParamsSchema,
    GetMessagesParamsSchema,
    MCPConfigEnvelopeSchema,
    RpcRequestEnvelopeSchema,
    RpcResponseEnvelopeSchema,
    SendParamsSchema,
)


def test_rpc_method_inventory_covers_current_dispatchers() -> None:
    """Schema map should cover all methods currently exposed by dispatchers."""
    assert set(RPC_AGENT_METHOD_PARAM_SCHEMAS) == {
        "send",
        "shutdown",
        "cancel",
        "compact",
        "get_tokens",
        "get_context",
        "get_messages",
    }
    assert set(RPC_GLOBAL_METHOD_PARAM_SCHEMAS) == {
        "create_agent",
        "destroy_agent",
        "list_agents",
        "shutdown_server",
    }
    assert set(RPC_ALL_METHOD_PARAM_SCHEMAS) == {
        *RPC_AGENT_METHOD_PARAM_SCHEMAS,
        *RPC_GLOBAL_METHOD_PARAM_SCHEMAS,
    }


def test_rpc_request_envelope_rejects_bool_id() -> None:
    with pytest.raises(ValidationError, match="id"):
        RpcRequestEnvelopeSchema.model_validate(
            {
                "jsonrpc": "2.0",
                "method": "send",
                "params": {"content": "hi"},
                "id": True,
            }
        )


def test_rpc_response_envelope_uses_result_error_key_presence() -> None:
    RpcResponseEnvelopeSchema.model_validate(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": None,
        }
    )
    with pytest.raises(ValidationError, match="response cannot have both"):
        RpcResponseEnvelopeSchema.model_validate(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {},
                "error": {"code": -32000, "message": "boom"},
            }
        )


def test_send_params_reject_bool_request_id() -> None:
    with pytest.raises(ValidationError, match="request_id"):
        SendParamsSchema.model_validate({"content": "hello", "request_id": False})


def test_cancel_params_reject_empty_request_id() -> None:
    with pytest.raises(ValidationError, match="request_id"):
        CancelParamsSchema.model_validate({"request_id": ""})


def test_get_messages_enforces_bounds() -> None:
    with pytest.raises(ValidationError, match="offset"):
        GetMessagesParamsSchema.model_validate({"offset": -1, "limit": 10})
    with pytest.raises(ValidationError, match="limit"):
        GetMessagesParamsSchema.model_validate({"offset": 0, "limit": 2001})


def test_create_agent_rejects_invalid_agent_id_and_shape() -> None:
    with pytest.raises(ValidationError, match="agent_id"):
        CreateAgentParamsSchema.model_validate({"agent_id": "../../escape"})
    with pytest.raises(ValidationError, match="disable_tools"):
        CreateAgentParamsSchema.model_validate({"disable_tools": "write_file"})


def test_create_agent_rejects_blank_initial_message() -> None:
    with pytest.raises(ValidationError, match="initial_message"):
        CreateAgentParamsSchema.model_validate({"initial_message": "   "})


def test_mcp_envelope_accepts_official_mcp_servers_shape() -> None:
    model = MCPConfigEnvelopeSchema.model_validate(
        {
            "mcpServers": {
                "test": {
                    "command": "npx",
                    "args": ["-y", "example-server"],
                }
            }
        }
    )
    assert model.mcpServers is not None
    assert "test" in model.mcpServers


def test_mcp_envelope_accepts_nexus_servers_shape() -> None:
    model = MCPConfigEnvelopeSchema.model_validate(
        {
            "servers": [
                {
                    "name": "test",
                    "command": ["python", "-m", "example_server"],
                }
            ]
        }
    )
    assert model.servers is not None
    assert model.servers[0].name == "test"


@pytest.mark.parametrize(
    "payload, match",
    [
        ({}, "must define"),
        (
            {
                "mcpServers": {"a": {"command": "cmd"}},
                "servers": [{"name": "b", "command": ["cmd"]}],
            },
            "cannot define both",
        ),
        ({"unexpected": {}}, "Extra inputs are not permitted"),
        (
            {
                "servers": [
                    {
                        "name": "bad",
                        "command": ["cmd"],
                        "url": "http://localhost:8080",
                    }
                ]
            },
            "exactly one",
        ),
    ],
)
def test_mcp_envelope_rejects_malformed_shapes(payload: dict[str, object], match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        MCPConfigEnvelopeSchema.model_validate(payload)
