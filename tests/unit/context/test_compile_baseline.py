"""Baseline parity fixtures for current context compilation behavior.

These tests intentionally snapshot current pre-provider message shaping so
future context-compiler refactors can prove behavior parity.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from nexus3.context.manager import ContextManager
from nexus3.core.types import Role, ToolCall, ToolResult

_FIXTURE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "arch_baseline" / (
    "context_compile_baseline.json"
)


def _snapshot_messages(messages: list[Any]) -> list[dict[str, Any]]:
    snapshot: list[dict[str, Any]] = []
    for msg in messages:
        row: dict[str, Any] = {
            "role": msg.role.value,
            "content": msg.content,
        }
        if msg.tool_call_id is not None:
            row["tool_call_id"] = msg.tool_call_id
        if msg.tool_calls:
            row["tool_calls"] = [
                {"id": call.id, "name": call.name}
                for call in msg.tool_calls
            ]
        snapshot.append(row)
    return snapshot


def _add_fixture_message(ctx: ContextManager, payload: dict[str, Any]) -> None:
    role = payload["role"]
    if role == "user":
        ctx.add_user_message(payload["content"])
        return

    if role == "assistant":
        calls = [
            ToolCall(
                id=entry["id"],
                name=entry["name"],
                arguments=entry.get("arguments", {}),
            )
            for entry in payload.get("tool_calls", [])
        ]
        ctx.add_assistant_message(payload["content"], tool_calls=calls or None)
        return

    if role == "tool":
        ctx.add_tool_result(
            payload["tool_call_id"],
            payload.get("name", "fixture_tool"),
            ToolResult(output=payload["content"]),
        )
        return

    raise AssertionError(f"Unsupported fixture role: {role}")


@pytest.mark.parametrize(
    "case",
    json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))["cases"],
    ids=lambda case: case["id"],
)
def test_context_compile_baseline(case: dict[str, Any]) -> None:
    """Capture current repair-and-build behavior as parity baseline."""
    ctx = ContextManager()
    ctx.set_system_prompt(case["system_prompt"])

    for message in case["input_messages"]:
        _add_fixture_message(ctx, message)

    # Mirrors Session's pre-provider repair pipeline.
    pruned = ctx.prune_unpaired_tool_results()
    ctx.fix_orphaned_tool_calls()
    appended = ctx.ensure_assistant_after_tool_results()

    compiled = ctx.build_messages()
    assert pruned == case["expected"]["pruned_tool_results"]
    assert appended is case["expected"]["assistant_appended"]
    assert _snapshot_messages(compiled) == case["expected"]["compiled"]

    # Dynamic context is volatile but must remain wrapped for provider injection.
    dynamic = ctx.build_dynamic_context()
    assert dynamic is not None
    assert dynamic.startswith("<session-context>\n")
    assert dynamic.endswith("\n</session-context>")
    assert "Current date:" in dynamic
    assert "Current time:" in dynamic

    # Guardrail: compiled messages should remain role-typed.
    assert all(hasattr(msg, "role") and isinstance(msg.role, Role) for msg in compiled)
