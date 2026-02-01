"""Tests for MCPServerConfig command format handling.

Tests both the Pydantic model (nexus3.config.schema) and dataclass (nexus3.mcp.registry)
implementations of MCPServerConfig for handling different config formats:
- NEXUS3 format: command as list
- Official MCP format (Claude Desktop): command as string + args array
"""

import pytest

from nexus3.config.schema import MCPServerConfig as PydanticMCPServerConfig
from nexus3.mcp.registry import MCPServerConfig as DataclassMCPServerConfig


class TestPydanticMCPServerConfig:
    """Tests for the Pydantic-based MCPServerConfig."""

    def test_nexus3_format_command_list(self) -> None:
        """NEXUS3 format: command as list."""
        config = PydanticMCPServerConfig(
            name="test",
            command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/path"],
        )
        assert config.get_command_list() == [
            "npx", "-y", "@modelcontextprotocol/server-filesystem", "/path"
        ]

    def test_official_mcp_format(self) -> None:
        """Official format: command string + args array."""
        config = PydanticMCPServerConfig(
            name="test",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", "/path"],
        )
        assert config.get_command_list() == [
            "npx", "-y", "@modelcontextprotocol/server-filesystem", "/path"
        ]

    def test_command_string_no_args(self) -> None:
        """Command string with no args."""
        config = PydanticMCPServerConfig(name="test", command="echo")
        assert config.get_command_list() == ["echo"]

    def test_command_string_empty_args(self) -> None:
        """Command string with empty args list."""
        config = PydanticMCPServerConfig(name="test", command="echo", args=[])
        assert config.get_command_list() == ["echo"]

    def test_url_config_no_command(self) -> None:
        """URL-based config has no command."""
        config = PydanticMCPServerConfig(name="test", url="http://localhost:8080")
        assert config.get_command_list() == []

    def test_command_list_ignores_args(self) -> None:
        """When command is a list, args field is ignored."""
        config = PydanticMCPServerConfig(
            name="test",
            command=["echo", "hello"],
            args=["ignored", "args"],
        )
        # List command takes precedence, args ignored
        assert config.get_command_list() == ["echo", "hello"]

    def test_validation_both_command_and_url(self) -> None:
        """Cannot specify both command and url."""
        with pytest.raises(ValueError, match="Cannot specify both"):
            PydanticMCPServerConfig(
                name="test",
                command="echo",
                url="http://localhost:8080",
            )

    def test_validation_neither_command_nor_url(self) -> None:
        """Must specify either command or url."""
        with pytest.raises(ValueError, match="Must specify either"):
            PydanticMCPServerConfig(name="test")


class TestDataclassMCPServerConfig:
    """Tests for the dataclass-based MCPServerConfig."""

    def test_nexus3_format_command_list(self) -> None:
        """NEXUS3 format: command as list."""
        config = DataclassMCPServerConfig(
            name="test",
            command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/path"],
        )
        assert config.get_command_list() == [
            "npx", "-y", "@modelcontextprotocol/server-filesystem", "/path"
        ]

    def test_official_mcp_format(self) -> None:
        """Official format: command string + args array."""
        config = DataclassMCPServerConfig(
            name="test",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", "/path"],
        )
        assert config.get_command_list() == [
            "npx", "-y", "@modelcontextprotocol/server-filesystem", "/path"
        ]

    def test_command_string_no_args(self) -> None:
        """Command string with no args."""
        config = DataclassMCPServerConfig(name="test", command="echo")
        assert config.get_command_list() == ["echo"]

    def test_command_string_empty_args(self) -> None:
        """Command string with empty args list."""
        config = DataclassMCPServerConfig(name="test", command="echo", args=[])
        assert config.get_command_list() == ["echo"]

    def test_url_config_no_command(self) -> None:
        """URL-based config has no command."""
        config = DataclassMCPServerConfig(name="test", url="http://localhost:8080")
        assert config.get_command_list() == []

    def test_command_list_ignores_args(self) -> None:
        """When command is a list, args field is ignored."""
        config = DataclassMCPServerConfig(
            name="test",
            command=["echo", "hello"],
            args=["ignored", "args"],
        )
        # List command takes precedence, args ignored
        assert config.get_command_list() == ["echo", "hello"]

    def test_defaults(self) -> None:
        """Verify default values."""
        config = DataclassMCPServerConfig(name="test", command=["echo"])
        assert config.args is None
        assert config.url is None
        assert config.env is None
        assert config.env_passthrough is None
        assert config.cwd is None
        assert config.enabled is True


class TestConfigFormatEquivalence:
    """Test that both config classes produce equivalent results."""

    def test_nexus3_format_equivalence(self) -> None:
        """Both classes handle NEXUS3 format identically."""
        pydantic = PydanticMCPServerConfig(
            name="test",
            command=["npx", "-y", "server"],
        )
        dataclass = DataclassMCPServerConfig(
            name="test",
            command=["npx", "-y", "server"],
        )
        assert pydantic.get_command_list() == dataclass.get_command_list()

    def test_official_format_equivalence(self) -> None:
        """Both classes handle official format identically."""
        pydantic = PydanticMCPServerConfig(
            name="test",
            command="npx",
            args=["-y", "server"],
        )
        dataclass = DataclassMCPServerConfig(
            name="test",
            command="npx",
            args=["-y", "server"],
        )
        assert pydantic.get_command_list() == dataclass.get_command_list()

    def test_url_format_equivalence(self) -> None:
        """Both classes handle URL format identically."""
        pydantic = PydanticMCPServerConfig(
            name="test",
            url="http://localhost:8080",
        )
        dataclass = DataclassMCPServerConfig(
            name="test",
            url="http://localhost:8080",
        )
        assert pydantic.get_command_list() == dataclass.get_command_list() == []
