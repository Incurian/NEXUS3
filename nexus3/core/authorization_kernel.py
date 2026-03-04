"""Authorization kernel interfaces and decision models.

Foundation-only module for Arch Plan A Phase 1. This defines typed request,
resource, and decision schemas plus a small adapter-based kernel that can
wrap legacy authorization checks in later phases.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

AuthorizationScalar = str | int | float | bool | None


class AuthorizationAction(Enum):
    """Canonical authorization action names."""

    TOOL_EXECUTE = "tool.execute"
    AGENT_CREATE = "agent.create"
    AGENT_DESTROY = "agent.destroy"
    AGENT_SEND = "agent.send"
    AGENT_TARGET = "agent.target"
    SESSION_READ = "session.read"
    SESSION_WRITE = "session.write"


class AuthorizationResourceType(Enum):
    """Supported authorization resource categories."""

    TOOL = "tool"
    AGENT = "agent"
    SESSION = "session"
    PATH = "path"
    RPC = "rpc"


@dataclass(frozen=True)
class AuthorizationResource:
    """Resource being authorized."""

    resource_type: AuthorizationResourceType
    identifier: str
    attributes: dict[str, AuthorizationScalar] = field(default_factory=dict)


@dataclass(frozen=True)
class AuthorizationRequest:
    """Typed authorization input."""

    action: AuthorizationAction
    resource: AuthorizationResource
    principal_id: str
    context: dict[str, AuthorizationScalar] = field(default_factory=dict)


@dataclass(frozen=True)
class AuthorizationDecision:
    """Authorization outcome."""

    allowed: bool
    reason: str
    request: AuthorizationRequest
    metadata: dict[str, AuthorizationScalar] = field(default_factory=dict)

    @classmethod
    def allow(
        cls,
        request: AuthorizationRequest,
        reason: str = "allowed",
        metadata: dict[str, AuthorizationScalar] | None = None,
    ) -> AuthorizationDecision:
        """Build an allow decision."""
        return cls(
            allowed=True,
            reason=reason,
            request=request,
            metadata={} if metadata is None else metadata,
        )

    @classmethod
    def deny(
        cls,
        request: AuthorizationRequest,
        reason: str = "denied",
        metadata: dict[str, AuthorizationScalar] | None = None,
    ) -> AuthorizationDecision:
        """Build a deny decision."""
        return cls(
            allowed=False,
            reason=reason,
            request=request,
            metadata={} if metadata is None else metadata,
        )

    def raise_if_denied(self) -> None:
        """Raise PermissionError when decision is denied."""
        if not self.allowed:
            raise PermissionError(self.reason)


class AuthorizationAdapter(Protocol):
    """Adapter contract for legacy authorization systems.

    Returning None means the adapter does not handle this request.
    """

    def authorize(self, request: AuthorizationRequest) -> AuthorizationDecision | None:
        """Return a decision or None if not applicable."""
        ...


class AuthorizationKernel(Protocol):
    """Kernel interface for authorization decisions."""

    def authorize(self, request: AuthorizationRequest) -> AuthorizationDecision:
        """Return a decision for the request."""
        ...


@dataclass
class AdapterAuthorizationKernel:
    """Minimal adapter-driven kernel implementation.

    This implementation is intentionally small for Phase 1 and is suitable for
    unit testing. Future phases can register adapter wrappers around existing
    call-site checks and then switch callers to this kernel.
    """

    adapters: tuple[AuthorizationAdapter, ...] = ()
    default_allow: bool = False

    def authorize(self, request: AuthorizationRequest) -> AuthorizationDecision:
        """Authorize via adapters, then apply default fallback."""
        for adapter in self.adapters:
            decision = adapter.authorize(request)
            if decision is not None:
                return decision

        if self.default_allow:
            return AuthorizationDecision.allow(request, reason="default_allow")
        return AuthorizationDecision.deny(request, reason="default_deny")

