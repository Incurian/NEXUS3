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
        assert (global_dir / "AGENTS.md").exists()
        assert (global_dir / "NEXUS.md").exists()
        assert (global_dir / "config.json").exists()
        assert (global_dir / "mcp.json").exists()
        assert (global_dir / "sessions").is_dir()

    def test_copies_global_agents_template_from_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test global init seeds ~/.nexus3/AGENTS.md from packaged defaults."""
        home = tmp_path / "home"
        home.mkdir()
        defaults_dir = tmp_path / "defaults"
        defaults_dir.mkdir()
        (defaults_dir / "AGENTS.md").write_text("default agents template")
        (defaults_dir / "NEXUS.md").write_text("default nexus template")
        (defaults_dir / "config.json").write_text("{}")

        monkeypatch.setattr(Path, "home", lambda: home)
        monkeypatch.setattr("nexus3.cli.init_commands.get_defaults_dir", lambda: defaults_dir)

        success, message = init_global()

        assert success
        assert (home / ".nexus3" / "AGENTS.md").read_text() == "default agents template"

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
        """Test creates root AGENTS.md and .nexus3 config files by default."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        success, message = init_local(cwd=project_dir)

        assert success
        assert (project_dir / "AGENTS.md").exists()
        assert not (project_dir / "NEXUS.md").exists()
        local_dir = project_dir / ".nexus3"
        assert local_dir.exists()
        assert (local_dir / "config.json").exists()
        assert (local_dir / "mcp.json").exists()

    def test_creates_nexus_md_when_specified(self, tmp_path: Path) -> None:
        """Test creates NEXUS.md when filename is specified."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        success, message = init_local(cwd=project_dir, filename="NEXUS.md")

        assert success
        assert (project_dir / "NEXUS.md").exists()
        assert not (project_dir / "AGENTS.md").exists()

    def test_creates_claude_md_when_specified(self, tmp_path: Path) -> None:
        """Test creates CLAUDE.md when filename is specified."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        success, message = init_local(cwd=project_dir, filename="CLAUDE.md")

        assert success
        assert (project_dir / "CLAUDE.md").exists()

    def test_template_content(self, tmp_path: Path) -> None:
        """Test created files have template content."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        init_local(cwd=project_dir)

        # Check AGENTS.md (default) comes from the packaged project template
        content = (project_dir / "AGENTS.md").read_text()
        assert "# AGENTS Template" in content
        assert "## Canonical Guidance" in content
        assert "## Project Overview" in content

        # Check config.json is valid JSON
        import json

        config_content = (project_dir / ".nexus3" / "config.json").read_text()
        config = json.loads(config_content)
        assert isinstance(config, dict)

        # Check mcp.json has empty servers
        mcp_content = (project_dir / ".nexus3" / "mcp.json").read_text()
        mcp = json.loads(mcp_content)
        assert mcp == {"servers": []}

    def test_local_agents_uses_global_template_when_available(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test local AGENTS.md copies ~/.nexus3/AGENTS.md when present."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        global_dir = tmp_path / "home" / ".nexus3"
        global_dir.mkdir(parents=True)
        defaults_dir = tmp_path / "defaults"
        defaults_dir.mkdir()
        (global_dir / "AGENTS.md").write_text("home agents template")
        (defaults_dir / "AGENTS.md").write_text("packaged agents template")

        monkeypatch.setattr("nexus3.cli.init_commands.get_nexus_dir", lambda: global_dir)
        monkeypatch.setattr("nexus3.cli.init_commands.get_defaults_dir", lambda: defaults_dir)

        success, message = init_local(cwd=project_dir)

        assert success
        assert (project_dir / "AGENTS.md").read_text() == "home agents template"

    def test_local_agents_falls_back_to_packaged_template(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test local AGENTS.md falls back to defaults when no home template exists."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        global_dir = tmp_path / "home" / ".nexus3"
        defaults_dir = tmp_path / "defaults"
        defaults_dir.mkdir()
        (defaults_dir / "AGENTS.md").write_text("packaged agents template")

        monkeypatch.setattr("nexus3.cli.init_commands.get_nexus_dir", lambda: global_dir)
        monkeypatch.setattr("nexus3.cli.init_commands.get_defaults_dir", lambda: defaults_dir)

        success, message = init_local(cwd=project_dir)

        assert success
        assert (project_dir / "AGENTS.md").read_text() == "packaged agents template"

    def test_allows_existing_local_dir_without_force(self, tmp_path: Path) -> None:
        """Test existing .nexus3/ alone does not block init."""
        project_dir = tmp_path / "project"
        local_dir = project_dir / ".nexus3"
        local_dir.mkdir(parents=True)

        success, message = init_local(cwd=project_dir, force=False)

        assert success
        assert (project_dir / "AGENTS.md").exists()
        assert (local_dir / "config.json").exists()
        assert (local_dir / "mcp.json").exists()

    def test_fails_if_exists(self, tmp_path: Path) -> None:
        """Test fails if a target file already exists without --force."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / "AGENTS.md").write_text("existing content")

        success, message = init_local(cwd=project_dir, force=False)

        assert not success
        assert "already exists" in message

    def test_force_overwrites(self, tmp_path: Path) -> None:
        """Test --force overwrites existing files."""
        project_dir = tmp_path / "project"
        local_dir = project_dir / ".nexus3"
        project_dir.mkdir()
        local_dir.mkdir()
        (project_dir / "AGENTS.md").write_text("old content")

        success, message = init_local(cwd=project_dir, force=True)

        assert success
        content = (project_dir / "AGENTS.md").read_text()
        assert content != "old content"
        assert "## Canonical Guidance" in content
