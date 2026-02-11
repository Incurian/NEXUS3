from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

from nexus3.ide.discovery import _is_pid_alive, discover_ides


class TestIsPidAlive:
    def test_negative_pid(self) -> None:
        assert _is_pid_alive(-1) is False

    def test_zero_pid(self) -> None:
        assert _is_pid_alive(0) is False

    def test_alive_pid(self) -> None:
        # Current process is always alive
        assert _is_pid_alive(os.getpid()) is True

    def test_dead_pid(self) -> None:
        with patch("os.kill", side_effect=ProcessLookupError):
            assert _is_pid_alive(99999) is False

    def test_permission_error_means_alive(self) -> None:
        with patch("os.kill", side_effect=PermissionError):
            assert _is_pid_alive(99999) is True

    def test_generic_os_error(self) -> None:
        with patch("os.kill", side_effect=OSError):
            assert _is_pid_alive(99999) is False


class TestDiscoverIdes:
    def test_missing_directory(self, tmp_path: Path) -> None:
        result = discover_ides(tmp_path, lock_dir=tmp_path / "nonexistent")
        assert result == []

    def test_empty_directory(self, tmp_path: Path) -> None:
        lock_dir = tmp_path / "ide"
        lock_dir.mkdir()
        result = discover_ides(tmp_path, lock_dir=lock_dir)
        assert result == []

    def test_valid_lock_file(self, tmp_path: Path) -> None:
        lock_dir = tmp_path / "ide"
        lock_dir.mkdir()
        workspace = tmp_path / "project"
        workspace.mkdir()

        lock_data = {
            "pid": os.getpid(),  # Current process is alive
            "workspaceFolders": [str(workspace)],
            "ideName": "VS Code",
            "transport": "ws",
            "authToken": "test-token-123",
        }
        lock_file = lock_dir / "9999.lock"
        lock_file.write_text(json.dumps(lock_data), encoding="utf-8")

        result = discover_ides(workspace, lock_dir=lock_dir)
        assert len(result) == 1
        assert result[0].port == 9999
        assert result[0].ide_name == "VS Code"
        assert result[0].auth_token == "test-token-123"
        assert result[0].pid == os.getpid()

    def test_stale_lock_file_cleaned_up(self, tmp_path: Path) -> None:
        lock_dir = tmp_path / "ide"
        lock_dir.mkdir()

        lock_data = {
            "pid": 1,  # PID 1 exists but we'll mock it as dead
            "workspaceFolders": [str(tmp_path)],
            "ideName": "VS Code",
            "transport": "ws",
            "authToken": "token",
        }
        lock_file = lock_dir / "8888.lock"
        lock_file.write_text(json.dumps(lock_data), encoding="utf-8")

        with patch("nexus3.ide.discovery._is_pid_alive", return_value=False):
            result = discover_ides(tmp_path, lock_dir=lock_dir)

        assert result == []
        assert not lock_file.exists()  # Stale file cleaned up

    def test_non_numeric_filename_skipped(self, tmp_path: Path) -> None:
        lock_dir = tmp_path / "ide"
        lock_dir.mkdir()

        lock_file = lock_dir / "not-a-number.lock"
        lock_file.write_text("{}", encoding="utf-8")

        result = discover_ides(tmp_path, lock_dir=lock_dir)
        assert result == []

    def test_malformed_json_skipped(self, tmp_path: Path) -> None:
        lock_dir = tmp_path / "ide"
        lock_dir.mkdir()

        lock_file = lock_dir / "1234.lock"
        lock_file.write_text("not json!", encoding="utf-8")

        result = discover_ides(tmp_path, lock_dir=lock_dir)
        assert result == []

    def test_workspace_mismatch_filtered(self, tmp_path: Path) -> None:
        lock_dir = tmp_path / "ide"
        lock_dir.mkdir()

        lock_data = {
            "pid": os.getpid(),
            "workspaceFolders": ["/some/other/path"],
            "ideName": "VS Code",
            "transport": "ws",
            "authToken": "token",
        }
        lock_file = lock_dir / "7777.lock"
        lock_file.write_text(json.dumps(lock_data), encoding="utf-8")

        result = discover_ides(tmp_path, lock_dir=lock_dir)
        assert result == []

    def test_sorted_by_longest_prefix(self, tmp_path: Path) -> None:
        lock_dir = tmp_path / "ide"
        lock_dir.mkdir()
        project = tmp_path / "project" / "sub"
        project.mkdir(parents=True)

        # Broader workspace
        lock1 = {
            "pid": os.getpid(),
            "workspaceFolders": [str(tmp_path)],
            "ideName": "Broad",
            "transport": "ws",
            "authToken": "t1",
        }
        (lock_dir / "1111.lock").write_text(json.dumps(lock1), encoding="utf-8")

        # More specific workspace
        lock2 = {
            "pid": os.getpid(),
            "workspaceFolders": [str(tmp_path / "project")],
            "ideName": "Specific",
            "transport": "ws",
            "authToken": "t2",
        }
        (lock_dir / "2222.lock").write_text(json.dumps(lock2), encoding="utf-8")

        result = discover_ides(project, lock_dir=lock_dir)
        assert len(result) == 2
        assert result[0].ide_name == "Specific"  # Longer prefix first
        assert result[1].ide_name == "Broad"
