"""Shared external-editor preview helpers for REPL-only UI flows."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def is_wsl() -> bool:
    """Detect if running in Windows Subsystem for Linux."""
    try:
        with open("/proc/version") as f:
            return "microsoft" in f.read().lower()
    except (FileNotFoundError, PermissionError):
        return False


def get_system_editor() -> list[str]:
    """Get the appropriate editor command for the current platform."""
    for env in ("VISUAL", "EDITOR"):
        if editor := os.environ.get(env):
            return [editor]

    if sys.platform == "win32" or is_wsl():
        return ["notepad.exe"]

    for cmd in ("less", "more", "cat"):
        if shutil.which(cmd):
            return [cmd]

    return ["cat"]


def open_in_editor(content: str, title: str) -> bool:
    """Open text content in an external editor or pager."""
    temp_dir = Path.home() / ".nexus3" / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(suffix=".txt", prefix="nexus_tool_", dir=temp_dir)
    try:
        editor_cmd = get_system_editor()
        running_in_wsl = is_wsl()
        is_pager = editor_cmd[0] in ("less", "more", "cat")

        with os.fdopen(fd, "w", encoding="utf-8") as f:
            if is_pager:
                f.write("Navigation: q=quit  Space=next page  b=back  /=search\n")
                f.write("-" * 50 + "\n\n")
            f.write(f"=== {title} ===\n\n{content}\n")

        if sys.platform == "win32":
            subprocess.Popen(
                editor_cmd + [tmp_path],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            time.sleep(0.5)
        elif running_in_wsl and "notepad" in editor_cmd[0].lower():
            subprocess.Popen(editor_cmd + [tmp_path])
            time.sleep(0.5)
        else:
            subprocess.run(editor_cmd + [tmp_path])

        return True
    except Exception:
        return False
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
