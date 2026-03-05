"""Context compiler IR and invariant checks for provider-bound message prep."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from nexus3.core.types import Message, Role


class InvariantCode(StrEnum):
    """Stable codes for compiler invariant violations."""

    TOOL_RESULT_OUTSIDE_ASSISTANT_BATCH = "tool_result_outside_assistant_batch"
    TOOL_RESULT_UNKNOWN_ID = "tool_result_unknown_id"
    TOOL_RESULT_DUPLICATE_ID = "tool_result_duplicate_id"
    MISSING_TOOL_RESULT = "missing_tool_result"
    TRAILING_TOOL_BATCH = "trailing_tool_batch"


@dataclass(frozen=True)
class InvariantViolation:
    """A single invariant violation entry."""

    code: InvariantCode
    message: str
    index: int | None = None
    tool_call_id: str | None = None


@dataclass(frozen=True)
class InvariantReport:
    """Structured invariant-check result."""

    violations: tuple[InvariantViolation, ...]

    @property
    def ok(self) -> bool:
        """True when no violations are present."""
        return not self.violations


@dataclass(frozen=True)
class ToolBatchIR:
    """IR summary for one assistant tool-call batch."""

    assistant_index: int
    tool_result_indices: tuple[int, ...]
    expected_tool_call_ids: tuple[str, ...]
    seen_tool_call_ids: tuple[str, ...]
    missing_tool_call_ids: tuple[str, ...]


@dataclass(frozen=True)
class CompileDiagnostics:
    """Repair diagnostics emitted by compile step."""

    pruned_tool_results: int
    synthesized_tool_results: int
    appended_assistant_after_tool_results: bool
    invariant_errors: tuple[str, ...]


@dataclass(frozen=True)
class CompiledContextIR:
    """Compiled context payload for provider-bound message conversion."""

    messages: tuple[Message, ...]
    tool_batches: tuple[ToolBatchIR, ...]
    diagnostics: CompileDiagnostics
    invariant_report: InvariantReport


def _prune_unpaired_tool_results(messages: list[Message]) -> int:
    removed = 0
    i = 0
    while i < len(messages):
        msg = messages[i]

        if msg.role == Role.ASSISTANT and msg.tool_calls:
            expected_ids = {tool_call.id for tool_call in msg.tool_calls}
            seen_ids: set[str] = set()
            j = i + 1
            while j < len(messages) and messages[j].role == Role.TOOL:
                tool_msg = messages[j]
                tool_id = tool_msg.tool_call_id
                if tool_id in expected_ids and tool_id not in seen_ids:
                    seen_ids.add(tool_id)
                    j += 1
                    continue
                del messages[j]
                removed += 1
            i = j
            continue

        if msg.role == Role.TOOL:
            del messages[i]
            removed += 1
            continue

        i += 1

    return removed


def _synthesize_missing_tool_results(messages: list[Message]) -> int:
    synthesized = 0
    i = 0
    while i < len(messages):
        msg = messages[i]
        if not (msg.role == Role.ASSISTANT and msg.tool_calls):
            i += 1
            continue

        expected_ids = {tool_call.id for tool_call in msg.tool_calls}
        found_ids: set[str] = set()

        j = i + 1
        while j < len(messages):
            next_msg = messages[j]
            if next_msg.role != Role.TOOL:
                break
            if next_msg.tool_call_id in expected_ids:
                found_ids.add(next_msg.tool_call_id)
            j += 1

        missing_ids = expected_ids - found_ids
        if missing_ids:
            insert_pos = j
            for tool_call in msg.tool_calls:
                if tool_call.id not in missing_ids:
                    continue
                messages.insert(
                    insert_pos,
                    Message(
                        role=Role.TOOL,
                        content="Cancelled by user: tool execution was interrupted",
                        tool_call_id=tool_call.id,
                    ),
                )
                synthesized += 1
                insert_pos += 1
            j = insert_pos

        i = j

    return synthesized


def _ensure_assistant_after_trailing_tool_results(messages: list[Message]) -> bool:
    if not messages or messages[-1].role != Role.TOOL:
        return False

    start = len(messages) - 1
    while start >= 0 and messages[start].role == Role.TOOL:
        start -= 1
    start += 1

    assistant_index = start - 1
    if assistant_index < 0:
        return False

    assistant_message = messages[assistant_index]
    if assistant_message.role != Role.ASSISTANT or not assistant_message.tool_calls:
        return False

    expected_ids = {tool_call.id for tool_call in assistant_message.tool_calls}
    found_ids = {
        message.tool_call_id
        for message in messages[start:]
        if message.tool_call_id is not None
    }
    if not expected_ids.issubset(found_ids):
        return False

    messages.append(
        Message(
            role=Role.ASSISTANT,
            content="Previous turn was cancelled after tool execution.",
        )
    )
    return True


def _build_tool_batches(messages: Sequence[Message]) -> tuple[ToolBatchIR, ...]:
    batches: list[ToolBatchIR] = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        if not (msg.role == Role.ASSISTANT and msg.tool_calls):
            i += 1
            continue

        expected_order = tuple(tool_call.id for tool_call in msg.tool_calls)
        expected_set = set(expected_order)
        seen_order: list[str] = []
        seen_set: set[str] = set()
        result_indices: list[int] = []

        j = i + 1
        while j < len(messages) and messages[j].role == Role.TOOL:
            result_indices.append(j)
            tool_id = messages[j].tool_call_id
            if tool_id in expected_set and tool_id not in seen_set:
                seen_order.append(tool_id)
                seen_set.add(tool_id)
            j += 1

        missing = tuple(tool_id for tool_id in expected_order if tool_id not in seen_set)
        batches.append(
            ToolBatchIR(
                assistant_index=i,
                tool_result_indices=tuple(result_indices),
                expected_tool_call_ids=expected_order,
                seen_tool_call_ids=tuple(seen_order),
                missing_tool_call_ids=missing,
            )
        )
        i = j

    return tuple(batches)


def check_context_invariants(messages: Sequence[Message]) -> InvariantReport:
    """Run invariant checks over a message sequence."""
    violations: list[InvariantViolation] = []
    i = 0
    while i < len(messages):
        msg = messages[i]

        if msg.role == Role.ASSISTANT and msg.tool_calls:
            expected_order = tuple(tool_call.id for tool_call in msg.tool_calls)
            expected_set = set(expected_order)
            seen_set: set[str] = set()

            j = i + 1
            while j < len(messages) and messages[j].role == Role.TOOL:
                tool_msg = messages[j]
                tool_id = tool_msg.tool_call_id
                if tool_id not in expected_set:
                    violations.append(
                        InvariantViolation(
                            code=InvariantCode.TOOL_RESULT_UNKNOWN_ID,
                            message=(
                                f"TOOL message at index {j} has unknown tool_call_id "
                                f"'{tool_id}' for assistant batch at index {i}"
                            ),
                            index=j,
                            tool_call_id=tool_id,
                        )
                    )
                elif tool_id in seen_set:
                    violations.append(
                        InvariantViolation(
                            code=InvariantCode.TOOL_RESULT_DUPLICATE_ID,
                            message=(
                                f"TOOL message at index {j} duplicates tool_call_id "
                                f"'{tool_id}' in assistant batch at index {i}"
                            ),
                            index=j,
                            tool_call_id=tool_id,
                        )
                    )
                else:
                    seen_set.add(tool_id)
                j += 1

            for tool_id in expected_order:
                if tool_id not in seen_set:
                    violations.append(
                        InvariantViolation(
                            code=InvariantCode.MISSING_TOOL_RESULT,
                            message=(
                                f"Assistant tool_call '{tool_id}' at index {i} "
                                "is missing a TOOL result"
                            ),
                            index=i,
                            tool_call_id=tool_id,
                        )
                    )
            i = j
            continue

        if msg.role == Role.TOOL:
            violations.append(
                InvariantViolation(
                    code=InvariantCode.TOOL_RESULT_OUTSIDE_ASSISTANT_BATCH,
                    message=(
                        f"TOOL message at index {i} is outside an assistant tool-call batch"
                    ),
                    index=i,
                    tool_call_id=msg.tool_call_id,
                )
            )

        i += 1

    if messages and messages[-1].role == Role.TOOL:
        violations.append(
            InvariantViolation(
                code=InvariantCode.TRAILING_TOOL_BATCH,
                message="Conversation ends with TOOL messages without a trailing assistant message",
                index=len(messages) - 1,
            )
        )

    return InvariantReport(violations=tuple(violations))


def validate_compiled_message_invariants(messages: Sequence[Message]) -> list[str]:
    """Compatibility helper returning invariant error strings only."""
    report = check_context_invariants(messages)
    return [violation.message for violation in report.violations]


def compile_context_messages(
    messages: Sequence[Message],
    *,
    system_prompt: str | None = None,
    prune_unpaired_tool_results: bool = True,
    synthesize_missing_tool_results: bool = True,
    ensure_assistant_after_tool_results: bool = True,
) -> CompiledContextIR:
    """Compile context messages into normalized IR with diagnostics."""
    compiled_messages = list(messages)

    pruned = 0
    if prune_unpaired_tool_results:
        pruned = _prune_unpaired_tool_results(compiled_messages)

    synthesized = 0
    if synthesize_missing_tool_results:
        synthesized = _synthesize_missing_tool_results(compiled_messages)

    appended = False
    if ensure_assistant_after_tool_results:
        appended = _ensure_assistant_after_trailing_tool_results(compiled_messages)

    report = check_context_invariants(compiled_messages)
    diagnostics = CompileDiagnostics(
        pruned_tool_results=pruned,
        synthesized_tool_results=synthesized,
        appended_assistant_after_tool_results=appended,
        invariant_errors=tuple(violation.message for violation in report.violations),
    )

    messages_with_system = list(compiled_messages)
    if system_prompt:
        system_message = Message(role=Role.SYSTEM, content=system_prompt)
        if (
            not messages_with_system
            or messages_with_system[0].role != Role.SYSTEM
            or messages_with_system[0].content != system_prompt
        ):
            messages_with_system.insert(0, system_message)

    return CompiledContextIR(
        messages=tuple(messages_with_system),
        tool_batches=_build_tool_batches(compiled_messages),
        diagnostics=diagnostics,
        invariant_report=report,
    )


def compile_message_sequence(
    messages: Sequence[Message],
    *,
    system_prompt: str | None = None,
    prune_unpaired_tool_results: bool = True,
    synthesize_missing_tool_results: bool = True,
    ensure_assistant_after_tool_results: bool = True,
) -> CompiledContextIR:
    """Compatibility alias for compiler entrypoint name used in tests/docs."""
    return compile_context_messages(
        messages,
        system_prompt=system_prompt,
        prune_unpaired_tool_results=prune_unpaired_tool_results,
        synthesize_missing_tool_results=synthesize_missing_tool_results,
        ensure_assistant_after_tool_results=ensure_assistant_after_tool_results,
    )


__all__ = [
    "InvariantCode",
    "InvariantViolation",
    "InvariantReport",
    "ToolBatchIR",
    "CompileDiagnostics",
    "CompiledContextIR",
    "check_context_invariants",
    "compile_context_messages",
    "compile_message_sequence",
    "validate_compiled_message_invariants",
]
