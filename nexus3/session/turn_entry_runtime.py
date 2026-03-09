"""Turn-entry preflight runtime helpers extracted from Session."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from nexus3.context.manager import ContextManager
    from nexus3.skill.registry import SkillRegistry


class _TurnEntrySession(Protocol):
    context: ContextManager | None
    registry: SkillRegistry | None
    _halted_at_iteration_limit: bool
    _last_iteration_count: int

    def _flush_cancelled_tools(self) -> None: ...

    def _normalize_context_preflight(self, *, path: str) -> None: ...


def prepare_turn_entry(
    session: _TurnEntrySession,
    *,
    user_input: str,
    user_meta: dict[str, Any] | None,
    preflight_path: str,
) -> bool:
    """Run shared context-mode turn-entry preflight for send()/run_turn()."""
    context = session.context
    if context is None:
        raise RuntimeError("prepare_turn_entry() requires context mode")

    session._flush_cancelled_tools()
    session._normalize_context_preflight(path=preflight_path)

    session._halted_at_iteration_limit = False
    session._last_iteration_count = 0

    context.add_user_message(user_input, meta=user_meta)

    return session.registry is not None and bool(session.registry.get_definitions())
