"""Compiler-backed context graph prototype utilities."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from nexus3.context.compiler import (
    CompileDiagnostics,
    InvariantReport,
    compile_context_messages,
)
from nexus3.core.types import Message, Role


class GraphEdgeKind(StrEnum):
    """Edge types used in the context graph."""

    NEXT = "next"
    TOOL_RESULT = "tool_result"


@dataclass(frozen=True)
class ContextGraphEdge:
    """Directed edge in the compiled context graph."""

    source_index: int
    target_index: int
    kind: GraphEdgeKind
    tool_call_id: str | None = None


@dataclass(frozen=True)
class ContextMessageGroup:
    """Atomic message group used by truncation/compaction planning."""

    message_indices: tuple[int, ...]
    includes_tool_batch: bool = False


@dataclass(frozen=True)
class ContextGraph:
    """Graph projection of compiled context messages."""

    messages: tuple[Message, ...]
    edges: tuple[ContextGraphEdge, ...]
    groups: tuple[ContextMessageGroup, ...]
    diagnostics: CompileDiagnostics
    invariant_report: InvariantReport

    def outgoing(
        self,
        source_index: int,
        *,
        kind: GraphEdgeKind | None = None,
    ) -> tuple[ContextGraphEdge, ...]:
        """Return outgoing edges for a source index."""
        return tuple(
            edge
            for edge in self.edges
            if edge.source_index == source_index
            and (kind is None or edge.kind == kind)
        )

    def incoming(
        self,
        target_index: int,
        *,
        kind: GraphEdgeKind | None = None,
    ) -> tuple[ContextGraphEdge, ...]:
        """Return incoming edges for a target index."""
        return tuple(
            edge
            for edge in self.edges
            if edge.target_index == target_index
            and (kind is None or edge.kind == kind)
        )


def _build_edges(messages: Sequence[Message]) -> tuple[ContextGraphEdge, ...]:
    edges: list[ContextGraphEdge] = []

    # Preserve linear turn order.
    for i in range(len(messages) - 1):
        edges.append(
            ContextGraphEdge(
                source_index=i,
                target_index=i + 1,
                kind=GraphEdgeKind.NEXT,
            )
        )

    # Link assistant tool-call batches to their tool-result messages.
    i = 0
    while i < len(messages):
        msg = messages[i]
        if not (msg.role == Role.ASSISTANT and msg.tool_calls):
            i += 1
            continue

        result_index_by_id: dict[str, int] = {}
        j = i + 1
        while j < len(messages) and messages[j].role == Role.TOOL:
            tool_id = messages[j].tool_call_id
            if tool_id is not None and tool_id not in result_index_by_id:
                result_index_by_id[tool_id] = j
            j += 1

        for tool_call in msg.tool_calls:
            target = result_index_by_id.get(tool_call.id)
            if target is None:
                continue
            edges.append(
                ContextGraphEdge(
                    source_index=i,
                    target_index=target,
                    kind=GraphEdgeKind.TOOL_RESULT,
                    tool_call_id=tool_call.id,
                )
            )

        i = j

    return tuple(edges)


def _build_groups(messages: Sequence[Message]) -> tuple[ContextMessageGroup, ...]:
    groups: list[ContextMessageGroup] = []

    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg.role == Role.ASSISTANT and msg.tool_calls:
            expected_ids = {tool_call.id for tool_call in msg.tool_calls}
            indices = [i]
            j = i + 1
            while j < len(messages) and messages[j].role == Role.TOOL:
                tool_id = messages[j].tool_call_id
                if tool_id in expected_ids:
                    indices.append(j)
                    j += 1
                    continue
                break

            groups.append(
                ContextMessageGroup(
                    message_indices=tuple(indices),
                    includes_tool_batch=len(indices) > 1,
                )
            )
            i = j
            continue

        groups.append(ContextMessageGroup(message_indices=(i,)))
        i += 1

    return tuple(groups)


def build_context_graph(
    messages: Sequence[Message],
    *,
    system_prompt: str | None = None,
) -> ContextGraph:
    """Compile messages and project them into a typed graph model."""
    compiled = compile_context_messages(
        messages,
        system_prompt=system_prompt,
    )
    compiled_messages = tuple(compiled.messages)

    return ContextGraph(
        messages=compiled_messages,
        edges=_build_edges(compiled_messages),
        groups=_build_groups(compiled_messages),
        diagnostics=compiled.diagnostics,
        invariant_report=compiled.invariant_report,
    )


__all__ = [
    "GraphEdgeKind",
    "ContextGraphEdge",
    "ContextMessageGroup",
    "ContextGraph",
    "build_context_graph",
]

