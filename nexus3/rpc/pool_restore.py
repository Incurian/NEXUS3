"""Dependency-injected restore helpers extracted from ``AgentPool``.

This module mirrors the restore semantics currently implemented in
``nexus3.rpc.pool.AgentPool`` while keeping wiring external. The helpers are
not coupled to pool internals beyond explicit dependencies passed by the caller.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, MutableMapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Generic, Protocol, TypeVar

from nexus3.clipboard import CLIPBOARD_PRESETS, ClipboardManager
from nexus3.context import ContextConfig, ContextLoader, ContextManager
from nexus3.core.permissions import (
    AgentPermissions,
    PermissionDelta,
    PermissionLevel,
    PermissionPreset,
    ToolPermission,
    resolve_preset,
)
from nexus3.mcp.registry import MCPServerRegistry
from nexus3.rpc.dispatcher import Dispatcher
from nexus3.rpc.log_multiplexer import LogMultiplexer
from nexus3.rpc.pool_visibility import _convert_gitlab_config
from nexus3.session import LogConfig, LogStream, SavedSession, Session, SessionLogger
from nexus3.session.persistence import deserialize_clipboard_entries, deserialize_messages
from nexus3.skill import ServiceContainer, SkillRegistry
from nexus3.skill.vcs import register_vcs_skills

AgentT = TypeVar("AgentT")
AgentCo = TypeVar("AgentCo", covariant=True)

if TYPE_CHECKING:
    from nexus3.config.schema import Config
    from nexus3.provider.registry import ProviderRegistry


class SessionManagerLike(Protocol):
    """Session-manager contract needed for get-or-restore."""

    def session_exists(self, agent_id: str) -> bool:
        """Return whether a saved session exists for the given agent ID."""

    def load_session(self, agent_id: str) -> SavedSession:
        """Load the saved session for the given agent ID."""


class AgentFactory(Protocol[AgentCo]):
    """Factory used to construct final restored Agent instances."""

    def __call__(
        self,
        *,
        agent_id: str,
        logger: SessionLogger,
        context: ContextManager,
        services: ServiceContainer,
        registry: SkillRegistry,
        session: Session,
        dispatcher: Dispatcher,
        created_at: datetime | None = None,
    ) -> AgentCo:
        """Construct an agent value from restored runtime components."""


class AgentIdValidator(Protocol):
    """Validation callback for restored agent IDs."""

    def __call__(self, agent_id: str) -> None:
        """Validate an agent ID, raising ``ValueError`` on invalid values."""


class VisibilityChecker(Protocol):
    """Visibility-check callback for MCP/GitLab restore paths."""

    def __call__(
        self,
        *,
        agent_id: str,
        permissions: AgentPermissions,
        check_stage: str,
    ) -> bool:
        """Return whether integration/tool visibility is allowed."""


class ProviderGetter(Protocol):
    """Provider-lookup helper for resolved model payloads."""

    def __call__(
        self,
        *,
        provider_name: str,
        model_id: str,
        reasoning: bool,
    ) -> Any:
        """Return provider instance for resolved model metadata."""


class RegisterVcsSkillsFn(Protocol):
    """Callable contract for VCS-skill registration."""

    def __call__(
        self,
        registry: SkillRegistry,
        services: ServiceContainer,
        permissions: AgentPermissions | None,
        *,
        gitlab_visible: bool | None = None,
    ) -> int:
        """Register VCS skills for a restored agent."""


class LoggerFactory(Protocol):
    """Session-logger factory used by restore internals."""

    def __call__(
        self,
        *,
        agent_id: str,
        base_log_dir: Path,
        log_streams: LogStream,
        log_multiplexer: LogMultiplexer,
    ) -> SessionLogger:
        """Build a logger and register any raw callback routing."""


@dataclass(frozen=True)
class RestoreSharedDeps:
    """Shared dependencies required by restore internals."""

    config: Config
    provider_registry: ProviderRegistry
    base_log_dir: Path
    context_loader: ContextLoader
    log_streams: LogStream
    custom_presets: dict[str, PermissionPreset]
    mcp_registry: MCPServerRegistry
    is_repl: bool = False


@dataclass
class RestoreRuntimeDeps(Generic[AgentT]):
    """Runtime dependencies/state required by restore internals."""

    agents: MutableMapping[str, AgentT]
    lock: asyncio.Lock
    log_multiplexer: LogMultiplexer
    pool_ref: Any
    global_dispatcher: Any | None
    validate_agent_id: AgentIdValidator
    is_mcp_visible_for_agent: VisibilityChecker
    is_gitlab_visible_for_agent: VisibilityChecker
    agent_factory: AgentFactory[AgentT]
    logger_factory: LoggerFactory
    provider_getter: ProviderGetter | None = None
    register_vcs_skills_fn: RegisterVcsSkillsFn | None = None


def default_logger_factory(
    *,
    agent_id: str,
    base_log_dir: Path,
    log_streams: LogStream,
    log_multiplexer: LogMultiplexer,
) -> SessionLogger:
    """Default logger factory preserving AgentPool restore behavior."""
    agent_log_dir = base_log_dir / agent_id
    log_config = LogConfig(base_dir=agent_log_dir, streams=log_streams, mode="agent")
    logger = SessionLogger(log_config)

    raw_callback = logger.get_raw_log_callback()
    if raw_callback is not None:
        log_multiplexer.register(agent_id, raw_callback)
    return logger


def _resolve_provider_getter(
    shared: RestoreSharedDeps,
    runtime: RestoreRuntimeDeps[Any],
) -> ProviderGetter:
    """Resolve provider getter, defaulting to the shared provider registry."""
    if runtime.provider_getter is not None:
        return runtime.provider_getter

    def _provider_getter(
        *,
        provider_name: str,
        model_id: str,
        reasoning: bool,
    ) -> Any:
        return shared.provider_registry.get(provider_name, model_id, reasoning)

    return _provider_getter


async def get_or_restore(
    *,
    agent_id: str,
    session_manager: SessionManagerLike | None,
    runtime: RestoreRuntimeDeps[AgentT],
    restore_unlocked: Callable[[SavedSession], Awaitable[AgentT]],
) -> AgentT | None:
    """Get an active agent or restore from persistence atomically."""
    async with runtime.lock:
        existing = runtime.agents.get(agent_id)
        if existing is not None:
            return existing

        if session_manager is not None and session_manager.session_exists(agent_id):
            saved = session_manager.load_session(agent_id)
            return await restore_unlocked(saved)

        return None


async def _restore_unlocked(
    *,
    saved: SavedSession,
    shared: RestoreSharedDeps,
    runtime: RestoreRuntimeDeps[AgentT],
) -> AgentT:
    """Restore internals equivalent to ``AgentPool._restore_unlocked``."""
    agent_id = saved.agent_id

    # Preserve AgentPool validation + defense-in-depth duplicate check semantics.
    runtime.validate_agent_id(agent_id)
    if agent_id in runtime.agents:
        raise ValueError(f"Agent already exists: {agent_id}")

    logger = runtime.logger_factory(
        agent_id=agent_id,
        base_log_dir=shared.base_log_dir,
        log_streams=shared.log_streams,
        log_multiplexer=runtime.log_multiplexer,
    )

    system_prompt = saved.system_prompt
    resolved_model = shared.config.resolve_model(saved.model_alias)

    from nexus3.skill.builtin import register_builtin_skills

    services = ServiceContainer()

    preset_name = saved.permission_preset or shared.config.permissions.default_preset
    try:
        permissions = resolve_preset(preset_name, shared.custom_presets)
    except ValueError:
        permissions = resolve_preset("sandboxed", shared.custom_presets)

    if saved.disabled_tools:
        delta = PermissionDelta(disable_tools=saved.disabled_tools)
        permissions = permissions.apply_delta(delta)

    services.register("agent_id", agent_id)
    services.set_permissions(permissions)
    services.register("mcp_registry", shared.mcp_registry)
    services.set_model(resolved_model)

    agent_cwd = Path(saved.working_directory) if saved.working_directory else Path.cwd()
    services.set_cwd(agent_cwd)

    permission_level = permissions.effective_policy.level
    if permission_level == PermissionLevel.YOLO:
        clipboard_perms = CLIPBOARD_PRESETS["yolo"]
    elif permission_level == PermissionLevel.TRUSTED:
        clipboard_perms = CLIPBOARD_PRESETS["trusted"]
    else:
        clipboard_perms = CLIPBOARD_PRESETS["sandboxed"]

    clipboard_manager = ClipboardManager(
        agent_id=agent_id,
        cwd=agent_cwd,
        permissions=clipboard_perms,
    )
    services.register("clipboard_manager", clipboard_manager)

    if saved.clipboard_agent_entries:
        entries = deserialize_clipboard_entries(saved.clipboard_agent_entries)
        clipboard_manager.restore_agent_entries(entries)

    context_config = ContextConfig(max_tokens=resolved_model.context_window)
    context = ContextManager(
        config=context_config,
        logger=logger,
        agent_id=agent_id,
        clipboard_manager=clipboard_manager,
        clipboard_config=shared.config.clipboard,
    )
    context.set_system_prompt(system_prompt)

    messages = deserialize_messages(saved.messages)
    for msg in messages:
        context._messages.append(msg)

    context.refresh_git_context(agent_cwd)

    gitlab_config = _convert_gitlab_config(shared.config)
    if gitlab_config:
        services.register("gitlab_config", gitlab_config)

    if runtime.global_dispatcher is not None:
        from nexus3.rpc.agent_api import DirectAgentAPI

        agent_api = DirectAgentAPI(
            runtime.pool_ref,
            runtime.global_dispatcher,
            requester_id=agent_id,
        )
        services.register("agent_api", agent_api)

    registry = SkillRegistry(services)
    register_builtin_skills(registry)

    register_vcs = runtime.register_vcs_skills_fn or register_vcs_skills
    register_vcs(
        registry,
        services,
        permissions,
        gitlab_visible=runtime.is_gitlab_visible_for_agent(
            agent_id=agent_id,
            permissions=permissions,
            check_stage="restore",
        ),
    )

    for skill_name in list(registry._specs):
        if skill_name.startswith("gitlab_") and skill_name not in permissions.tool_permissions:
            permissions.tool_permissions[skill_name] = ToolPermission(enabled=False)

    tool_defs = registry.get_definitions_for_permissions(permissions)

    if runtime.is_mcp_visible_for_agent(
        agent_id=agent_id,
        permissions=permissions,
        check_stage="restore",
    ):
        for mcp_skill in await shared.mcp_registry.get_all_skills(agent_id=agent_id):
            tool_perm = permissions.tool_permissions.get(mcp_skill.name)
            if tool_perm is not None and not tool_perm.enabled:
                continue
            tool_defs.append(
                {
                    "type": "function",
                    "function": {
                        "name": mcp_skill.name,
                        "description": mcp_skill.description,
                        "parameters": mcp_skill.parameters,
                    },
                }
            )

    context.set_tool_definitions(tool_defs)

    provider_getter = _resolve_provider_getter(shared, runtime)
    provider = provider_getter(
        provider_name=resolved_model.provider_name,
        model_id=resolved_model.model_id,
        reasoning=resolved_model.reasoning,
    )

    session = Session(
        provider,
        context=context,
        logger=logger,
        registry=registry,
        skill_timeout=shared.config.skill_timeout,
        max_concurrent_tools=shared.config.max_concurrent_tools,
        services=services,
        config=shared.config,
        context_loader=shared.context_loader,
        is_repl=shared.is_repl,
    )

    dispatcher = Dispatcher(
        session,
        context=context,
        agent_id=agent_id,
        log_multiplexer=runtime.log_multiplexer,
        pool=runtime.pool_ref,
    )

    agent = runtime.agent_factory(
        agent_id=agent_id,
        logger=logger,
        context=context,
        services=services,
        registry=registry,
        session=session,
        dispatcher=dispatcher,
        created_at=saved.created_at,
    )

    runtime.agents[agent_id] = agent
    return agent


async def restore_from_saved(
    *,
    saved: SavedSession,
    runtime: RestoreRuntimeDeps[AgentT],
    restore_unlocked: Callable[[SavedSession], Awaitable[AgentT]],
) -> AgentT:
    """Restore a saved agent while holding the pool lock."""
    async with runtime.lock:
        return await restore_unlocked(saved)


__all__ = [
    "RestoreRuntimeDeps",
    "RestoreSharedDeps",
    "SessionManagerLike",
    "_restore_unlocked",
    "default_logger_factory",
    "get_or_restore",
    "restore_from_saved",
]
