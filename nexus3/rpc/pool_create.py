"""Create-path helpers extracted from AgentPool for future wiring.

This module intentionally keeps helper APIs dependency-injected so `pool.py`
can adopt them incrementally without changing shared runtime wiring in this
slice.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, Protocol, TypeVar, cast

from nexus3.config.schema import ResolvedModel
from nexus3.core.authorization_kernel import (
    AdapterAuthorizationKernel,
    AuthorizationAction,
    AuthorizationDecision,
    AuthorizationRequest,
    AuthorizationResource,
    AuthorizationResourceType,
    CreateAuthorizationContext,
    CreateAuthorizationStage,
)
from nexus3.core.permissions import (
    AgentPermissions,
    PermissionDelta,
    PermissionPreset,
    resolve_preset,
)

MAX_AGENT_DEPTH = 5
logger = logging.getLogger(__name__)

AgentT = TypeVar("AgentT")
ConfigT = TypeVar("ConfigT", bound="AgentConfigLike")
CreateUnlockedFn = Callable[[str | None, ConfigT | None, str | None], Awaitable[AgentT]]
ParentPermissionsReader = Callable[[AgentT], AgentPermissions | None]
TempIdGenerator = Callable[[set[str]], str]
TempConfigBuilder = Callable[[ConfigT | None, str], ConfigT]


class AgentConfigLike(Protocol):
    """Minimal AgentConfig shape required by create-path helpers."""

    agent_id: str | None
    system_prompt: str | None
    preset: str | None
    cwd: Path | None
    delta: PermissionDelta | None
    parent_permissions: AgentPermissions | None
    parent_agent_id: str | None
    model: str | None


class PermissionsConfigLike(Protocol):
    """Minimal config.permissions shape required by create-path helpers."""

    default_preset: str


class ConfigResolverLike(Protocol):
    """Minimal Config shape required by create-path helpers."""

    permissions: PermissionsConfigLike

    def resolve_model(self, alias: str | None = None) -> ResolvedModel:
        ...


@dataclass(frozen=True)
class PreparedCreateInputs(Generic[ConfigT]):
    """Prepared create-stage runtime inputs for post-policy wiring."""

    effective_id: str
    effective_config: ConfigT
    agent_log_dir: Path
    preset_name: str
    permissions: AgentPermissions
    resolved_model: ResolvedModel
    parent_permissions: AgentPermissions | None
    requester_id: str


class _CreateAuthorizationAdapter:
    """Kernel adapter mirroring legacy AgentPool.create parent ceiling checks."""

    @staticmethod
    def _deserialize_permissions(payload_json: str | None) -> AgentPermissions | None:
        if not isinstance(payload_json, str):
            return None
        try:
            raw_payload = json.loads(payload_json)
        except json.JSONDecodeError:
            return None
        if not isinstance(raw_payload, dict):
            return None
        try:
            typed_payload = cast(dict[str, Any], raw_payload)
            return AgentPermissions.from_dict(typed_payload)
        except (KeyError, TypeError, ValueError):
            return None

    def _evaluate_parent_ceiling(self, create_context: CreateAuthorizationContext) -> bool | None:
        parent_permissions = self._deserialize_permissions(
            create_context.parent_permissions_json
        )
        requested_permissions = self._deserialize_permissions(
            create_context.requested_permissions_json
        )
        if parent_permissions is None or requested_permissions is None:
            return None
        return parent_permissions.can_grant(requested_permissions)

    def authorize(self, request: AuthorizationRequest) -> AuthorizationDecision | None:
        if request.action != AuthorizationAction.AGENT_CREATE:
            return None
        if request.resource.resource_type != AuthorizationResourceType.AGENT:
            return None

        create_context = CreateAuthorizationContext.from_context_map(request.context)
        if create_context is None:
            return AuthorizationDecision.deny(request, reason="invalid_create_context")

        check_stage = create_context.check_stage
        if check_stage == CreateAuthorizationStage.LIFECYCLE_ENTRY:
            return AuthorizationDecision.allow(request, reason="create_lifecycle_entry")

        if check_stage == CreateAuthorizationStage.MAX_DEPTH:
            if create_context.parent_depth >= create_context.max_depth:
                return AuthorizationDecision.deny(
                    request,
                    reason="max_depth_exceeded",
                )
            return AuthorizationDecision.allow(request, reason="within_max_depth")

        if check_stage == CreateAuthorizationStage.BASE_CEILING:
            parent_can_grant = self._evaluate_parent_ceiling(create_context)
            if parent_can_grant is None:
                return AuthorizationDecision.deny(request, reason="invalid_create_context")
            if parent_can_grant is True:
                return AuthorizationDecision.allow(
                    request,
                    reason="base_preset_within_parent_ceiling",
                )
            return AuthorizationDecision.deny(
                request,
                reason="base_preset_exceeds_parent_ceiling",
            )

        if check_stage == CreateAuthorizationStage.DELTA_CEILING:
            parent_can_grant = self._evaluate_parent_ceiling(create_context)
            if parent_can_grant is None:
                return AuthorizationDecision.deny(request, reason="invalid_create_context")
            if parent_can_grant is True:
                return AuthorizationDecision.allow(
                    request,
                    reason="delta_within_parent_ceiling",
                )
            return AuthorizationDecision.deny(
                request,
                reason="delta_exceeds_parent_ceiling",
            )

        if check_stage == CreateAuthorizationStage.REQUESTER_PARENT_BINDING:
            parent_agent_id = create_context.parent_agent_id
            if not isinstance(parent_agent_id, str):
                return AuthorizationDecision.allow(
                    request,
                    reason="no_parent_binding",
                )
            if request.principal_id == "external":
                return AuthorizationDecision.allow(
                    request,
                    reason="external_requester",
                )
            if request.principal_id == parent_agent_id:
                return AuthorizationDecision.allow(
                    request,
                    reason="requester_matches_parent",
                )
            return AuthorizationDecision.deny(
                request,
                reason="requester_parent_mismatch",
            )


def serialize_create_permissions(permissions: AgentPermissions | None) -> str | None:
    """Serialize permissions for create-stage kernel context payload."""
    if permissions is None:
        return None
    return json.dumps(permissions.to_dict(), sort_keys=True)


def enforce_create_authorization(
    *,
    kernel: AdapterAuthorizationKernel,
    target_agent_id: str,
    requester_id: str,
    check_stage: CreateAuthorizationStage,
    parent_depth: int,
    denial_message: str,
    parent_permissions: AgentPermissions | None = None,
    requested_permissions: AgentPermissions | None = None,
    parent_agent_id: str | None = None,
    max_agent_depth: int = MAX_AGENT_DEPTH,
) -> None:
    """Apply create authorization kernel decision for a specific create stage."""
    create_context = CreateAuthorizationContext(
        check_stage=check_stage,
        parent_depth=parent_depth,
        max_depth=max_agent_depth,
        parent_permissions_json=serialize_create_permissions(parent_permissions),
        requested_permissions_json=serialize_create_permissions(requested_permissions),
        parent_agent_id=parent_agent_id,
    )
    kernel_context = create_context.to_context_map()

    kernel_request = AuthorizationRequest(
        action=AuthorizationAction.AGENT_CREATE,
        resource=AuthorizationResource(
            resource_type=AuthorizationResourceType.AGENT,
            identifier=target_agent_id,
        ),
        principal_id=requester_id,
        context=kernel_context,
    )
    kernel_decision = kernel.authorize(kernel_request)
    if not kernel_decision.allowed:
        raise PermissionError(denial_message)


def prepare_create_unlocked(
    *,
    agents: Mapping[str, AgentT],
    config_resolver: ConfigResolverLike,
    custom_presets: Mapping[str, PermissionPreset],
    base_log_dir: Path,
    create_authorization_kernel: AdapterAuthorizationKernel,
    validate_agent_id: Callable[[str], None],
    get_parent_permissions: ParentPermissionsReader[AgentT],
    new_default_config: Callable[[], ConfigT],
    agent_id: str | None = None,
    config: ConfigT | None = None,
    requester_id: str | None = None,
    max_agent_depth: int = MAX_AGENT_DEPTH,
) -> PreparedCreateInputs[ConfigT]:
    """Prepare create-stage policy/runtime inputs for _create_unlocked wiring."""
    effective_config = config or new_default_config()
    effective_id = effective_config.agent_id or agent_id
    if effective_id is None:
        raise ValueError("effective_id must be provided before create_unlocked preparation")

    validate_agent_id(effective_id)
    if effective_id in agents:
        raise ValueError(f"Agent already exists: {effective_id}")

    preset_name = effective_config.preset or config_resolver.permissions.default_preset
    try:
        permissions = resolve_preset(
            preset_name,
            dict(custom_presets),
            cwd=effective_config.cwd,
        )
    except ValueError:
        permissions = resolve_preset(
            "sandboxed",
            dict(custom_presets),
            cwd=effective_config.cwd,
        )

    parent_permissions = effective_config.parent_permissions
    if effective_config.parent_agent_id is not None:
        parent_agent = agents.get(effective_config.parent_agent_id)
        if parent_agent is None:
            raise PermissionError(
                "Cannot create agent: parent agent not found: "
                f"{effective_config.parent_agent_id}"
            )

        live_parent_permissions = get_parent_permissions(parent_agent)
        if not isinstance(live_parent_permissions, AgentPermissions):
            raise PermissionError(
                "Cannot create agent: parent agent has no permissions service"
            )

        if (
            parent_permissions is not None
            and parent_permissions is not live_parent_permissions
        ):
            logger.warning(
                "Parent permissions mismatch for create(%s): ignoring provided "
                "parent_permissions and using live parent permissions from %s",
                effective_id,
                effective_config.parent_agent_id,
            )
        parent_permissions = live_parent_permissions

    create_requester_id = requester_id or effective_config.parent_agent_id or "external"
    parent_depth = parent_permissions.depth if parent_permissions is not None else 0

    enforce_create_authorization(
        kernel=create_authorization_kernel,
        target_agent_id=effective_id,
        requester_id=create_requester_id,
        check_stage=CreateAuthorizationStage.LIFECYCLE_ENTRY,
        parent_depth=parent_depth,
        denial_message=(
            "Cannot create agent: requester is not authorized to create this agent"
        ),
        max_agent_depth=max_agent_depth,
    )

    if effective_config.parent_agent_id is not None:
        enforce_create_authorization(
            kernel=create_authorization_kernel,
            target_agent_id=effective_id,
            requester_id=create_requester_id,
            check_stage=CreateAuthorizationStage.REQUESTER_PARENT_BINDING,
            parent_depth=parent_depth,
            denial_message=(
                "Cannot create agent: requester does not match the parent agent"
            ),
            parent_agent_id=effective_config.parent_agent_id,
            max_agent_depth=max_agent_depth,
        )

    if parent_permissions is not None:
        enforce_create_authorization(
            kernel=create_authorization_kernel,
            target_agent_id=effective_id,
            requester_id=create_requester_id,
            check_stage=CreateAuthorizationStage.MAX_DEPTH,
            parent_depth=parent_permissions.depth,
            denial_message=(
                f"Cannot create agent: max nesting depth ({max_agent_depth}) exceeded"
            ),
            max_agent_depth=max_agent_depth,
        )
        enforce_create_authorization(
            kernel=create_authorization_kernel,
            target_agent_id=effective_id,
            requester_id=create_requester_id,
            check_stage=CreateAuthorizationStage.BASE_CEILING,
            parent_depth=parent_permissions.depth,
            parent_permissions=parent_permissions,
            requested_permissions=permissions,
            denial_message=f"Requested preset '{preset_name}' exceeds parent ceiling",
            max_agent_depth=max_agent_depth,
        )

    if effective_config.delta:
        permissions = permissions.apply_delta(effective_config.delta)
        if parent_permissions is not None:
            enforce_create_authorization(
                kernel=create_authorization_kernel,
                target_agent_id=effective_id,
                requester_id=create_requester_id,
                check_stage=CreateAuthorizationStage.DELTA_CEILING,
                parent_depth=parent_permissions.depth,
                parent_permissions=parent_permissions,
                requested_permissions=permissions,
                denial_message="Permission delta would exceed parent ceiling",
                max_agent_depth=max_agent_depth,
            )

    if parent_permissions is not None:
        permissions.ceiling = copy.deepcopy(parent_permissions)
        permissions.parent_agent_id = effective_config.parent_agent_id
        permissions.depth = parent_permissions.depth + 1

    resolved_model = config_resolver.resolve_model(effective_config.model)
    return PreparedCreateInputs(
        effective_id=effective_id,
        effective_config=effective_config,
        agent_log_dir=base_log_dir / effective_id,
        preset_name=preset_name,
        permissions=permissions,
        resolved_model=resolved_model,
        parent_permissions=parent_permissions,
        requester_id=create_requester_id,
    )


async def create_unlocked(
    *,
    agents: Mapping[str, AgentT],
    config_resolver: ConfigResolverLike,
    custom_presets: Mapping[str, PermissionPreset],
    base_log_dir: Path,
    create_authorization_kernel: AdapterAuthorizationKernel,
    validate_agent_id: Callable[[str], None],
    get_parent_permissions: ParentPermissionsReader[AgentT],
    new_default_config: Callable[[], ConfigT],
    materialize: Callable[[PreparedCreateInputs[ConfigT]], Awaitable[AgentT]],
    agent_id: str | None = None,
    config: ConfigT | None = None,
    requester_id: str | None = None,
    max_agent_depth: int = MAX_AGENT_DEPTH,
) -> AgentT:
    """Async helper corresponding to AgentPool._create_unlocked."""
    prepared = prepare_create_unlocked(
        agents=agents,
        config_resolver=config_resolver,
        custom_presets=custom_presets,
        base_log_dir=base_log_dir,
        create_authorization_kernel=create_authorization_kernel,
        validate_agent_id=validate_agent_id,
        get_parent_permissions=get_parent_permissions,
        new_default_config=new_default_config,
        agent_id=agent_id,
        config=config,
        requester_id=requester_id,
        max_agent_depth=max_agent_depth,
    )
    return await materialize(prepared)


async def create(
    *,
    lock: asyncio.Lock,
    create_unlocked_fn: CreateUnlockedFn[ConfigT, AgentT],
    agent_id: str | None = None,
    config: ConfigT | None = None,
    requester_id: str | None = None,
) -> AgentT:
    """Lock wrapper corresponding to AgentPool.create."""
    async with lock:
        return await create_unlocked_fn(agent_id, config, requester_id)


async def create_temp(
    *,
    lock: asyncio.Lock,
    existing_agent_ids: Callable[[], Iterable[str]],
    generate_temp_id: TempIdGenerator,
    build_temp_config: TempConfigBuilder[ConfigT],
    create_unlocked_fn: CreateUnlockedFn[ConfigT, AgentT],
    config: ConfigT | None = None,
) -> AgentT:
    """Lock wrapper corresponding to AgentPool.create_temp."""
    async with lock:
        temp_id = generate_temp_id(set(existing_agent_ids()))
        effective_config = build_temp_config(config, temp_id)
        return await create_unlocked_fn(None, effective_config, None)
