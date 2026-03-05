"""Fail-fast tests for malformed mcp.json boundary shapes in ContextLoader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus3.config.schema import ContextConfig
from nexus3.context.loader import ContextLoader
from nexus3.core.errors import MCPConfigError


def _build_loader(project_dir: Path, tmp_path: Path) -> ContextLoader:
    """Create a loader isolated from real global/default directories."""
    loader = ContextLoader(
        cwd=project_dir,
        context_config=ContextConfig(ancestor_depth=0),
    )
    loader._get_global_dir = lambda: tmp_path / "missing-global"  # type: ignore[assignment]
    loader._get_defaults_dir = lambda: tmp_path / "missing-defaults"  # type: ignore[assignment]
    return loader


def test_mcp_servers_wrong_top_level_type_fails_fast(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    nexus_dir = project_dir / ".nexus3"
    nexus_dir.mkdir(parents=True)

    mcp_path = nexus_dir / "mcp.json"
    # Empty string is malformed and previously could be silently skipped.
    mcp_path.write_text(json.dumps({"servers": ""}), encoding="utf-8")

    loader = _build_loader(project_dir=project_dir, tmp_path=tmp_path)

    with pytest.raises(MCPConfigError) as exc_info:
        loader.load()

    message = str(exc_info.value)
    assert "'servers' must be a list of server config objects" in message
    assert "got str" in message
    assert str(mcp_path) in message
    assert exc_info.value.context is not None
    assert exc_info.value.context.server_name == "servers"


def test_mcp_mcpservers_wrong_top_level_type_fails_fast(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    nexus_dir = project_dir / ".nexus3"
    nexus_dir.mkdir(parents=True)

    mcp_path = nexus_dir / "mcp.json"
    mcp_path.write_text(json.dumps({"mcpServers": []}), encoding="utf-8")

    loader = _build_loader(project_dir=project_dir, tmp_path=tmp_path)

    with pytest.raises(MCPConfigError) as exc_info:
        loader.load()

    message = str(exc_info.value)
    assert "'mcpServers' must be an object mapping server names" in message
    assert "got list" in message
    assert str(mcp_path) in message
    assert exc_info.value.context is not None
    assert exc_info.value.context.server_name == "mcpServers"


def test_mcp_servers_list_with_non_dict_entry_fails_fast(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    nexus_dir = project_dir / ".nexus3"
    nexus_dir.mkdir(parents=True)

    mcp_path = nexus_dir / "mcp.json"
    mcp_path.write_text(
        json.dumps(
            {
                "servers": [
                    {"name": "valid", "command": ["echo", "ok"]},
                    123,
                ]
            }
        ),
        encoding="utf-8",
    )

    loader = _build_loader(project_dir=project_dir, tmp_path=tmp_path)

    with pytest.raises(MCPConfigError) as exc_info:
        loader.load()

    message = str(exc_info.value)
    assert "'servers[1]' must be an object" in message
    assert "got int" in message
    assert str(mcp_path) in message
    assert exc_info.value.context is not None
    assert exc_info.value.context.server_name == "servers[1]"


def test_empty_mcpservers_falls_back_to_servers_for_compat(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    nexus_dir = project_dir / ".nexus3"
    nexus_dir.mkdir(parents=True)

    mcp_path = nexus_dir / "mcp.json"
    mcp_path.write_text(
        json.dumps(
            {
                "mcpServers": {},
                "servers": [{"name": "ok", "command": ["echo", "ok"]}],
            }
        ),
        encoding="utf-8",
    )

    loader = _build_loader(project_dir=project_dir, tmp_path=tmp_path)
    loaded = loader.load()

    assert [server.config.name for server in loaded.mcp_servers] == ["ok"]
