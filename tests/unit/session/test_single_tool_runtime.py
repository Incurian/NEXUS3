"""Tests for single_tool_runtime compatibility normalization."""

from nexus3.core.types import ToolCall
from nexus3.session.single_tool_runtime import _normalize_tool_call_for_execution


def test_legacy_edit_file_batch_call_is_remapped() -> None:
    """Legacy edit_file(edits=[...]) calls should route to edit_file_batch."""
    tool_call = ToolCall(
        id="call_1",
        name="edit_file",
        arguments={
            "path": "/tmp/demo.txt",
            "edits": [
                {
                    "old_string": "alpha",
                    "new_string": "ALPHA",
                }
            ],
        },
    )

    normalized = _normalize_tool_call_for_execution(tool_call)

    assert normalized.name == "edit_file_batch"
    assert normalized.arguments == tool_call.arguments
    assert normalized.meta["compat_tool_alias_from"] == "edit_file"


def test_legacy_edit_file_batch_placeholders_are_stripped() -> None:
    """Harmless legacy single-edit placeholders should be removed."""
    tool_call = ToolCall(
        id="call_2",
        name="edit_file",
        arguments={
            "path": "/tmp/demo.txt",
            "old_string": "",
            "new_string": "",
            "replace_all": False,
            "edits": [
                {
                    "old_string": "alpha",
                    "new_string": "ALPHA",
                }
            ],
        },
    )

    normalized = _normalize_tool_call_for_execution(tool_call)

    assert normalized.name == "edit_file_batch"
    assert normalized.arguments == {
        "path": "/tmp/demo.txt",
        "edits": [
            {
                "old_string": "alpha",
                "new_string": "ALPHA",
            }
        ],
    }
    assert normalized.meta["compat_tool_alias_from"] == "edit_file"
    assert normalized.meta["compat_normalized_legacy_placeholders"] is True


def test_single_edit_file_call_is_unchanged() -> None:
    """Normal single-edit calls should not be rewritten."""
    tool_call = ToolCall(
        id="call_3",
        name="edit_file",
        arguments={
            "path": "/tmp/demo.txt",
            "old_string": "alpha",
            "new_string": "ALPHA",
        },
    )

    normalized = _normalize_tool_call_for_execution(tool_call)

    assert normalized is tool_call


def test_legacy_edit_lines_batch_call_is_remapped() -> None:
    """Legacy edit_lines(edits=[...]) calls should route to edit_lines_batch."""
    tool_call = ToolCall(
        id="call_4",
        name="edit_lines",
        arguments={
            "path": "/tmp/demo.txt",
            "edits": [
                {
                    "start_line": 2,
                    "new_content": "replacement",
                }
            ],
        },
    )

    normalized = _normalize_tool_call_for_execution(tool_call)

    assert normalized.name == "edit_lines_batch"
    assert normalized.arguments == tool_call.arguments
    assert normalized.meta["compat_tool_alias_from"] == "edit_lines"


def test_legacy_edit_lines_batch_placeholders_are_stripped() -> None:
    """Harmless single-edit placeholders should be removed for edit_lines batches."""
    tool_call = ToolCall(
        id="call_5",
        name="edit_lines",
        arguments={
            "path": "/tmp/demo.txt",
            "start_line": None,
            "end_line": None,
            "new_content": "",
            "edits": [
                {
                    "start_line": 2,
                    "new_content": "replacement",
                }
            ],
        },
    )

    normalized = _normalize_tool_call_for_execution(tool_call)

    assert normalized.name == "edit_lines_batch"
    assert normalized.arguments == {
        "path": "/tmp/demo.txt",
        "edits": [
            {
                "start_line": 2,
                "new_content": "replacement",
            }
        ],
    }
    assert normalized.meta["compat_tool_alias_from"] == "edit_lines"
    assert normalized.meta["compat_normalized_legacy_placeholders"] is True


def test_patch_target_alias_and_diff_file_are_normalized() -> None:
    """Legacy patch alias/input forms should normalize to public canonical tools."""
    tool_call = ToolCall(
        id="call_6",
        name="patch",
        arguments={
            "target": "/tmp/demo.txt",
            "diff_file": "/tmp/change.diff",
        },
    )

    normalized = _normalize_tool_call_for_execution(tool_call)

    assert normalized.name == "patch_from_file"
    assert normalized.arguments == {
        "path": "/tmp/demo.txt",
        "diff_file": "/tmp/change.diff",
    }
    assert normalized.meta["compat_argument_alias_target"] == "path"


def test_read_file_start_end_aliases_are_normalized() -> None:
    """read_file aliases should normalize to offset/limit before validation."""
    tool_call = ToolCall(
        id="call_7",
        name="read_file",
        arguments={
            "path": "/tmp/demo.txt",
            "start_line": 3,
            "end_line": 5,
        },
    )

    normalized = _normalize_tool_call_for_execution(tool_call)

    assert normalized.arguments == {
        "path": "/tmp/demo.txt",
        "offset": 3,
        "limit": 3,
    }
    assert normalized.meta["compat_argument_alias_window"] == "offset_limit"


def test_outline_parser_aliases_are_normalized() -> None:
    """outline parser aliases should normalize to the canonical parser argument."""
    tool_call = ToolCall(
        id="call_8",
        name="outline",
        arguments={
            "path": "/tmp/demo.txt",
            "file_type": "py",
        },
    )

    normalized = _normalize_tool_call_for_execution(tool_call)

    assert normalized.arguments == {
        "path": "/tmp/demo.txt",
        "parser": "python",
    }
    assert normalized.meta["compat_argument_alias_parser"] == "parser"


def test_read_file_conflicting_aliases_fail_closed() -> None:
    """Conflicting read_file alias/canonical windows should preserve a clear error."""
    tool_call = ToolCall(
        id="call_9",
        name="read_file",
        arguments={
            "path": "/tmp/demo.txt",
            "offset": 2,
            "start_line": 3,
        },
    )

    normalized = _normalize_tool_call_for_execution(tool_call)

    assert normalized.meta["compat_validation_error"] == (
        "read_file offset and start_line must match when both are provided"
    )
