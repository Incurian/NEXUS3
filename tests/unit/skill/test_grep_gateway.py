"""Unit tests for grep fallback filesystem gateway enforcement."""

import asyncio
from pathlib import Path

import pytest

from nexus3.skill.builtin.grep import GrepSkill, grep_factory
from nexus3.skill.services import ServiceContainer


def _build_grep_skill(
    *,
    cwd: Path,
    allowed_paths: list[Path] | None,
    blocked_paths: list[Path] | None = None,
) -> GrepSkill:
    services = ServiceContainer()
    services.register("cwd", cwd)
    services.register("allowed_paths", allowed_paths)
    services.register("blocked_paths", blocked_paths or [])
    return grep_factory(services)


class TestGrepGatewayEnforcement:
    """Grep fallback path filtering behavior through FilesystemAccessGateway."""

    @pytest.mark.asyncio
    async def test_grep_fallback_skips_blocked_paths(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def _inline_to_thread(func, /, *args, **kwargs):
            return func(*args, **kwargs)

        monkeypatch.setattr(asyncio, "to_thread", _inline_to_thread)

        allowed = tmp_path / "allowed"
        blocked = allowed / "blocked"
        allowed.mkdir()
        blocked.mkdir()
        (allowed / "inside.txt").write_text("needle\n")
        (blocked / "hidden.txt").write_text("needle\n")

        skill = _build_grep_skill(
            cwd=tmp_path,
            allowed_paths=[allowed],
            blocked_paths=[blocked],
        )
        result = await skill.execute(pattern="needle", path=str(allowed), recursive=True)

        assert not result.error
        assert result.output is not None
        assert "inside.txt" in result.output
        assert "hidden.txt" not in result.output

    @pytest.mark.asyncio
    async def test_grep_fallback_skips_symlink_file_escape(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def _inline_to_thread(func, /, *args, **kwargs):
            return func(*args, **kwargs)

        monkeypatch.setattr(asyncio, "to_thread", _inline_to_thread)

        allowed = tmp_path / "allowed"
        outside = tmp_path / "outside"
        allowed.mkdir()
        outside.mkdir()
        (allowed / "inside.txt").write_text("needle\n")
        (outside / "secret.txt").write_text("needle\n")

        link = allowed / "secret-link.txt"
        try:
            link.symlink_to(outside / "secret.txt")
        except OSError as exc:
            pytest.skip(f"symlink creation not supported: {exc}")

        skill = _build_grep_skill(cwd=tmp_path, allowed_paths=[allowed])
        result = await skill.execute(pattern="needle", path=str(allowed), recursive=True)

        assert not result.error
        assert result.output is not None
        assert "inside.txt" in result.output
        assert "secret-link.txt" not in result.output
        assert "secret.txt" not in result.output

    @pytest.mark.asyncio
    async def test_grep_fallback_skips_symlink_directory_escape(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def _inline_to_thread(func, /, *args, **kwargs):
            return func(*args, **kwargs)

        monkeypatch.setattr(asyncio, "to_thread", _inline_to_thread)

        allowed = tmp_path / "allowed"
        outside = tmp_path / "outside"
        allowed.mkdir()
        outside.mkdir()
        (allowed / "inside.txt").write_text("needle\n")
        (outside / "secret.txt").write_text("needle\n")

        link_dir = allowed / "linked-outside"
        try:
            link_dir.symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"symlink creation not supported: {exc}")

        skill = _build_grep_skill(cwd=tmp_path, allowed_paths=[allowed])
        result = await skill.execute(pattern="needle", path=str(allowed), recursive=True)

        assert not result.error
        assert result.output is not None
        assert "inside.txt" in result.output
        assert "linked-outside/secret.txt" not in result.output
        assert "secret.txt" not in result.output
