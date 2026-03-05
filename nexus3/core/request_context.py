"""Immutable request-scoped context shared across dispatch boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nexus3.core.capabilities import CapabilityClaims


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Per-request immutable context for authorization and tracing.

    Attributes:
        requester_id: Agent id from request metadata, or None for external callers.
        capability_claims: Verified capability claims when capability auth is used.
        request_id: JSON-RPC id as a string when available.
        trace_id: Optional trace/correlation id for diagnostics.
        policy_snapshot_id: Optional identifier of policy snapshot used for this request.
    """

    requester_id: str | None
    capability_claims: CapabilityClaims | None = None
    request_id: str | None = None
    trace_id: str | None = None
    policy_snapshot_id: str | None = None
