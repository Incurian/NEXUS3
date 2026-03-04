"""Unit tests for FilesystemAccessGateway."""

from pathlib import Path

import pytest

from nexus3.core.filesystem_access import FilesystemAccessGateway
from nexus3.skill.services import ServiceContainer


def _build_gateway(
    *,
    cwd: Path,
    allowed_paths: list[Path] | None,
    blocked_paths: list[Path] | None = None,
) -> FilesystemAccessGateway:
    services = ServiceContainer()
    services.register("cwd", cwd)
    services.register("allowed_paths", allowed_paths)
    services.register("blocked_paths", blocked_paths or [])
    return FilesystemAccessGateway(services, tool_name="glob")


class TestFilesystemAccessGateway:
    """Behavior tests for per-candidate authorization filtering."""

    def test_iter_authorized_paths_filters_outside_allowed(self, tmp_path: Path) -> None:
        allowed = tmp_path / "allowed"
        outside = tmp_path / "outside"
        allowed.mkdir()
        outside.mkdir()
        allowed_file = allowed / "ok.txt"
        outside_file = outside / "blocked.txt"
        allowed_file.write_text("ok")
        outside_file.write_text("no")

        gateway = _build_gateway(cwd=tmp_path, allowed_paths=[allowed])
        results = list(
            gateway.iter_authorized_paths(
                [allowed_file, outside_file],
                must_exist=True,
            )
        )

        assert results == [allowed_file]

    def test_iter_authorized_paths_enforces_blocked_paths(self, tmp_path: Path) -> None:
        allowed = tmp_path / "allowed"
        blocked = allowed / "secret"
        allowed.mkdir()
        blocked.mkdir()
        public_file = allowed / "public.txt"
        blocked_file = blocked / "private.txt"
        public_file.write_text("ok")
        blocked_file.write_text("no")

        gateway = _build_gateway(
            cwd=tmp_path,
            allowed_paths=[allowed],
            blocked_paths=[blocked],
        )
        results = list(
            gateway.iter_authorized_paths(
                [public_file, blocked_file],
                must_exist=True,
            )
        )

        assert results == [public_file]

    def test_iter_authorized_paths_blocks_symlink_escape(self, tmp_path: Path) -> None:
        allowed = tmp_path / "allowed"
        outside = tmp_path / "outside"
        allowed.mkdir()
        outside.mkdir()
        outside_file = outside / "secret.txt"
        outside_file.write_text("secret")

        link = allowed / "secret-link.txt"
        try:
            link.symlink_to(outside_file)
        except OSError as exc:
            pytest.skip(f"symlink creation not supported: {exc}")

        gateway = _build_gateway(cwd=tmp_path, allowed_paths=[allowed])
        results = list(gateway.iter_authorized_paths([link], must_exist=True))

        assert results == []

