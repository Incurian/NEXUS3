"""Unit tests for immutable request-scoped context model."""

from dataclasses import FrozenInstanceError, fields

import pytest

from nexus3.core.request_context import RequestContext


class TestRequestContext:
    """Tests for RequestContext model semantics."""

    def test_request_context_field_shape(self) -> None:
        """RequestContext exposes expected immutable identity/tracing fields."""
        field_names = [field.name for field in fields(RequestContext)]
        assert field_names == [
            "requester_id",
            "request_id",
            "trace_id",
            "policy_snapshot_id",
        ]

    def test_request_context_defaults_and_values(self) -> None:
        """RequestContext stores provided values and defaults optional fields."""
        explicit = RequestContext(
            requester_id="agent-7",
            request_id="req-42",
            trace_id="trace-99",
            policy_snapshot_id="policy-v3",
        )
        assert explicit.requester_id == "agent-7"
        assert explicit.request_id == "req-42"
        assert explicit.trace_id == "trace-99"
        assert explicit.policy_snapshot_id == "policy-v3"

        external = RequestContext(requester_id=None)
        assert external.requester_id is None
        assert external.request_id is None
        assert external.trace_id is None
        assert external.policy_snapshot_id is None

    def test_request_context_is_immutable(self) -> None:
        """RequestContext rejects mutation after creation."""
        context = RequestContext(requester_id="agent-1", request_id="req-1")
        with pytest.raises(FrozenInstanceError):
            context.requester_id = "agent-2"
