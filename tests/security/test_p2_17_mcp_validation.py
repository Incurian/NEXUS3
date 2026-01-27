"""P2.17b: MCP Validation Fix Tests.

Tests that invalid MCP server configurations raise errors instead of being
silently dropped.

Security issue: Silent exception swallowing in _merge_mcp_servers() would
allow invalid configs to be ignored, potentially masking misconfiguration
that could lead to missing tools or security controls.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from nexus3.config.schema import MCPServerConfig
from nexus3.context.loader import ContextLoader
from nexus3.core.errors import MCPConfigError

if TYPE_CHECKING:
    from pytest import TempPathFactory


class TestMCPServerConfigValidation:
    """Test MCPServerConfig Pydantic validation."""

    def test_valid_with_command_only(self) -> None:
        """MCPServerConfig with only command is valid."""
        config = MCPServerConfig(
            name="test-server",
            command=["python", "-m", "test_server"],
        )
        assert config.name == "test-server"
        assert config.command == ["python", "-m", "test_server"]
        assert config.url is None

    def test_valid_with_url_only(self) -> None:
        """MCPServerConfig with only url is valid."""
        config = MCPServerConfig(
            name="test-server",
            url="http://localhost:8080",
        )
        assert config.name == "test-server"
        assert config.url == "http://localhost:8080"
        assert config.command is None

    def test_invalid_with_both_command_and_url(self) -> None:
        """MCPServerConfig with both command and url raises ValueError."""
        with pytest.raises(ValidationError) as exc_info:
            MCPServerConfig(
                name="test-server",
                command=["python", "-m", "test_server"],
                url="http://localhost:8080",
            )

        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert "Cannot specify both 'command' and 'url'" in str(errors[0]["msg"])

    def test_invalid_with_neither_command_nor_url(self) -> None:
        """MCPServerConfig with neither command nor url raises ValueError."""
        with pytest.raises(ValidationError) as exc_info:
            MCPServerConfig(name="test-server")

        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert "Must specify either 'command' or 'url'" in str(errors[0]["msg"])

    def test_command_can_be_empty_list(self) -> None:
        """Empty command list is treated as falsy (no command specified)."""
        # Empty list is falsy in Python, so this should fail validation
        with pytest.raises(ValidationError) as exc_info:
            MCPServerConfig(name="test-server", command=[])

        errors = exc_info.value.errors()
        assert "Must specify either 'command' or 'url'" in str(errors[0]["msg"])

    def test_url_can_be_empty_string(self) -> None:
        """Empty url string is treated as falsy (no url specified)."""
        # Empty string is falsy in Python, so this should fail validation
        with pytest.raises(ValidationError) as exc_info:
            MCPServerConfig(name="test-server", url="")

        errors = exc_info.value.errors()
        assert "Must specify either 'command' or 'url'" in str(errors[0]["msg"])


class TestContextLoaderMCPValidation:
    """Test ContextLoader raises MCPConfigError for invalid MCP configs."""

    @pytest.fixture
    def temp_project(self, tmp_path_factory: TempPathFactory) -> Path:
        """Create a temporary project directory with .nexus3 folder."""
        project_dir = tmp_path_factory.mktemp("project")
        nexus_dir = project_dir / ".nexus3"
        nexus_dir.mkdir()
        return project_dir

    def test_invalid_server_raises_mcp_config_error(self, temp_project: Path) -> None:
        """Invalid MCP server config raises MCPConfigError (not silently dropped)."""
        mcp_path = temp_project / ".nexus3" / "mcp.json"
        mcp_path.write_text(
            json.dumps(
                {
                    "servers": [
                        {
                            "name": "invalid-server",
                            # Neither command nor url - should fail
                        }
                    ]
                }
            )
        )

        loader = ContextLoader(cwd=temp_project)

        with pytest.raises(MCPConfigError) as exc_info:
            loader.load()

        assert "Invalid MCP server config" in str(exc_info.value)
        assert str(mcp_path) in str(exc_info.value)

    def test_both_command_and_url_raises_mcp_config_error(
        self, temp_project: Path
    ) -> None:
        """MCP server with both command and url raises MCPConfigError."""
        mcp_path = temp_project / ".nexus3" / "mcp.json"
        mcp_path.write_text(
            json.dumps(
                {
                    "servers": [
                        {
                            "name": "both-transport",
                            "command": ["python", "server.py"],
                            "url": "http://localhost:8080",
                        }
                    ]
                }
            )
        )

        loader = ContextLoader(cwd=temp_project)

        with pytest.raises(MCPConfigError) as exc_info:
            loader.load()

        assert "Invalid MCP server config" in str(exc_info.value)
        # Sanitized error shows field names, not full validation message
        assert "validation failed for fields" in str(exc_info.value)

    def test_missing_name_raises_mcp_config_error(self, temp_project: Path) -> None:
        """MCP server without name raises MCPConfigError."""
        mcp_path = temp_project / ".nexus3" / "mcp.json"
        mcp_path.write_text(
            json.dumps(
                {
                    "servers": [
                        {
                            # Missing name
                            "command": ["python", "server.py"]
                        }
                    ]
                }
            )
        )

        loader = ContextLoader(cwd=temp_project)

        with pytest.raises(MCPConfigError) as exc_info:
            loader.load()

        assert "Invalid MCP server config" in str(exc_info.value)
        assert str(mcp_path) in str(exc_info.value)

    def test_extra_field_raises_mcp_config_error(self, temp_project: Path) -> None:
        """MCP server with extra field raises MCPConfigError (extra=forbid)."""
        mcp_path = temp_project / ".nexus3" / "mcp.json"
        mcp_path.write_text(
            json.dumps(
                {
                    "servers": [
                        {
                            "name": "extra-field-server",
                            "command": ["python", "server.py"],
                            "unknown_field": "should fail",
                        }
                    ]
                }
            )
        )

        loader = ContextLoader(cwd=temp_project)

        with pytest.raises(MCPConfigError) as exc_info:
            loader.load()

        assert "Invalid MCP server config" in str(exc_info.value)

    def test_error_message_includes_source_path(self, temp_project: Path) -> None:
        """Error message includes the path to the problematic mcp.json file."""
        mcp_path = temp_project / ".nexus3" / "mcp.json"
        mcp_path.write_text(
            json.dumps(
                {
                    "servers": [
                        {
                            "name": "no-transport",
                            # Neither command nor url
                        }
                    ]
                }
            )
        )

        loader = ContextLoader(cwd=temp_project)

        with pytest.raises(MCPConfigError) as exc_info:
            loader.load()

        error_message = str(exc_info.value)
        # Check that the full path is included
        assert str(mcp_path) in error_message
        # Also verify mcp.json filename is present
        assert "mcp.json" in error_message

    def test_valid_server_loads_successfully(self, temp_project: Path) -> None:
        """Valid MCP server config loads without error."""
        mcp_path = temp_project / ".nexus3" / "mcp.json"
        mcp_path.write_text(
            json.dumps(
                {
                    "servers": [
                        {
                            "name": "valid-server",
                            "command": ["python", "-m", "my_server"],
                        },
                        {
                            "name": "http-server",
                            "url": "http://localhost:9000",
                        },
                    ]
                }
            )
        )

        loader = ContextLoader(cwd=temp_project)
        context = loader.load()

        assert len(context.mcp_servers) == 2
        server_names = [s.config.name for s in context.mcp_servers]
        assert "valid-server" in server_names
        assert "http-server" in server_names

    def test_second_invalid_server_still_raises(self, temp_project: Path) -> None:
        """Second invalid server in list still raises (fail-fast behavior)."""
        mcp_path = temp_project / ".nexus3" / "mcp.json"
        mcp_path.write_text(
            json.dumps(
                {
                    "servers": [
                        {
                            "name": "valid-server",
                            "command": ["python", "good.py"],
                        },
                        {
                            "name": "invalid-server",
                            # No transport
                        },
                    ]
                }
            )
        )

        loader = ContextLoader(cwd=temp_project)

        with pytest.raises(MCPConfigError) as exc_info:
            loader.load()

        assert "Invalid MCP server config" in str(exc_info.value)


class TestMCPConfigErrorChain:
    """Test that MCPConfigError properly chains the original exception."""

    def test_exception_chain_preserved(self, tmp_path: Path) -> None:
        """Original ValidationError is preserved in exception chain."""
        project_dir = tmp_path
        nexus_dir = project_dir / ".nexus3"
        nexus_dir.mkdir()

        mcp_path = nexus_dir / "mcp.json"
        mcp_path.write_text(
            json.dumps(
                {
                    "servers": [
                        {
                            "name": "bad-server",
                            # Neither command nor url
                        }
                    ]
                }
            )
        )

        loader = ContextLoader(cwd=project_dir)

        with pytest.raises(MCPConfigError) as exc_info:
            loader.load()

        # Verify the __cause__ is the original exception
        assert exc_info.value.__cause__ is not None
        # The cause should be a ValidationError from pydantic
        assert isinstance(exc_info.value.__cause__, ValidationError)
