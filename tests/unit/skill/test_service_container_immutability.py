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
