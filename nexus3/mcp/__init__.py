"""MCP (Model Context Protocol) client implementation for NEXUS3.

This module provides client-side MCP support, allowing NEXUS3 agents to
connect to external MCP servers and use their tools.

Usage:
    from nexus3.mcp import MCPClient, StdioTransport

    transport = StdioTransport(["python", "-m", "some_mcp_server"])
    async with MCPClient(transport) as client:
        tools = await client.list_tools()
        result = await client.call_tool("echo", {"message": "hello"})
"""

from nexus3.mcp.client import MCPClient, MCPError
from nexus3.mcp.protocol import MCPServerInfo, MCPTool, MCPToolResult
from nexus3.mcp.registry import ConnectedServer, MCPServerConfig, MCPServerRegistry
from nexus3.mcp.skill_adapter import MCPSkillAdapter
from nexus3.mcp.transport import HTTPTransport, MCPTransport, StdioTransport

__all__ = [
    "ConnectedServer",
    "HTTPTransport",
    "MCPClient",
    "MCPError",
    "MCPServerConfig",
    "MCPServerInfo",
    "MCPServerRegistry",
    "MCPSkillAdapter",
    "MCPTool",
    "MCPToolResult",
    "MCPTransport",
    "StdioTransport",
]
