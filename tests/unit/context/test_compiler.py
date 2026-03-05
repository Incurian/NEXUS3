"""Tests for context compiler IR and invariant checks."""

import json
from pathlib import Path
from typing import Any

import pytest

from nexus3.context.compiler import (
    compile_message_sequence,
    validate_compiled_message_invariants,
)
from nexus3.core.types import Message, Role, ToolCall

_FIXTURE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "arch_baseline" / (
    "context_compile_baseline.json"
)


def _message_from_payload(payload: dict[str, Any]) -> Message:
    role = payload["role"]
    if role == "user":
        return Message(role=Role.USER, content=payload["content"])
    if role == "assistant":
        calls = tuple(
            ToolCall(
                id=entry["id"],
                name=entry["name"],
                arguments=entry.get("arguments", {}),
            )
            for entry in payload.get("tool_calls", [])
        )
        return Message(
            role=Role.ASSISTANT,
            content=payload["content"],
            tool_calls=calls,
        )
    if role == "tool":
        return Message(
            role=Role.TOOL,
            content=payload["content"],
            tool_call_id=payload["tool_call_id"],
        )
    raise AssertionError(f"Unsupported fixture role: {role}")


def _snapshot_messages(messages: list[Message]) -> list[dict[str, Any]]:
    snapshot: list[dict[str, Any]] = []
    for msg in messages:
        row: dict[str, Any] = {"role": msg.role.value, "content": msg.content}
        if msg.tool_call_id is not None:
            row["tool_call_id"] = msg.tool_call_id
        if msg.tool_calls:
            row["tool_calls"] = [
                {"id": tool_call.id, "name": tool_call.name}
                for tool_call in msg.tool_calls
            ]
        snapshot.append(row)
    return snapshot


@pytest.mark.parametrize(
    "case",
    json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))["cases"],
    ids=lambda case: case["id"],
)
def test_compile_message_sequence_matches_baseline_fixture(case: dict[str, Any]) -> None:
    input_messages = [_message_from_payload(payload) for payload in case["input_messages"]]
    compiled = compile_message_sequence(
        input_messages,
        system_prompt=case["system_prompt"],
    )

    assert compiled.diagnostics.pruned_tool_results == case["expected"]["pruned_tool_results"]
    assert (
        compiled.diagnostics.appended_assistant_after_tool_results
        is case["expected"]["assistant_appended"]
    )
    assert not compiled.diagnostics.invariant_errors
    assert _snapshot_messages(list(compiled.messages)) == case["expected"]["compiled"]


@pytest.mark.parametrize(
    ("case_id", "expected_pruned", "expected_synthesized", "expected_appended"),
    [
        ("repair_missing_tool_and_prune_invalid_tool_results", 2, 1, False),
        ("append_assistant_after_trailing_tool_batch", 0, 0, True),
    ],
)
def test_compile_message_sequence_reports_repair_diagnostics(
    case_id: str,
    expected_pruned: int,
    expected_synthesized: int,
    expected_appended: bool,
) -> None:
    cases = {
        case["id"]: case
        for case in json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))["cases"]
    }
    case = cases[case_id]
    input_messages = [_message_from_payload(payload) for payload in case["input_messages"]]

    compiled = compile_message_sequence(
        input_messages,
        system_prompt=case["system_prompt"],
    )

    assert compiled.diagnostics.pruned_tool_results == expected_pruned
    assert compiled.diagnostics.synthesized_tool_results == expected_synthesized
    assert compiled.diagnostics.appended_assistant_after_tool_results is expected_appended
    assert compiled.tool_batches
    assert all(not batch.missing_tool_call_ids for batch in compiled.tool_batches)


def test_validate_compiled_message_invariants_flags_unpaired_tool_messages() -> None:
    messages = [
        Message(role=Role.TOOL, content="orphan", tool_call_id="tc1"),
    ]

    errors = validate_compiled_message_invariants(messages)

    assert len(errors) == 2
    assert "outside an assistant tool-call batch" in errors[0]
    assert "without a trailing assistant message" in errors[1]


def test_compile_message_sequence_can_report_missing_when_repairs_disabled() -> None:
    messages = [
        Message(role=Role.USER, content="Task"),
        Message(
            role=Role.ASSISTANT,
            content="Using tools",
            tool_calls=(ToolCall(id="tc1", name="run", arguments={}),),
        ),
        Message(role=Role.USER, content="Next input"),
    ]

    compiled = compile_message_sequence(
        messages,
        synthesize_missing_tool_results=False,
        ensure_assistant_after_tool_results=False,
    )

    assert compiled.diagnostics.synthesized_tool_results == 0
    assert any(
        "missing a TOOL result" in error
        for error in compiled.diagnostics.invariant_errors
    )
