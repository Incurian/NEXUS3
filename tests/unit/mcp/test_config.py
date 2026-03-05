"""Tests for canonical MCPServerConfig behavior and compatibility aliases."""

import pytest

from nexus3.config.schema import MCPServerConfig as SchemaMCPServerConfig
from nexus3.mcp.registry import MCPServerConfig as RegistryMCPServerConfig


class TestMCPServerConfig:
    """Tests for the canonical MCPServerConfig model."""

    def test_nexus3_format_command_list(self) -> None:
        """NEXUS3 format: command as list."""
        config = SchemaMCPServerConfig(
            name="test",
            command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/path"],
        )
        assert config.get_command_list() == [
            "npx", "-y", "@modelcontextprotocol/server-filesystem", "/path"
        ]

    def test_official_mcp_format(self) -> None:
        """Official format: command string + args array."""
        config = SchemaMCPServerConfig(
            name="test",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", "/path"],
        )
        assert config.get_command_list() == [
            "npx", "-y", "@modelcontextprotocol/server-filesystem", "/path"
        ]

    def test_command_string_no_args(self) -> None:
        """Command string with no args."""
        config = SchemaMCPServerConfig(name="test", command="echo")
        assert config.get_command_list() == ["echo"]

    def test_command_string_empty_args(self) -> None:
        """Command string with empty args list."""
        config = SchemaMCPServerConfig(name="test", command="echo", args=[])
        assert config.get_command_list() == ["echo"]

    def test_url_config_no_command(self) -> None:
        """URL-based config has no command."""
        config = SchemaMCPServerConfig(name="test", url="http://localhost:8080")
        assert config.get_command_list() == []

    def test_command_list_ignores_args(self) -> None:
        """When command is a list, args field is ignored."""
        config = SchemaMCPServerConfig(
            name="test",
            command=["echo", "hello"],
            args=["ignored", "args"],
        )
        # List command takes precedence, args ignored
        assert config.get_command_list() == ["echo", "hello"]

    def test_validation_both_command_and_url(self) -> None:
        """Cannot specify both command and url."""
        with pytest.raises(ValueError, match="Cannot specify both"):
            SchemaMCPServerConfig(
                name="test",
                command="echo",
                url="http://localhost:8080",
            )

    def test_validation_neither_command_nor_url(self) -> None:
        """Must specify either command or url."""
        with pytest.raises(ValueError, match="Must specify either"):
            SchemaMCPServerConfig(name="test")

    def test_defaults(self) -> None:
        """Verify default values."""
        config = SchemaMCPServerConfig(name="test", command=["echo"])
        assert config.args is None
        assert config.url is None
        assert config.env is None
        assert config.env_passthrough is None
        assert config.cwd is None
        assert config.enabled is True
        assert config.fail_if_no_tools is False

    def test_fail_if_no_tools_override(self) -> None:
        """Registry-specific fail_if_no_tools flag is available on canonical model."""
        config = SchemaMCPServerConfig(
            name="test",
            command=["echo"],
            fail_if_no_tools=True,
        )
        assert config.fail_if_no_tools is True

class TestCompatibilityAliases:
    """Backwards-compatible import locations still expose MCPServerConfig."""

    def test_registry_alias_matches_schema_class(self) -> None:
        """Registry import path aliases the canonical schema class."""
        assert RegistryMCPServerConfig is SchemaMCPServerConfig
