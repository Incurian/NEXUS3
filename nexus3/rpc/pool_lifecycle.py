"""Lifecycle helpers extracted from ``AgentPool`` for future wiring.

This module preserves current pool lifecycle behavior while exposing
dependency-injected helpers for incremental integration.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, MutableMapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, TypeVar

from nexus3.core.authorization_kernel import (
    AdapterAuthorizationKernel,
    AuthorizationAction,
    AuthorizationDecision,
    AuthorizationRequest,
    AuthorizationResource,
    AuthorizationResourceType,
)
from nexus3.core.capabilities import (
    CapabilityClaims,
    CapabilitySigner,
    InMemoryCapabilityRevocationStore,
    direct_rpc_scope_for_method,
)
from nexus3.core.permissions import AgentPermissions

AgentT = TypeVar("AgentT", bound="AgentLike")
DestroyUnlockedFn = Callable[[str, str | None, bool], Awaitable[bool]]


class _DestroyAuthorizationAdapter:
    """Kernel adapter mirroring legacy AgentPool.destroy authorization checks."""

    def authorize(self, request: AuthorizationRequest) -> AuthorizationDecision | None:
        if request.action != AuthorizationAction.AGENT_DESTROY:
            return None
        if request.resource.resource_type != AuthorizationResourceType.AGENT:
            return None

        requester_id = request.principal_id
        target_agent_id = request.resource.identifier
        target_parent_agent_id = request.context.get("target_parent_agent_id")
        admin_override = request.context.get("admin_override")

        if admin_override is True:
            return AuthorizationDecision.allow(request, reason="admin_override")
        if requester_id == "external":
            return AuthorizationDecision.allow(request, reason="external_requester")

        if requester_id == target_agent_id:
            return AuthorizationDecision.allow(request, reason="self_destroy")
        if isinstance(target_parent_agent_id, str) and target_parent_agent_id == requester_id:
            return AuthorizationDecision.allow(request, reason="parent_destroy")
        return AuthorizationDecision.deny(request, reason="not_parent_or_self")


class ServicesLike(Protocol):
    """Minimal service-container contract used by lifecycle helpers."""

    def get_permissions(self) -> AgentPermissions | None:
        """Return effective permissions service payload."""

    def get_child_agent_ids(self) -> set[str] | None:
        """Return tracked child IDs if present."""

    def set_child_agent_ids(self, child_ids: set[str] | None) -> None:
        """Persist tracked child IDs."""

    def get_model(self) -> Any:
        """Return resolved model object if present."""

    def has(self, key: str) -> bool:
        """Return whether a service key exists."""

    def get_cwd(self) -> Any:
        """Return cwd service value if present."""

    def get(self, key: str) -> Any:
        """Generic service lookup."""


class DispatcherLike(Protocol):
    """Minimal dispatcher contract used by lifecycle helpers."""

    should_shutdown: bool

    async def cancel_all_requests(self) -> None:
        """Cancel active requests prior to teardown."""


class LoggerLike(Protocol):
    """Minimal logger contract used by lifecycle helpers."""

    def close(self) -> None:
        """Flush and close logger resources."""


class ContextLike(Protocol):
    """Minimal context contract used by lifecycle list helper."""

    @property
    def messages(self) -> list[Any]:
        """Return conversation messages."""


class SessionLike(Protocol):
    """Minimal session contract used by lifecycle list helper."""

    halted_at_iteration_limit: bool
    last_action_at: datetime | None


class AgentLike(Protocol):
    """Minimal Agent shape used by lifecycle helpers."""

    agent_id: str
    created_at: datetime
    repl_connected: bool
    services: ServicesLike
    dispatcher: DispatcherLike
    logger: LoggerLike
    context: ContextLike
    session: SessionLike


@dataclass
class CapabilityLifecycleState:
    """Mutable capability lifecycle state used by helper functions."""

    signer: CapabilitySigner
    revocation_store: InMemoryCapabilityRevocationStore
    issued_token_ids_by_subject: MutableMapping[str, set[str]]
    issued_token_ids_by_issuer: MutableMapping[str, set[str]]
    default_ttl_seconds: int = 300


class AuthorizationError(Exception):
    """Raised when lifecycle authorization denies an operation."""


def track_issued_capability(
    *,
    state: CapabilityLifecycleState,
    claims: CapabilityClaims,
) -> None:
    """Track issued token IDs by subject and issuer."""
    state.issued_token_ids_by_subject.setdefault(
        claims.subject_id,
        set(),
    ).add(claims.token_id)
    state.issued_token_ids_by_issuer.setdefault(
        claims.issuer_id,
        set(),
    ).add(claims.token_id)


def revoke_capabilities_for_agent(
    *,
    state: CapabilityLifecycleState,
    agent_id: str,
) -> None:
    """Revoke all tracked capabilities for an agent (subject and issuer)."""
    token_ids: set[str] = set()
    token_ids.update(
        state.issued_token_ids_by_subject.pop(agent_id, set())
    )
    token_ids.update(
        state.issued_token_ids_by_issuer.pop(agent_id, set())
    )
    if not token_ids:
        return

    for token_id in token_ids:
        state.revocation_store.revoke(token_id)

    for mapping in (
        state.issued_token_ids_by_subject,
        state.issued_token_ids_by_issuer,
    ):
        stale_keys: list[str] = []
        for principal_id, tracked in mapping.items():
            tracked.difference_update(token_ids)
            if not tracked:
                stale_keys.append(principal_id)
        for principal_id in stale_keys:
            mapping.pop(principal_id, None)


def issue_direct_capability(
    *,
    state: CapabilityLifecycleState,
    issuer_id: str,
    subject_id: str,
    rpc_method: str,
    ttl_seconds: int | None = None,
) -> str:
    """Issue and track a direct in-process capability token."""
    required_scope = direct_rpc_scope_for_method(rpc_method)
    if required_scope is None:
        raise ValueError(f"Unsupported direct capability method: {rpc_method}")
    if not issuer_id:
        raise ValueError("issuer_id must be non-empty")
    if not subject_id:
        raise ValueError("subject_id must be non-empty")

    token = state.signer.issue(
        issuer_id=issuer_id,
        subject_id=subject_id,
        scopes=(required_scope,),
        ttl_seconds=ttl_seconds or state.default_ttl_seconds,
    )
    claims = state.signer.verify(token)
    track_issued_capability(state=state, claims=claims)
    return token


def verify_direct_capability(
    *,
    state: CapabilityLifecycleState,
    token: str,
    required_scope: str,
) -> CapabilityClaims:
    """Verify a direct capability token with revocation checks."""
    return state.signer.verify(
        token,
        required_scopes=(required_scope,),
        revocation_store=state.revocation_store,
    )


def authorize_destroy(
    *,
    destroy_authorization_kernel: AdapterAuthorizationKernel,
    agent_id: str,
    requester_id: str | None,
    admin_override: bool,
    target_permissions: AgentPermissions | None,
) -> str:
    """Authorize a destroy request and return effective principal ID."""
    destroy_principal_id = requester_id or "external"
    kernel_request = AuthorizationRequest(
        action=AuthorizationAction.AGENT_DESTROY,
        resource=AuthorizationResource(
            resource_type=AuthorizationResourceType.AGENT,
            identifier=agent_id,
        ),
        principal_id=destroy_principal_id,
        context={
            "target_parent_agent_id": (
                target_permissions.parent_agent_id
                if target_permissions is not None
                else None
            ),
            "admin_override": admin_override,
        },
    )
    kernel_decision = destroy_authorization_kernel.authorize(kernel_request)
    if not kernel_decision.allowed:
        raise AuthorizationError(
            f"Agent '{destroy_principal_id}' is not authorized to destroy '{agent_id}'"
        )
    return destroy_principal_id


async def destroy_unlocked(
    *,
    agents: MutableMapping[str, AgentT],
    destroy_authorization_kernel: AdapterAuthorizationKernel,
    revoke_capabilities_for_agent_fn: Callable[[str], None],
    unregister_log_multiplexer_agent_fn: Callable[[str], None],
    agent_id: str,
    requester_id: str | None = None,
    admin_override: bool = False,
) -> bool:
    """Destroy path internals equivalent to ``AgentPool.destroy`` (lock held)."""
    if agent_id not in agents:
        return False

    agent = agents[agent_id]
    target_permissions = agent.services.get_permissions()
    authorize_destroy(
        destroy_authorization_kernel=destroy_authorization_kernel,
        agent_id=agent_id,
        requester_id=requester_id,
        admin_override=admin_override,
        target_permissions=target_permissions,
    )

    revoke_capabilities_for_agent_fn(agent_id)

    agents.pop(agent_id)

    permissions = agent.services.get_permissions()
    if permissions and permissions.parent_agent_id:
        parent = agents.get(permissions.parent_agent_id)
        if parent:
            child_ids = parent.services.get_child_agent_ids()
            if child_ids and agent_id in child_ids:
                updated_child_ids = set(child_ids)
                updated_child_ids.discard(agent_id)
                parent.services.set_child_agent_ids(updated_child_ids)

    await agent.dispatcher.cancel_all_requests()
    unregister_log_multiplexer_agent_fn(agent_id)

    clipboard_manager = agent.services.get("clipboard_manager")
    if clipboard_manager:
        clipboard_manager.close()

    agent.logger.close()
    return True


async def destroy(
    *,
    lock: asyncio.Lock,
    destroy_unlocked_fn: DestroyUnlockedFn,
    agent_id: str,
    requester_id: str | None = None,
    admin_override: bool = False,
) -> bool:
    """Lock wrapper corresponding to ``AgentPool.destroy``."""
    async with lock:
        return await destroy_unlocked_fn(agent_id, requester_id, admin_override)


def get_agent(*, agents: MutableMapping[str, AgentT], agent_id: str) -> AgentT | None:
    """Accessor helper corresponding to ``AgentPool.get``."""
    return agents.get(agent_id)


def get_children(*, agents: MutableMapping[str, AgentT], agent_id: str) -> list[str]:
    """Accessor helper corresponding to ``AgentPool.get_children``."""
    agent = agents.get(agent_id)
    if agent is None:
        return []
    child_ids = agent.services.get_child_agent_ids()
    return list(child_ids) if child_ids else []


def list_agents(
    *,
    agents: MutableMapping[str, AgentT],
    is_temp_agent_fn: Callable[[str], bool],
) -> list[dict[str, Any]]:
    """Accessor helper corresponding to ``AgentPool.list``."""
    result: list[dict[str, Any]] = []
    for agent in agents.values():
        permissions = agent.services.get_permissions()
        child_ids = agent.services.get_child_agent_ids()
        resolved_model = agent.services.get_model()
        cwd = agent.services.get_cwd() if agent.services.has("cwd") else None

        write_paths: list[str] | None = None
        if permissions:
            write_file_perm = permissions.tool_permissions.get("write_file")
            if write_file_perm and write_file_perm.allowed_paths is not None:
                write_paths = [str(p) for p in write_file_perm.allowed_paths]

        result.append(
            {
                "agent_id": agent.agent_id,
                "is_temp": is_temp_agent_fn(agent.agent_id),
                "created_at": agent.created_at.isoformat(),
                "message_count": len(agent.context.messages),
                "should_shutdown": agent.dispatcher.should_shutdown,
                "parent_agent_id": permissions.parent_agent_id if permissions else None,
                "child_count": len(child_ids) if child_ids else 0,
                "halted_at_iteration_limit": agent.session.halted_at_iteration_limit,
                "model": resolved_model.alias if resolved_model else None,
                "last_action_at": (
                    agent.session.last_action_at.isoformat()
                    if agent.session.last_action_at
                    else None
                ),
                "permission_level": (
                    permissions.effective_policy.level.name if permissions else None
                ),
                "cwd": str(cwd) if cwd else None,
                "write_paths": write_paths,
            }
        )
    return result


def set_repl_connected(
    *,
    agents: MutableMapping[str, AgentT],
    agent_id: str,
    connected: bool,
) -> None:
    """Accessor helper corresponding to ``AgentPool.set_repl_connected``."""
    agent = agents.get(agent_id)
    if agent:
        agent.repl_connected = connected


def is_repl_connected(
    *,
    agents: MutableMapping[str, AgentT],
    agent_id: str,
) -> bool:
    """Accessor helper corresponding to ``AgentPool.is_repl_connected``."""
    agent = agents.get(agent_id)
    return agent.repl_connected if agent else False


def should_shutdown(*, agents: MutableMapping[str, AgentT]) -> bool:
    """Accessor helper corresponding to ``AgentPool.should_shutdown``."""
    if not agents:
        return False
    return all(agent.dispatcher.should_shutdown for agent in agents.values())


def pool_len(*, agents: MutableMapping[str, AgentT]) -> int:
    """Accessor helper corresponding to ``AgentPool.__len__``."""
    return len(agents)


def pool_contains(*, agents: MutableMapping[str, AgentT], agent_id: str) -> bool:
    """Accessor helper corresponding to ``AgentPool.__contains__``."""
    return agent_id in agents


__all__ = [
    "AuthorizationError",
    "CapabilityLifecycleState",
    "_DestroyAuthorizationAdapter",
    "authorize_destroy",
    "destroy",
    "destroy_unlocked",
    "get_agent",
    "get_children",
    "is_repl_connected",
    "issue_direct_capability",
    "list_agents",
    "pool_contains",
    "pool_len",
    "revoke_capabilities_for_agent",
    "set_repl_connected",
    "should_shutdown",
    "track_issued_capability",
    "verify_direct_capability",
]

