"""Compaction runtime helpers extracted from Session."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from nexus3.context.compaction import build_summarize_prompt
from nexus3.core.interfaces import AsyncProvider
from nexus3.core.types import Message, Role
from nexus3.session.http_logging import clear_current_logger, set_current_logger

if TYPE_CHECKING:
    from nexus3.config.schema import CompactionConfig, Config
    from nexus3.session.logging import SessionLogger


class _CompactionRuntimeSession(Protocol):
    """Session shape required by compaction runtime helpers."""

    provider: AsyncProvider
    logger: SessionLogger | None
    _config: Config | None
    _compaction_provider: AsyncProvider | None


def get_compaction_provider(session: _CompactionRuntimeSession) -> AsyncProvider:
    """Get or create the provider used for compaction summaries."""
    if session._compaction_provider is not None:
        return session._compaction_provider

    if session._config is None:
        return session.provider

    compaction_model = session._config.compaction.model
    if compaction_model is None:
        return session.provider

    # Lazy import preserves startup behavior and avoids eager provider imports.
    from nexus3.provider import create_provider

    resolved = session._config.resolve_model(compaction_model)
    provider_config = session._config.get_provider_config(resolved.provider_name)
    session._compaction_provider = create_provider(provider_config, resolved.model_id)
    return session._compaction_provider


async def generate_summary(
    session: _CompactionRuntimeSession,
    messages: list[Message],
    compaction_config: CompactionConfig,
) -> str:
    """Generate a compaction summary using the configured provider."""
    prompt = build_summarize_prompt(messages)
    summary_messages = [Message(role=Role.USER, content=prompt)]

    # Keep logger lifecycle identical to Session-local implementation.
    if session.logger:
        set_current_logger(session.logger)

    try:
        provider = get_compaction_provider(session)
        response = await provider.complete(summary_messages, tools=None)
        return response.content
    finally:
        clear_current_logger()
