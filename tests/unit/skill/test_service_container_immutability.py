"""Focused tests for ServiceContainer runtime mutators and snapshots."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from nexus3.config.schema import ResolvedModel
from nexus3.core.permissions import AgentPermissions, PermissionLevel, PermissionPolicy
from nexus3.skill.services import ServiceContainer


def _make_permissions(base_preset: str) -> AgentPermissions:
    level = PermissionLevel.SANDBOXED if base_preset == "sandboxed" else PermissionLevel.TRUSTED
    allowed_paths = [Path("sandbox-root")] if level == PermissionLevel.SANDBOXED else None
    return AgentPermissions(
        base_preset=base_preset,
        effective_policy=PermissionPolicy(
            level=level,
            allowed_paths=allowed_paths,
            cwd=Path("agent-root"),
        ),
    )


def _make_model(alias: str) -> ResolvedModel:
    return ResolvedModel(
        model_id=f"provider/{alias}",
        context_window=64_000,
        reasoning=False,
        alias=alias,
        provider_name="test-provider",
    )


class TestServiceContainerRuntimeMutation:
    """Tests for additive runtime mutators and immutable runtime snapshots."""

    def test_runtime_mutators_update_typed_accessors(self) -> None:
        """Runtime mutators should update the corresponding typed accessors."""
        container = ServiceContainer()
        permissions = _make_permissions(base_preset="trusted")
        model = _make_model(alias="fast")
        cwd = Path("runtime-cwd")
        child_agent_ids = {"child-a", "child-b"}

        container.set_permissions(permissions)
        container.set_cwd(cwd)
        container.set_model(model)
        container.set_child_agent_ids(child_agent_ids)

        assert container.get_permissions() is permissions
        assert container.get_cwd() == cwd
        assert container.get_model() is model
        assert container.get_child_agent_ids() == child_agent_ids

    def test_runtime_snapshot_captures_fields_and_is_immutable(self) -> None:
        """Runtime snapshot should preserve runtime fields and reject mutation."""
        container = ServiceContainer()
        permissions = _make_permissions(base_preset="trusted")
        model = _make_model(alias="balanced")

        container.set_permissions(permissions)
        container.set_cwd(Path("snapshot-cwd"))
        container.set_model(model)
        container.set_child_agent_ids({"child-1", "child-2"})

        snapshot = container.snapshot_runtime()
        assert snapshot.permissions is permissions
        assert snapshot.cwd == Path("snapshot-cwd")
        assert snapshot.model is model
        assert snapshot.child_agent_ids == frozenset({"child-1", "child-2"})
        assert isinstance(snapshot.child_agent_ids, frozenset)

        with pytest.raises(FrozenInstanceError):
            snapshot.cwd = Path("mutated")  # type: ignore[misc]

    def test_updating_one_runtime_field_does_not_corrupt_others(self) -> None:
        """Each runtime mutator should only change its own field."""
        container = ServiceContainer()
        permissions_a = _make_permissions(base_preset="trusted")
        permissions_b = _make_permissions(base_preset="sandboxed")
        model_a = _make_model(alias="alpha")
        model_b = _make_model(alias="beta")
        cwd_a = Path("cwd-a")
        cwd_b = Path("cwd-b")

        container.set_permissions(permissions_a)
        container.set_cwd(cwd_a)
        container.set_model(model_a)
        container.set_child_agent_ids({"child-a"})

        container.set_permissions(permissions_b)
        assert container.get_permissions() is permissions_b
        assert container.get_cwd() == cwd_a
        assert container.get_model() is model_a
        assert container.get_child_agent_ids() == {"child-a"}

        container.set_model(model_b)
        assert container.get_permissions() is permissions_b
        assert container.get_cwd() == cwd_a
        assert container.get_model() is model_b
        assert container.get_child_agent_ids() == {"child-a"}

        container.set_child_agent_ids({"child-b"})
        assert container.get_permissions() is permissions_b
        assert container.get_cwd() == cwd_a
        assert container.get_model() is model_b
        assert container.get_child_agent_ids() == {"child-b"}

        container.set_cwd(cwd_b)
        assert container.get_permissions() is permissions_b
        assert container.get_cwd() == cwd_b
        assert container.get_model() is model_b
        assert container.get_child_agent_ids() == {"child-b"}

    def test_set_permissions_syncs_legacy_allowed_paths_compatibility(self) -> None:
        """Setting permissions should keep legacy allowed_paths reads aligned."""
        container = ServiceContainer()
        container.register("allowed_paths", [Path("stale")])
        sandboxed_permissions = _make_permissions(base_preset="sandboxed")

        container.set_permissions(sandboxed_permissions)

        assert container.get_permissions() is sandboxed_permissions
        assert container.get("allowed_paths") == [Path("sandbox-root")]
        assert container.get_tool_allowed_paths() == [Path("sandbox-root")]

    def test_set_permissions_with_unrestricted_policy_clears_stale_allowed_paths(self) -> None:
        """Trusted permissions should clear stale fallback allowed_paths entries."""
        container = ServiceContainer()
        container.register("allowed_paths", [Path("stale")])

        container.set_permissions(_make_permissions(base_preset="trusted"))

        assert container.get("allowed_paths") is None
        assert container.get_tool_allowed_paths() is None

    def test_clearing_permissions_clears_legacy_allowed_paths_compatibility(self) -> None:
        """Clearing permissions should clear legacy allowed_paths compatibility state."""
        container = ServiceContainer()
        container.set_permissions(_make_permissions(base_preset="sandboxed"))

        container.set_permissions(None)

        assert container.get_permissions() is None
        assert container.get("allowed_paths") is None
        assert container.get_tool_allowed_paths() is None

    def test_snapshot_child_agent_ids_stays_stable_after_runtime_mutation(self) -> None:
        """Snapshot should capture child IDs as an immutable point-in-time copy."""
        container = ServiceContainer()
        input_child_ids = {"child-a"}
        container.set_child_agent_ids(input_child_ids)

        # Verify mutator copies caller-owned set.
        input_child_ids.add("child-b")
        assert container.get_child_agent_ids() == {"child-a"}

        snapshot = container.snapshot_runtime()
        live_child_ids = container.get_child_agent_ids()
        assert live_child_ids is not None
        live_child_ids.add("child-c")

        assert container.get_child_agent_ids() == {"child-a", "child-c"}
        assert snapshot.child_agent_ids == frozenset({"child-a"})
