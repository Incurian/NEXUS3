"""Tests for the ContextLoader with layered configuration."""

import json
from pathlib import Path
from typing import Generator

import pytest

from nexus3.config.schema import ContextConfig
from nexus3.context.loader import (
    ContextLayer,
    ContextLoader,
    ContextSources,
    LoadedContext,
    MCPServerWithOrigin,
)
from nexus3.core.utils import deep_merge, find_ancestor_config_dirs


class TestDeepMerge:
    """Tests for the deep_merge function."""

    def test_simple_merge(self) -> None:
        """Test basic key merging."""
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        result = deep_merge(base, override)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self) -> None:
        """Test nested dict merging."""
        base = {"outer": {"a": 1, "b": 2}}
        override = {"outer": {"b": 3, "c": 4}}
        result = deep_merge(base, override)
        assert result == {"outer": {"a": 1, "b": 3, "c": 4}}

    def test_list_replacement(self) -> None:
        """Test list replacement (P2.14 security fix).

        Lists are now REPLACED, not concatenated. This is critical for
        security-related config like blocked_paths where local config
        needs to be able to override global config.
        """
        base = {"items": [1, 2]}
        override = {"items": [3, 4]}
        result = deep_merge(base, override)
        assert result == {"items": [3, 4]}

    def test_type_override(self) -> None:
        """Test different types override."""
        base = {"key": [1, 2]}
        override = {"key": "string"}
        result = deep_merge(base, override)
        assert result == {"key": "string"}

    def test_empty_base(self) -> None:
        """Test merge with empty base."""
        result = deep_merge({}, {"a": 1})
        assert result == {"a": 1}

    def test_empty_override(self) -> None:
        """Test merge with empty override."""
        result = deep_merge({"a": 1}, {})
        assert result == {"a": 1}


class TestContextLayer:
    """Tests for the ContextLayer dataclass."""

    def test_layer_creation(self) -> None:
        """Test creating a context layer."""
        layer = ContextLayer(
            name="test",
            path=Path("/test"),
            prompt="Hello",
            config={"key": "value"},
        )
        assert layer.name == "test"
        assert layer.path == Path("/test")
        assert layer.prompt == "Hello"
        assert layer.config == {"key": "value"}
        assert layer.mcp is None
        assert layer.readme is None


class TestContextLoader:
    """Tests for the ContextLoader class."""

    @pytest.fixture
    def temp_dir(self, tmp_path: Path) -> Generator[Path, None, None]:
        """Create a temporary directory structure."""
        # Create global dir
        global_dir = tmp_path / "home" / ".nexus3"
        global_dir.mkdir(parents=True)
        (global_dir / "NEXUS.md").write_text("Global prompt")
        (global_dir / "config.json").write_text('{"stream_output": false}')

        # Create project structure
        project_dir = tmp_path / "projects" / "company" / "backend" / "app"
        project_dir.mkdir(parents=True)

        # Company level
        company_nexus = tmp_path / "projects" / "company" / ".nexus3"
        company_nexus.mkdir()
        (company_nexus / "NEXUS.md").write_text("Company prompt")
        (company_nexus / "config.json").write_text('{"max_tool_iterations": 5}')

        # Backend level
        backend_nexus = tmp_path / "projects" / "company" / "backend" / ".nexus3"
        backend_nexus.mkdir()
        (backend_nexus / "NEXUS.md").write_text("Backend prompt")

        # App level (local)
        app_nexus = project_dir / ".nexus3"
        app_nexus.mkdir()
        (app_nexus / "NEXUS.md").write_text("App prompt")
        (app_nexus / "config.json").write_text('{"skill_timeout": 60.0}')

        yield project_dir

    def test_load_global_only(self, tmp_path: Path) -> None:
        """Test loading only global context."""
        global_dir = tmp_path / ".nexus3"
        global_dir.mkdir()
        (global_dir / "NEXUS.md").write_text("Test prompt")

        # Mock home directory
        loader = ContextLoader(cwd=tmp_path)
        loader._get_global_dir = lambda: global_dir  # type: ignore

        context = loader.load()
        assert "Test prompt" in context.system_prompt
        assert context.sources.global_dir == global_dir

    def test_ancestor_discovery(self, tmp_path: Path) -> None:
        """Test finding ancestor config directories."""
        # Create nested structure
        deep_dir = tmp_path / "a" / "b" / "c" / "project"
        deep_dir.mkdir(parents=True)

        # Create ancestor configs
        (tmp_path / "a" / ".nexus3").mkdir()
        (tmp_path / "a" / "b" / ".nexus3").mkdir()

        ancestors = find_ancestor_config_dirs(deep_dir, max_depth=3)

        assert len(ancestors) == 2
        # Should be in order: furthest first
        assert ancestors[0] == tmp_path / "a" / ".nexus3"
        assert ancestors[1] == tmp_path / "a" / "b" / ".nexus3"

    def test_ancestor_depth_limit(self, tmp_path: Path) -> None:
        """Test ancestor depth configuration."""
        # Create nested structure
        deep_dir = tmp_path / "a" / "b" / "c" / "project"
        deep_dir.mkdir(parents=True)

        # Create ancestor configs at all levels
        (tmp_path / "a" / ".nexus3").mkdir()
        (tmp_path / "a" / "b" / ".nexus3").mkdir()
        (tmp_path / "a" / "b" / "c" / ".nexus3").mkdir()

        # With depth 1, only immediate parent should be found
        ancestors = find_ancestor_config_dirs(deep_dir, max_depth=1)

        assert len(ancestors) == 1
        assert ancestors[0] == tmp_path / "a" / "b" / "c" / ".nexus3"

    def test_load_json_empty_file(self, tmp_path: Path) -> None:
        """Test loading empty JSON file returns empty dict."""
        empty_file = tmp_path / "empty.json"
        empty_file.write_text("")

        loader = ContextLoader(cwd=tmp_path)
        result = loader._load_json(empty_file)
        assert result == {}

    def test_load_json_invalid(self, tmp_path: Path) -> None:
        """Test loading invalid JSON raises error."""
        from nexus3.core.errors import ContextLoadError

        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json")

        loader = ContextLoader(cwd=tmp_path)
        with pytest.raises(ContextLoadError, match="Invalid JSON"):
            loader._load_json(bad_file)

    def test_labeled_sections(self, tmp_path: Path) -> None:
        """Test that loaded context has labeled sections."""
        global_dir = tmp_path / "global" / ".nexus3"
        global_dir.mkdir(parents=True)
        (global_dir / "NEXUS.md").write_text("Global content")

        local_dir = tmp_path / "project" / ".nexus3"
        local_dir.mkdir(parents=True)
        (local_dir / "NEXUS.md").write_text("Local content")

        loader = ContextLoader(
            cwd=tmp_path / "project",
            context_config=ContextConfig(ancestor_depth=0),
        )
        loader._get_global_dir = lambda: global_dir  # type: ignore

        context = loader.load()

        # Check for labeled sections
        assert "## Global Configuration" in context.system_prompt
        assert "## Project Configuration" in context.system_prompt
        assert "Source:" in context.system_prompt
        assert "Global content" in context.system_prompt
        assert "Local content" in context.system_prompt

    def test_readme_fallback(self, tmp_path: Path) -> None:
        """Test README.md is used as fallback when NEXUS.md is missing."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        nexus_dir = project_dir / ".nexus3"
        nexus_dir.mkdir()
        # No NEXUS.md, but README.md exists in project root
        (project_dir / "README.md").write_text("README content")

        loader = ContextLoader(
            cwd=project_dir,
            context_config=ContextConfig(ancestor_depth=0, readme_as_fallback=True),
        )
        # Mock global to return nothing
        loader._get_global_dir = lambda: tmp_path / "nonexistent"  # type: ignore
        loader._get_defaults_dir = lambda: tmp_path / "nonexistent"  # type: ignore

        context = loader.load()
        assert "README content" in context.system_prompt

    def test_readme_disabled(self, tmp_path: Path) -> None:
        """Test README.md is not used when fallback is disabled."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        nexus_dir = project_dir / ".nexus3"
        nexus_dir.mkdir()
        (project_dir / "README.md").write_text("README content")

        loader = ContextLoader(
            cwd=project_dir,
            context_config=ContextConfig(ancestor_depth=0, readme_as_fallback=False),
        )
        loader._get_global_dir = lambda: tmp_path / "nonexistent"  # type: ignore
        loader._get_defaults_dir = lambda: tmp_path / "nonexistent"  # type: ignore

        context = loader.load()
        # Should get fallback prompt, not README
        assert "README content" not in context.system_prompt
        assert "helpful AI assistant" in context.system_prompt

    def test_mcp_server_merging(self, tmp_path: Path) -> None:
        """Test MCP servers are merged from all layers."""
        global_dir = tmp_path / "global" / ".nexus3"
        global_dir.mkdir(parents=True)
        (global_dir / "mcp.json").write_text(json.dumps({
            "servers": [
                {"name": "global-server", "command": ["echo", "global"]}
            ]
        }))

        local_dir = tmp_path / "project" / ".nexus3"
        local_dir.mkdir(parents=True)
        (local_dir / "mcp.json").write_text(json.dumps({
            "servers": [
                {"name": "local-server", "command": ["echo", "local"]}
            ]
        }))

        loader = ContextLoader(
            cwd=tmp_path / "project",
            context_config=ContextConfig(ancestor_depth=0),
        )
        loader._get_global_dir = lambda: global_dir  # type: ignore

        context = loader.load()

        assert len(context.mcp_servers) == 2
        names = {s.config.name for s in context.mcp_servers}
        assert names == {"global-server", "local-server"}

    def test_mcp_server_override(self, tmp_path: Path) -> None:
        """Test local MCP server overrides global with same name."""
        global_dir = tmp_path / "global" / ".nexus3"
        global_dir.mkdir(parents=True)
        (global_dir / "mcp.json").write_text(json.dumps({
            "servers": [
                {"name": "shared", "command": ["echo", "global"]}
            ]
        }))

        local_dir = tmp_path / "project" / ".nexus3"
        local_dir.mkdir(parents=True)
        (local_dir / "mcp.json").write_text(json.dumps({
            "servers": [
                {"name": "shared", "command": ["echo", "local"]}
            ]
        }))

        loader = ContextLoader(
            cwd=tmp_path / "project",
            context_config=ContextConfig(ancestor_depth=0),
        )
        loader._get_global_dir = lambda: global_dir  # type: ignore

        context = loader.load()

        assert len(context.mcp_servers) == 1
        server = context.mcp_servers[0]
        assert server.config.name == "shared"
        assert server.config.command == ["echo", "local"]
        assert server.origin == "local"


class TestContextLoaderSubagent:
    """Tests for subagent context loading."""

    def test_subagent_inherits_parent_context(self, tmp_path: Path) -> None:
        """Test subagent gets parent context when no local NEXUS.md."""
        parent_sources = ContextSources(
            prompt_sources=[],
        )
        parent_context = LoadedContext(
            system_prompt="Parent prompt content",
            merged_config={},
            mcp_servers=[],
            sources=parent_sources,
        )

        # Subagent directory has no NEXUS.md
        subagent_cwd = tmp_path / "subproject"
        subagent_cwd.mkdir()

        loader = ContextLoader(cwd=subagent_cwd)
        prompt = loader.load_for_subagent(parent_context=parent_context)

        # Parent content is preserved
        assert "Parent prompt content" in prompt
        # Subagent gets its own environment info with correct cwd
        assert "# Environment" in prompt
        assert f"Working directory: {subagent_cwd}" in prompt

    def test_subagent_adds_local_context(self, tmp_path: Path) -> None:
        """Test subagent adds its local NEXUS.md to parent context."""
        from nexus3.context.loader import PromptSource

        parent_sources = ContextSources(
            prompt_sources=[PromptSource(path=Path("/global/NEXUS.md"), layer_name="global")],
        )
        parent_context = LoadedContext(
            system_prompt="Parent prompt",
            merged_config={},
            mcp_servers=[],
            sources=parent_sources,
        )

        # Create subagent NEXUS.md
        subagent_cwd = tmp_path / "subproject"
        nexus_dir = subagent_cwd / ".nexus3"
        nexus_dir.mkdir(parents=True)
        nexus_md = nexus_dir / "NEXUS.md"
        nexus_md.write_text("Subagent specific instructions")

        loader = ContextLoader(cwd=subagent_cwd)
        prompt = loader.load_for_subagent(parent_context=parent_context)

        # Should have both
        assert "Subagent specific instructions" in prompt
        assert "Parent prompt" in prompt
        assert "## Subagent Configuration" in prompt

    def test_subagent_no_duplicate(self, tmp_path: Path) -> None:
        """Test subagent doesn't duplicate parent's already-loaded NEXUS.md."""
        from nexus3.context.loader import PromptSource

        nexus_path = tmp_path / "project" / ".nexus3" / "NEXUS.md"
        nexus_path.parent.mkdir(parents=True)
        nexus_path.write_text("Shared content")

        parent_sources = ContextSources(
            prompt_sources=[PromptSource(path=nexus_path, layer_name="local")],
        )
        parent_context = LoadedContext(
            system_prompt="Parent already has this content",
            merged_config={},
            mcp_servers=[],
            sources=parent_sources,
        )

        loader = ContextLoader(cwd=tmp_path / "project")
        prompt = loader.load_for_subagent(parent_context=parent_context)

        # Should just use parent context (no duplication)
        assert prompt == "Parent already has this content"
