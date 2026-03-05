"""Immutable request-scoped context shared across dispatch boundaries."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Per-request immutable context for authorization and tracing.

    Attributes:
        requester_id: Agent id from request metadata, or None for external callers.
        request_id: JSON-RPC id as a string when available.
        trace_id: Optional trace/correlation id for diagnostics.
        policy_snapshot_id: Optional identifier of policy snapshot used for this request.
    """

    requester_id: str | None
    request_id: str | None = None
    trace_id: str | None = None
    policy_snapshot_id: str | None = None
