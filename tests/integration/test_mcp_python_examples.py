"""Integration smoke tests for the checked-in MCP Python example projects."""

import asyncio
import sys
from pathlib import Path

import pytest

from nexus3.config.schema import ContextConfig, MCPServerConfig
from nexus3.context.loader import ContextLoader
from nexus3.mcp.client import MCPClient
from nexus3.mcp.transport import HTTPTransport, StdioTransport

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = REPO_ROOT / "docs" / "references" / "mcp-python-examples"


def _load_example_config(tmp_path: Path, example_name: str) -> tuple[Path, MCPServerConfig]:
    """Load one example's local MCP config without user/global interference."""
    example_dir = EXAMPLES_DIR / example_name
    loader = ContextLoader(
        cwd=example_dir,
        context_config=ContextConfig(ancestor_depth=0),
    )
    empty_dir = tmp_path / "empty-config"
    loader._get_global_dir = lambda: empty_dir  # type: ignore[method-assign]
    loader._get_defaults_dir = lambda: empty_dir  # type: ignore[method-assign]

    context = loader.load(is_repl=True)
    assert len(context.mcp_servers) == 1
    return example_dir, context.mcp_servers[0].config


def _stdio_transport(example_dir: Path, config: MCPServerConfig) -> StdioTransport:
    """Build a stdio transport from an example config."""
    cwd = str(example_dir / config.cwd) if config.cwd else None
    return StdioTransport(
        command=config.get_command_list(),
        env=config.env,
        env_passthrough=config.env_passthrough,
        cwd=cwd,
    )


async def _start_http_example_server(script_path: Path) -> asyncio.subprocess.Process:
    """Start the checked-in HTTP example server."""
    return await asyncio.create_subprocess_exec(
        sys.executable,
        str(script_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


async def _wait_for_http_example_ready(
    process: asyncio.subprocess.Process,
    url: str,
) -> None:
    """Wait until the example HTTP server accepts MCP initialize requests."""
    last_error: Exception | None = None

    for _ in range(50):
        if process.returncode is not None:
            stderr = b""
            if process.stderr is not None:
                stderr = await process.stderr.read()
            raise AssertionError(
                "HTTP example server exited before becoming ready: "
                f"{stderr.decode(errors='replace').strip()}"
            )

        try:
            transport = HTTPTransport(url, timeout=0.2, max_retries=0)
            async with MCPClient(transport):
                return
        except Exception as exc:
            last_error = exc
            await asyncio.sleep(0.1)

    raise AssertionError(f"HTTP example server did not become ready: {last_error}")


async def _stop_process(process: asyncio.subprocess.Process) -> None:
    """Terminate a subprocess cleanly."""
    if process.returncode is not None:
        return

    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except TimeoutError:
        process.kill()
        await process.wait()


class TestMCPPythonExamples:
    """Smoke test the tutorial example projects against the real MCP client."""

    @pytest.mark.asyncio
    async def test_101_stdio_example(self, tmp_path: Path) -> None:
        """The beginner stdio example loads from mcp.json and responds correctly."""
        example_dir, config = _load_example_config(tmp_path, "101-stdio")

        assert config.name == "hello_stdio"
        assert config.command == "python3"
        assert config.cwd == "."

        async with MCPClient(_stdio_transport(example_dir, config)) as client:
            tools = await client.list_tools()
            result = await client.call_tool("hello", {"name": "Alice"})
            add = await client.call_tool("add", {"a": 41, "b": 1})

        assert [tool.name for tool in tools] == ["hello", "add"]
        assert result.to_text() == "Howdy, Alice! Welcome from the stdio example."
        assert add.to_text() == "42"

    @pytest.mark.asyncio
    async def test_101_http_example(self, tmp_path: Path) -> None:
        """The HTTP example server works with the real HTTP transport."""
        example_dir, config = _load_example_config(tmp_path, "101-http")
        assert config.name == "hello_http"
        assert config.url == "http://127.0.0.1:9876/mcp"

        process = await _start_http_example_server(example_dir / "hello_http_server.py")
        try:
            assert config.url is not None
            await _wait_for_http_example_ready(process, config.url)

            async with MCPClient(HTTPTransport(config.url)) as client:
                tools = await client.list_tools()
                result = await client.call_tool("hello", {"name": "Alice"})
                add = await client.call_tool("add", {"a": 20, "b": 22})

            assert [tool.name for tool in tools] == ["hello", "add"]
            assert result.to_text() == "Hello, Alice!"
            assert add.to_text() == "42"
        finally:
            await _stop_process(process)

    @pytest.mark.asyncio
    async def test_202_capabilities_example(self, tmp_path: Path) -> None:
        """The capabilities example exposes tools, resources, and prompts."""
        example_dir, config = _load_example_config(tmp_path, "202-capabilities")

        assert config.name == "capability_demo"
        assert config.command == "python3"
        assert config.cwd == "."

        async with MCPClient(_stdio_transport(example_dir, config)) as client:
            tools = await client.list_tools()
            resources = await client.list_resources()
            prompts = await client.list_prompts()
            count = await client.call_tool("get_customer_count", {})
            settings = await client.read_resource("config://app/settings")
            prompt = await client.get_prompt(
                "customer_summary",
                {"customer_name": "Acme", "status": "green"},
            )

        assert [tool.name for tool in tools] == ["add", "get_customer_count"]
        assert [resource.uri for resource in resources] == [
            "config://app/settings",
            "docs://customer-table",
        ]
        assert [mcp_prompt.name for mcp_prompt in prompts] == [
            "customer_summary",
            "schema_explainer",
        ]
        assert count.to_text() == "Current customer count: 128"
        assert settings[0].text is not None
        assert '"mode": "demo"' in settings[0].text
        assert prompt.messages[0].get_text().endswith(
            "This example is running in the development environment."
        )
