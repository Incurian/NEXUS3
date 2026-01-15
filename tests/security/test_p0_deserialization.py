"""P0.1: Test that empty allowed_paths [] is preserved through serialization.

This tests the critical security bug where `allowed_paths=[]` (deny all paths)
was being converted to `allowed_paths=None` (allow all paths) after JSON
roundtrip due to a truthiness check.

The semantic distinction:
- allowed_paths=None  -> Unrestricted (any path allowed)
- allowed_paths=[]    -> Deny all (no paths allowed)
- allowed_paths=[...] -> Only listed paths allowed
"""

from pathlib import Path

import pytest

from nexus3.core.policy import PermissionLevel, PermissionPolicy
from nexus3.core.presets import ToolPermission


class TestPermissionPolicyDeserialization:
    """Test PermissionPolicy.from_dict preserves allowed_paths semantics."""

    def test_none_stays_none(self) -> None:
        """allowed_paths=None (unrestricted) roundtrips correctly."""
        policy = PermissionPolicy(
            level=PermissionLevel.SANDBOXED,
            allowed_paths=None,
            cwd=Path("/tmp"),
        )
        data = policy.to_dict()
        restored = PermissionPolicy.from_dict(data)

        assert restored.allowed_paths is None, (
            "allowed_paths=None should remain None after roundtrip"
        )

    def test_empty_list_stays_empty(self) -> None:
        """CRITICAL: allowed_paths=[] (deny all) must NOT become None.

        This was the P0.1 security bug - empty list was converted to None,
        turning a deny-all policy into an allow-all policy.
        """
        policy = PermissionPolicy(
            level=PermissionLevel.SANDBOXED,
            allowed_paths=[],  # Deny all paths
            cwd=Path("/tmp"),
        )
        data = policy.to_dict()
        restored = PermissionPolicy.from_dict(data)

        assert restored.allowed_paths is not None, (
            "SECURITY BUG: allowed_paths=[] became None (deny-all -> allow-all)"
        )
        assert restored.allowed_paths == [], (
            "allowed_paths=[] should remain empty list after roundtrip"
        )

    def test_nonempty_list_preserved(self) -> None:
        """allowed_paths with entries roundtrips correctly."""
        policy = PermissionPolicy(
            level=PermissionLevel.SANDBOXED,
            allowed_paths=[Path("/home/user"), Path("/tmp")],
            cwd=Path("/tmp"),
        )
        data = policy.to_dict()
        restored = PermissionPolicy.from_dict(data)

        assert restored.allowed_paths is not None
        assert len(restored.allowed_paths) == 2
        assert Path("/home/user") in restored.allowed_paths
        assert Path("/tmp") in restored.allowed_paths


class TestToolPermissionDeserialization:
    """Test ToolPermission.from_dict preserves allowed_paths semantics."""

    def test_none_stays_none(self) -> None:
        """allowed_paths=None (unrestricted) roundtrips correctly."""
        perm = ToolPermission(enabled=True, allowed_paths=None)
        data = perm.to_dict()
        restored = ToolPermission.from_dict(data)

        assert restored.allowed_paths is None

    def test_empty_list_stays_empty(self) -> None:
        """CRITICAL: allowed_paths=[] (deny all) must NOT become None."""
        perm = ToolPermission(enabled=True, allowed_paths=[])
        data = perm.to_dict()
        restored = ToolPermission.from_dict(data)

        assert restored.allowed_paths is not None, (
            "SECURITY BUG: allowed_paths=[] became None"
        )
        assert restored.allowed_paths == []

    def test_nonempty_list_preserved(self) -> None:
        """allowed_paths with entries roundtrips correctly."""
        perm = ToolPermission(
            enabled=True,
            allowed_paths=[Path("/allowed/path")],
        )
        data = perm.to_dict()
        restored = ToolPermission.from_dict(data)

        assert restored.allowed_paths is not None
        assert len(restored.allowed_paths) == 1
        assert Path("/allowed/path") in restored.allowed_paths


class TestJSONRoundtrip:
    """Test behavior through actual JSON serialization (RPC boundary)."""

    def test_policy_json_roundtrip(self) -> None:
        """Test policy through JSON.dumps/loads cycle."""
        import json

        policy = PermissionPolicy(
            level=PermissionLevel.SANDBOXED,
            allowed_paths=[],
            cwd=Path("/tmp"),
        )

        # Simulate RPC: to_dict -> JSON -> from_dict
        json_str = json.dumps(policy.to_dict())
        restored_data = json.loads(json_str)
        restored = PermissionPolicy.from_dict(restored_data)

        assert restored.allowed_paths == [], (
            "Empty allowed_paths must survive JSON roundtrip"
        )

    def test_tool_permission_json_roundtrip(self) -> None:
        """Test tool permission through JSON.dumps/loads cycle."""
        import json

        perm = ToolPermission(enabled=True, allowed_paths=[])

        json_str = json.dumps(perm.to_dict())
        restored_data = json.loads(json_str)
        restored = ToolPermission.from_dict(restored_data)

        assert restored.allowed_paths == [], (
            "Empty allowed_paths must survive JSON roundtrip"
        )
