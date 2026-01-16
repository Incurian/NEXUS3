"""P2.14: Test that deep_merge uses list-replace semantics for permissions.

This tests the security fix where deep_merge REPLACES lists instead of
extending them. This is critical for security-related configuration keys.

The problem with list extension:
- Global: `blocked_paths: ["/etc"]`
- Local:  `blocked_paths: []`
- With extend: Result is `["/etc"]` - local config CANNOT clear the list!
- With replace: Result is `[]` - local config properly overrides

The fix ensures that more specific configuration (local) completely replaces
less specific configuration (global) for list values.
"""

import pytest

from nexus3.core.utils import deep_merge


class TestListReplaceSemantics:
    """Test that lists are replaced, not extended."""

    def test_empty_list_replaces(self) -> None:
        """Empty list in override should clear the base list."""
        base = {"blocked_paths": ["/etc", "/var"]}
        override = {"blocked_paths": []}
        result = deep_merge(base, override)
        assert result["blocked_paths"] == []

    def test_new_list_replaces(self) -> None:
        """New list in override should replace base list entirely."""
        base = {"disabled_tools": ["bash", "shell"]}
        override = {"disabled_tools": ["write_file"]}
        result = deep_merge(base, override)
        assert result["disabled_tools"] == ["write_file"]

    def test_list_not_present_in_override(self) -> None:
        """List not in override should be preserved from base."""
        base = {"blocked_paths": ["/etc"]}
        override = {"other_key": "value"}
        result = deep_merge(base, override)
        assert result["blocked_paths"] == ["/etc"]

    def test_nested_list_replacement(self) -> None:
        """Lists in nested dicts should also be replaced."""
        base = {
            "permissions": {
                "blocked_paths": ["/etc"],
                "level": "trusted"
            }
        }
        override = {
            "permissions": {
                "blocked_paths": ["/home/secret"]
            }
        }
        result = deep_merge(base, override)
        assert result["permissions"]["blocked_paths"] == ["/home/secret"]
        # Non-list key should be preserved
        assert result["permissions"]["level"] == "trusted"


class TestSecurityConfigScenarios:
    """Test real-world security configuration scenarios."""

    def test_local_can_clear_blocked_paths(self) -> None:
        """Local config should be able to clear blocked_paths from global."""
        global_config = {
            "permissions": {
                "presets": {
                    "default": {
                        "blocked_paths": ["/etc", "/var/secrets"]
                    }
                }
            }
        }
        local_config = {
            "permissions": {
                "presets": {
                    "default": {
                        "blocked_paths": []  # User wants no blocked paths
                    }
                }
            }
        }
        result = deep_merge(global_config, local_config)
        assert result["permissions"]["presets"]["default"]["blocked_paths"] == []

    def test_local_can_override_destructive_tools(self) -> None:
        """Local config should be able to change destructive_tools list."""
        global_config = {
            "permissions": {
                "destructive_tools": ["write_file", "bash", "shell"]
            }
        }
        local_config = {
            "permissions": {
                "destructive_tools": ["write_file"]  # Reduce to just write
            }
        }
        result = deep_merge(global_config, local_config)
        assert result["permissions"]["destructive_tools"] == ["write_file"]

    def test_mcp_servers_replaced_not_merged(self) -> None:
        """MCP server lists should be replaced, not merged."""
        global_config = {
            "mcp_servers": [
                {"name": "global_server", "command": ["python", "server.py"]}
            ]
        }
        local_config = {
            "mcp_servers": [
                {"name": "local_server", "command": ["node", "server.js"]}
            ]
        }
        result = deep_merge(global_config, local_config)
        # Should only have local server, not both
        assert len(result["mcp_servers"]) == 1
        assert result["mcp_servers"][0]["name"] == "local_server"


class TestOtherMergeBehavior:
    """Verify other merge behaviors are unchanged."""

    def test_dict_recursive_merge(self) -> None:
        """Dicts should still be recursively merged."""
        base = {"a": {"x": 1, "y": 2}}
        override = {"a": {"y": 3, "z": 4}}
        result = deep_merge(base, override)
        assert result == {"a": {"x": 1, "y": 3, "z": 4}}

    def test_scalar_override(self) -> None:
        """Scalar values should be overridden."""
        base = {"value": "old"}
        override = {"value": "new"}
        result = deep_merge(base, override)
        assert result["value"] == "new"

    def test_new_keys_added(self) -> None:
        """New keys in override should be added."""
        base = {"a": 1}
        override = {"b": 2}
        result = deep_merge(base, override)
        assert result == {"a": 1, "b": 2}

    def test_original_dicts_unmodified(self) -> None:
        """Original dicts should not be modified."""
        base = {"a": 1, "b": {"c": 2}}
        override = {"b": {"d": 3}}
        original_base = {"a": 1, "b": {"c": 2}}
        original_override = {"b": {"d": 3}}

        deep_merge(base, override)

        assert base == original_base
        assert override == original_override
