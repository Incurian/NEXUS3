"""Helpers for resolving optional external tool executables."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from nexus3.config.schema import SearchConfig


@dataclass(frozen=True)
class ExternalToolResolution:
    """Resolution result for an optional external executable."""

    executable: str | None
    source: str | None = None
    reason: str | None = None

    @property
    def available(self) -> bool:
        """Return True when a usable executable path was resolved."""
        return self.executable is not None


def resolve_ripgrep(search_config: SearchConfig | None) -> ExternalToolResolution:
    """Resolve the ripgrep executable according to config and host state."""
    if search_config is not None and search_config.ripgrep_path:
        configured = Path(search_config.ripgrep_path)
        if configured.is_file():
            return ExternalToolResolution(
                executable=str(configured),
                source="config",
            )
        return ExternalToolResolution(
            executable=None,
            reason=(
                "Configured ripgrep_path does not exist or is not a file: "
                f"{search_config.ripgrep_path}"
            ),
        )

    resolved = shutil.which("rg")
    if resolved:
        return ExternalToolResolution(
            executable=resolved,
            source="PATH",
        )

    return ExternalToolResolution(
        executable=None,
        reason="ripgrep executable 'rg' was not found on PATH",
    )
