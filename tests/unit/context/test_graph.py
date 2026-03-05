"""Tests for compiler-backed context graph projection."""

from nexus3.context.graph import GraphEdgeKind, build_context_graph
from nexus3.core.types import Message, Role, ToolCall


def test_build_context_graph_adds_next_and_tool_result_edges() -> None:
    messages = [
        Message(role=Role.USER, content="start"),
        Message(
            role=Role.ASSISTANT,
            content="running tools",
            tool_calls=(
                ToolCall(id="tc1", name="read_file", arguments={"path": "a.txt"}),
                ToolCall(id="tc2", name="read_file", arguments={"path": "b.txt"}),
            ),
        ),
        Message(role=Role.TOOL, content="a", tool_call_id="tc1"),
        Message(role=Role.TOOL, content="b", tool_call_id="tc2"),
        Message(role=Role.ASSISTANT, content="done"),
    ]

    graph = build_context_graph(messages)
    assert graph.invariant_report.ok

    next_edges = [edge for edge in graph.edges if edge.kind == GraphEdgeKind.NEXT]
    assert len(next_edges) == len(graph.messages) - 1

    tool_edges = graph.outgoing(1, kind=GraphEdgeKind.TOOL_RESULT)
    assert [edge.tool_call_id for edge in tool_edges] == ["tc1", "tc2"]
    assert [edge.target_index for edge in tool_edges] == [2, 3]

    assert [group.message_indices for group in graph.groups] == [
        (0,),
        (1, 2, 3),
        (4,),
    ]
    assert graph.groups[1].includes_tool_batch is True


def test_build_context_graph_repairs_missing_results_before_projection() -> None:
    messages = [
        Message(role=Role.USER, content="do work"),
        Message(
            role=Role.ASSISTANT,
            content="",
            tool_calls=(
                ToolCall(id="tc1", name="read_file", arguments={"path": "a.txt"}),
                ToolCall(id="tc2", name="read_file", arguments={"path": "b.txt"}),
            ),
        ),
        Message(role=Role.TOOL, content="a", tool_call_id="tc1"),
    ]

    graph = build_context_graph(messages)
    assert graph.invariant_report.ok
    assert graph.diagnostics.synthesized_tool_results == 1
    assert graph.diagnostics.appended_assistant_after_tool_results is True

    tool_edges = graph.outgoing(1, kind=GraphEdgeKind.TOOL_RESULT)
    assert {edge.tool_call_id for edge in tool_edges} == {"tc1", "tc2"}

    synthesized_tool_message = next(
        msg
        for msg in graph.messages
        if msg.role == Role.TOOL and msg.tool_call_id == "tc2"
    )
    assert "Cancelled by user" in synthesized_tool_message.content


def test_build_context_graph_prunes_orphan_tool_messages() -> None:
    graph = build_context_graph(
        [Message(role=Role.TOOL, content="orphan", tool_call_id="tc-orphan")]
    )

    assert graph.messages == ()
    assert graph.edges == ()
    assert graph.groups == ()
    assert graph.diagnostics.pruned_tool_results == 1
    assert graph.invariant_report.ok


def test_build_context_graph_keeps_single_system_prompt_instance() -> None:
    graph = build_context_graph(
        [
            Message(role=Role.SYSTEM, content="sys"),
            Message(role=Role.USER, content="hello"),
        ],
        system_prompt="sys",
    )

    assert [msg.role for msg in graph.messages] == [Role.SYSTEM, Role.USER]
    assert [msg.content for msg in graph.messages] == ["sys", "hello"]
