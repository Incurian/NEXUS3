from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_IS_WSL = "microsoft" in (
    Path("/proc/version").read_text(errors="ignore")
    if Path("/proc/version").exists()
    else ""
).lower()


@dataclass
class IDEInfo:
    pid: int
    workspace_folders: list[str]
    ide_name: str
    transport: str
    auth_token: str
    port: int
    lock_path: Path


def _get_lock_dirs() -> list[Path]:
    """Return lock directories to scan, in priority order.

    On WSL, also checks the Windows user's ~/.nexus3/ide/ via /mnt/c/.
    """
    dirs = [Path.home() / ".nexus3" / "ide"]
    if _IS_WSL:
        win_home = _get_windows_home()
        if win_home:
            win_lock_dir = win_home / ".nexus3" / "ide"
            if win_lock_dir != dirs[0]:
                dirs.append(win_lock_dir)
    return dirs


def _get_windows_home() -> Path | None:
    """Get the Windows user home directory from WSL."""
    # Try USERPROFILE via cmd.exe (fast, no PowerShell startup)
    cmd_exe = shutil.which("cmd.exe")
    if not cmd_exe:
        return None
    try:
        result = subprocess.run(
            [cmd_exe, "/C", "echo", "%USERPROFILE%"],
            capture_output=True, text=True, timeout=5,
        )
        win_path = result.stdout.strip()
        if win_path and "%" not in win_path:
            return _win_path_to_wsl(win_path)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def _win_path_to_wsl(win_path: str) -> Path | None:
    r"""Convert a Windows path (C:\Users\inc) to WSL (/mnt/c/Users/inc)."""
    # Match drive letter paths: C:\... or C:/...
    m = re.match(r"^([A-Za-z]):[/\\](.*)", win_path)
    if not m:
        return None
    drive = m.group(1).lower()
    rest = m.group(2).replace("\\", "/")
    return Path(f"/mnt/{drive}/{rest}")


def _wsl_unc_to_local(unc_path: str) -> Path | None:
    r"""Convert \\wsl.localhost\<Distro>\path to /path.

    Handles: \\wsl.localhost\Ubuntu\home\inc\repos\NEXUS3
    Returns: /home/inc/repos/NEXUS3 (if distro matches)
    """
    # Normalize separators
    normalized = unc_path.replace("\\", "/")
    # Match //wsl.localhost/<distro>/<rest> or //wsl$/<distro>/<rest>
    m = re.match(
        r"^//wsl(?:\.localhost|\$)/([^/]+)/(.*)", normalized,
    )
    if not m:
        return None
    distro = m.group(1)
    rest = m.group(2)
    # Verify distro matches (optional — accept any for flexibility)
    wsl_distro = os.environ.get("WSL_DISTRO_NAME", "")
    if wsl_distro and distro.lower() != wsl_distro.lower():
        return None
    return Path(f"/{rest}")


def _resolve_workspace_folder(folder: str) -> Path:
    """Resolve a workspace folder path, handling WSL UNC paths."""
    if _IS_WSL and (folder.startswith("\\\\") or folder.startswith("//")):
        local = _wsl_unc_to_local(folder)
        if local:
            return local.resolve()
    return Path(folder).resolve()


def discover_ides(cwd: Path, lock_dir: Path | None = None) -> list[IDEInfo]:
    """Scan lock files, validate PIDs, match workspace to cwd.

    Returns list sorted by best workspace match (longest prefix first).
    Returns [] if directory doesn't exist or no matches found.
    On WSL, also scans the Windows user's lock directory.
    """
    if lock_dir:
        lock_dirs = [lock_dir]
    else:
        lock_dirs = _get_lock_dirs()

    resolved_cwd = cwd.resolve()
    results: list[IDEInfo] = []

    for scan_dir in lock_dirs:
        if not scan_dir.is_dir():
            continue
        for lock_file in scan_dir.glob("*.lock"):
            _process_lock_file(
                lock_file, resolved_cwd, results,
            )

    # Sort by longest matching workspace prefix (best match first)
    results.sort(
        key=lambda i: max(
            (
                len(str(_resolve_workspace_folder(f)))
                for f in i.workspace_folders
                if resolved_cwd.is_relative_to(
                    _resolve_workspace_folder(f)
                )
            ),
            default=0,
        ),
        reverse=True,
    )
    return results


def _process_lock_file(
    lock_file: Path,
    resolved_cwd: Path,
    results: list[IDEInfo],
) -> None:
    """Parse and validate a single lock file."""
    try:
        port = int(lock_file.stem)
    except ValueError:
        return

    try:
        data = json.loads(lock_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return

    pid = data.get("pid", 0)
    if not _is_pid_alive(pid):
        try:
            lock_file.unlink()
        except OSError:
            pass
        return

    folders = data.get("workspaceFolders", [])
    if not any(
        resolved_cwd.is_relative_to(_resolve_workspace_folder(f))
        for f in folders
    ):
        return

    results.append(IDEInfo(
        pid=pid,
        workspace_folders=folders,
        ide_name=data.get("ideName", "Unknown"),
        transport=data.get("transport", "ws"),
        auth_token=data.get("authToken", ""),
        port=port,
        lock_path=lock_file,
    ))


def _is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        if not _IS_WSL:
            return False
        # On WSL, Windows PIDs aren't in /proc — check via interop
        return _is_windows_pid_alive(pid)
    except PermissionError:
        return True  # Exists but different user
    except OSError:
        if not _IS_WSL:
            return False
        return _is_windows_pid_alive(pid)


def _is_windows_pid_alive(pid: int) -> bool:
    """Check if a Windows process is alive from WSL via interop."""
    if not shutil.which("powershell.exe"):
        # Can't verify — assume alive to avoid false stale cleanup
        return True
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             f"Get-Process -Id {pid} -ErrorAction Stop"],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return True  # Can't verify — assume alive
