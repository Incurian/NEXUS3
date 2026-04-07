#!/usr/bin/env python3
"""Inspect the 202 capability example through Nexus's Python MCP client."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

EXAMPLE_DIR = Path(__file__).resolve().parent
REPO_ROOT = EXAMPLE_DIR.parents[3]
CONFIG_PATH = EXAMPLE_DIR / ".nexus3" / "mcp.json"


def _load_capability_config() -> Any:
    repo_root = str(REPO_ROOT)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    from nexus3.config.schema import MCPServerConfig

    config_data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    server_data = config_data["servers"]["capability_demo"]
    return MCPServerConfig(name="capability_demo", **server_data)


async def _main() -> None:
    config = _load_capability_config()

    repo_root = str(REPO_ROOT)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    from nexus3.mcp.client import MCPClient
    from nexus3.mcp.transport import StdioTransport

    cwd = str(EXAMPLE_DIR / config.cwd) if config.cwd else str(EXAMPLE_DIR)
    transport = StdioTransport(
        command=config.get_command_list(),
        env=config.env,
        env_passthrough=config.env_passthrough,
        cwd=cwd,
    )

    async with MCPClient(transport) as client:
        tools = await client.list_tools()
        resources = await client.list_resources()
        prompts = await client.list_prompts()
        count = await client.call_tool("get_customer_count", {})
        settings = await client.read_resource("config://app/settings")
        schema = await client.read_resource("docs://customer-table")
        prompt = await client.get_prompt(
            "customer_summary",
            {"customer_name": "Acme", "status": "green"},
        )

    settings_text = settings[0].text
    schema_text = schema[0].text
    if settings_text is None or schema_text is None:
        raise ValueError("Expected text resources from the capability example")

    settings_data = json.loads(settings_text)
    schema_heading = schema_text.splitlines()[0]

    print(f"Tools: {', '.join(tool.name for tool in tools)}")
    print(f"Resources: {', '.join(resource.uri for resource in resources)}")
    print(f"Prompts: {', '.join(item.name for item in prompts)}")
    print(f"Tool call: {count.to_text()}")
    print(f"Settings mode: {settings_data['mode']}")
    print(f"Settings environment: {settings_data['environment']}")
    print(f"Schema heading: {schema_heading}")
    print(f"Prompt preview: {prompt.messages[0].get_text()}")


if __name__ == "__main__":
    asyncio.run(_main())
