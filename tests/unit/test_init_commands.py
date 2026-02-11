"""Tests for init commands."""

from pathlib import Path

import pytest

from nexus3.cli.init_commands import init_global, init_local


class TestInitGlobal:
    """Tests for init_global command."""

    def test_creates_global_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test creates ~/.nexus3/ with default files."""
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: home)

        success, message = init_global()

        assert success
        global_dir = home / ".nexus3"
        assert global_dir.exists()
        assert (global_dir / "NEXUS.md").exists()
        assert (global_dir / "config.json").exists()
        assert (global_dir / "mcp.json").exists()
        assert (global_dir / "sessions").is_dir()

    def test_fails_if_exists(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test fails if directory already exists without --force."""
        home = tmp_path / "home"
        home.mkdir()
        (home / ".nexus3").mkdir()
        monkeypatch.setattr(Path, "home", lambda: home)

        success, message = init_global(force=False)

        assert not success
        assert "already exists" in message

    def test_force_overwrites(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test --force overwrites existing files."""
        home = tmp_path / "home"
        home.mkdir()
        global_dir = home / ".nexus3"
        global_dir.mkdir()
        (global_dir / "NEXUS.md").write_text("old content")
        monkeypatch.setattr(Path, "home", lambda: home)

        success, message = init_global(force=True)

        assert success
        # Content should be new (not "old content")
        content = (global_dir / "NEXUS.md").read_text()
        assert content != "old content"


class TestInitLocal:
    """Tests for init_local command."""

    def test_creates_local_dir(self, tmp_path: Path) -> None:
        """Test creates .nexus3/ with AGENTS.md by default."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        success, message = init_local(cwd=project_dir)

        assert success
        local_dir = project_dir / ".nexus3"
        assert local_dir.exists()
        assert (local_dir / "AGENTS.md").exists()
        assert not (local_dir / "NEXUS.md").exists()
        assert (local_dir / "config.json").exists()
        assert (local_dir / "mcp.json").exists()

    def test_creates_nexus_md_when_specified(self, tmp_path: Path) -> None:
        """Test creates NEXUS.md when filename is specified."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        success, message = init_local(cwd=project_dir, filename="NEXUS.md")

        assert success
        assert (project_dir / ".nexus3" / "NEXUS.md").exists()
        assert not (project_dir / ".nexus3" / "AGENTS.md").exists()

    def test_creates_claude_md_when_specified(self, tmp_path: Path) -> None:
        """Test creates CLAUDE.md when filename is specified."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        success, message = init_local(cwd=project_dir, filename="CLAUDE.md")

        assert success
        assert (project_dir / ".nexus3" / "CLAUDE.md").exists()

    def test_template_content(self, tmp_path: Path) -> None:
        """Test created files have template content."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        init_local(cwd=project_dir)

        # Check AGENTS.md (default) has placeholder sections
        content = (project_dir / ".nexus3" / "AGENTS.md").read_text()
        assert "## Overview" in content
        assert "## Key Files" in content
        assert "## Conventions" in content

        # Check config.json is valid JSON
        import json
        config_content = (project_dir / ".nexus3" / "config.json").read_text()
        config = json.loads(config_content)
        assert isinstance(config, dict)

        # Check mcp.json has empty servers
        mcp_content = (project_dir / ".nexus3" / "mcp.json").read_text()
        mcp = json.loads(mcp_content)
        assert mcp == {"servers": []}

    def test_fails_if_exists(self, tmp_path: Path) -> None:
        """Test fails if directory already exists without --force."""
        project_dir = tmp_path / "project"
        (project_dir / ".nexus3").mkdir(parents=True)

        success, message = init_local(cwd=project_dir, force=False)

        assert not success
        assert "already exists" in message

    def test_force_overwrites(self, tmp_path: Path) -> None:
        """Test --force overwrites existing files."""
        project_dir = tmp_path / "project"
        local_dir = project_dir / ".nexus3"
        local_dir.mkdir(parents=True)
        (local_dir / "AGENTS.md").write_text("old content")

        success, message = init_local(cwd=project_dir, force=True)

        assert success
        content = (local_dir / "AGENTS.md").read_text()
        assert content != "old content"
        assert "## Overview" in content
