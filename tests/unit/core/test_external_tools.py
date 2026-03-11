"""Tests for optional external tool resolution helpers."""

from pathlib import Path

import pytest

from nexus3.config.schema import SearchConfig
from nexus3.core.external_tools import resolve_ripgrep


class TestResolveRipgrep:
    """Tests for ripgrep resolution behavior."""

    def test_uses_configured_ripgrep_path(self, tmp_path: Path) -> None:
        """Configured ripgrep_path should win over PATH lookup."""
        fake_rg = tmp_path / "rg"
        fake_rg.write_text("")

        resolution = resolve_ripgrep(SearchConfig(ripgrep_path=str(fake_rg)))

        assert resolution.available is True
        assert resolution.executable == str(fake_rg)
        assert resolution.source == "config"

    def test_invalid_configured_path_returns_reason(self) -> None:
        """Missing configured ripgrep_path should produce an unavailable resolution."""
        resolution = resolve_ripgrep(SearchConfig(ripgrep_path="/no/such/rg"))

        assert resolution.available is False
        assert resolution.reason is not None
        assert "does not exist" in resolution.reason

    def test_falls_back_to_path_lookup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """PATH lookup should be used when no explicit path is configured."""
        monkeypatch.setattr("nexus3.core.external_tools.shutil.which", lambda name: "/usr/bin/rg")

        resolution = resolve_ripgrep(SearchConfig())

        assert resolution.available is True
        assert resolution.executable == "/usr/bin/rg"
        assert resolution.source == "PATH"

    def test_reports_missing_ripgrep_on_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Missing PATH ripgrep should return a clear reason."""
        monkeypatch.setattr("nexus3.core.external_tools.shutil.which", lambda name: None)

        resolution = resolve_ripgrep(SearchConfig())

        assert resolution.available is False
        assert resolution.reason == "ripgrep executable 'rg' was not found on PATH"
