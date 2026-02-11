from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class IDEInfo:
    pid: int
    workspace_folders: list[str]
    ide_name: str
    transport: str
    auth_token: str
    port: int
    lock_path: Path


def discover_ides(cwd: Path, lock_dir: Path | None = None) -> list[IDEInfo]:
    """Scan lock files, validate PIDs, match workspace to cwd.

    Returns list sorted by best workspace match (longest prefix first).
    Returns [] if directory doesn't exist or no matches found.
    """
    lock_dir = lock_dir or Path.home() / ".nexus3" / "ide"
    if not lock_dir.is_dir():
        return []

    resolved_cwd = cwd.resolve()
    results: list[IDEInfo] = []

    for lock_file in lock_dir.glob("*.lock"):
        # Port from filename stem
        try:
            port = int(lock_file.stem)
        except ValueError:
            continue

        # Parse JSON
        try:
            data = json.loads(lock_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        pid = data.get("pid", 0)
        if not _is_pid_alive(pid):
            # Stale lock file — clean up
            try:
                lock_file.unlink()
            except OSError:
                pass
            continue

        # Check workspace match
        folders = data.get("workspaceFolders", [])
        if not any(resolved_cwd.is_relative_to(Path(f).resolve()) for f in folders):
            continue

        results.append(IDEInfo(
            pid=pid,
            workspace_folders=folders,
            ide_name=data.get("ideName", "Unknown"),
            transport=data.get("transport", "ws"),
            auth_token=data.get("authToken", ""),
            port=port,
            lock_path=lock_file,
        ))

    # Sort by longest matching workspace prefix (best match first)
    results.sort(
        key=lambda i: max(
            (len(str(Path(f).resolve())) for f in i.workspace_folders
             if resolved_cwd.is_relative_to(Path(f).resolve())),
            default=0,
        ),
        reverse=True,
    )
    return results


def _is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False  # Process doesn't exist
    except PermissionError:
        return True  # Exists but different user
    except OSError:
        return False
