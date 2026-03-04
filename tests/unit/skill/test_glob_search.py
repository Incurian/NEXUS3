"""Unit tests for glob skill filesystem gateway path enforcement."""

import asyncio
from pathlib import Path

import pytest

from nexus3.skill.builtin.glob_search import GlobSkill, glob_factory
from nexus3.skill.services import ServiceContainer


def _build_glob_skill(
    *,
    cwd: Path,
    allowed_paths: list[Path] | None,
    blocked_paths: list[Path] | None = None,
) -> GlobSkill:
    services = ServiceContainer()
    services.register("cwd", cwd)
    services.register("allowed_paths", allowed_paths)
    services.register("blocked_paths", blocked_paths or [])
    return glob_factory(services)


class TestGlobGatewayEnforcement:
    """Glob path filtering behavior through FilesystemAccessGateway."""

    @pytest.mark.asyncio
    async def test_glob_skips_symlink_escape(
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
        (allowed / "inside.py").write_text("print('ok')")
        (outside / "secret.py").write_text("print('secret')")

        link = allowed / "secret-link.py"
        try:
            link.symlink_to(outside / "secret.py")
        except OSError as exc:
            pytest.skip(f"symlink creation not supported: {exc}")

        skill = _build_glob_skill(cwd=tmp_path, allowed_paths=[allowed])
        result = await skill.execute(pattern="*.py", path=str(allowed))

        assert not result.error
        assert result.output is not None
        assert "inside.py" in result.output
        assert "secret-link.py" not in result.output
        assert "secret.py" not in result.output

    @pytest.mark.asyncio
    async def test_glob_skips_blocked_paths(
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
        (allowed / "inside.py").write_text("print('ok')")
        (blocked / "hidden.py").write_text("print('hidden')")

        skill = _build_glob_skill(
            cwd=tmp_path,
            allowed_paths=[allowed],
            blocked_paths=[blocked],
        )
        result = await skill.execute(pattern="**/*.py", path=str(allowed))

        assert not result.error
        assert result.output is not None
        assert "inside.py" in result.output
        assert "hidden.py" not in result.output
