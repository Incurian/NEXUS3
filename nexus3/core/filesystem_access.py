"""Filesystem access gateway for multi-file skill operations.

This module provides a minimal, shared layer for per-entry authorization checks
using PathDecisionEngine with ServiceContainer-aware path configuration.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING

from nexus3.core.path_decision import PathDecision, PathDecisionEngine

if TYPE_CHECKING:
    from nexus3.skill.services import ServiceContainer


class FilesystemAccessGateway:
    """ServiceContainer-aware gateway for filesystem access decisions."""

    def __init__(self, services: ServiceContainer, tool_name: str | None = None) -> None:
        """Initialize gateway for a specific tool context."""
        self._engine = PathDecisionEngine.from_services(services, tool_name=tool_name)

    def decide_path(
        self,
        path: str | Path,
        *,
        must_exist: bool = False,
        must_be_dir: bool = False,
    ) -> PathDecision:
        """Get a path decision for a single path."""
        return self._engine.check_access(
            path,
            must_exist=must_exist,
            must_be_dir=must_be_dir,
        )

    def iter_authorized_paths(
        self,
        candidates: Iterable[Path],
        *,
        must_exist: bool = False,
        must_be_dir: bool = False,
        return_resolved: bool = False,
    ) -> Iterator[Path]:
        """Yield candidate paths that pass authorization checks.

        Args:
            candidates: Candidate file paths to evaluate.
            must_exist: Require candidate to exist.
            must_be_dir: Require candidate to be a directory.
            return_resolved: Yield resolved paths instead of original candidates.
        """
        for candidate in candidates:
            decision = self.decide_path(
                candidate,
                must_exist=must_exist,
                must_be_dir=must_be_dir,
            )
            if not decision.allowed:
                continue
            if return_resolved:
                assert decision.resolved_path is not None
                yield decision.resolved_path
            else:
                yield candidate
