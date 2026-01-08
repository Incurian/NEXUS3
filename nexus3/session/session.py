"""Chat session coordinator for NEXUS3."""

from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING

from nexus3.core.interfaces import AsyncProvider
from nexus3.core.types import (
    ContentDelta,
    Message,
    ReasoningDelta,
    Role,
    StreamComplete,
    ToolCallStarted,
    ToolResult,
)

if TYPE_CHECKING:
    from nexus3.context.manager import ContextManager
    from nexus3.core.cancel import CancellationToken
    from nexus3.core.types import ToolCall
    from nexus3.session.logging import SessionLogger
    from nexus3.skill.registry import SkillRegistry


# Callback types for notifications
ToolCallCallback = Callable[[str, str], None]  # (tool_name, tool_id) -> None
ToolCompleteCallback = Callable[[str, str, bool], None]  # (tool_name, tool_id, success) -> None
ReasoningCallback = Callable[[bool], None]  # (is_reasoning) -> None - True when starts, False when ends

# New batch-aware callback types
BatchStartCallback = Callable[["tuple[ToolCall, ...]"], None]  # All tools in batch
ToolActiveCallback = Callable[[str, str], None]  # (name, id) - tool starting execution
BatchProgressCallback = Callable[[str, str, bool, str], None]  # (name, id, success, error_msg)
BatchHaltCallback = Callable[[], None]  # Sequential batch halted due to error
BatchCompleteCallback = Callable[[], None]  # All tools in batch finished


class Session:
    """Coordinator between CLI and LLM provider.

    Works with ContextManager to maintain conversation history
    and handle multi-turn conversations.
    """

    def __init__(
        self,
        provider: AsyncProvider,
        context: "ContextManager | None" = None,
        logger: "SessionLogger | None" = None,
        registry: "SkillRegistry | None" = None,
        on_tool_call: ToolCallCallback | None = None,
        on_tool_complete: ToolCompleteCallback | None = None,
        on_reasoning: ReasoningCallback | None = None,
        on_batch_start: BatchStartCallback | None = None,
        on_tool_active: ToolActiveCallback | None = None,
        on_batch_progress: BatchProgressCallback | None = None,
        on_batch_halt: BatchHaltCallback | None = None,
        on_batch_complete: BatchCompleteCallback | None = None,
    ) -> None:
        """Initialize a new session.

        Args:
            provider: The async LLM provider for completions.
            context: Optional ContextManager for multi-turn conversations.
                    If None, each send() is single-turn (no history).
            logger: Optional session logger (used if context doesn't have one).
            registry: Optional SkillRegistry for tool execution.
            on_tool_call: Optional callback when a tool call is detected in stream.
                         Called with (tool_name, tool_id) for immediate display.
            on_tool_complete: Optional callback when a tool finishes executing.
                             Called with (tool_name, tool_id, success).
            on_reasoning: Optional callback when reasoning state changes.
                         Called with True when reasoning starts, False when it ends.
            on_batch_start: Optional callback when a batch of tools is about to execute.
                           Called with tuple of all ToolCalls in the batch.
            on_tool_active: Optional callback when a tool starts executing.
                           Called with (name, id).
            on_batch_progress: Optional callback when a tool in batch completes.
                              Called with (name, id, success, error_msg).
            on_batch_halt: Optional callback when sequential batch halts on error.
                          Called to mark remaining tools as halted.
            on_batch_complete: Optional callback when all tools in batch are done.
        """
        self.provider = provider
        self.context = context
        self.logger = logger
        self.registry = registry
        self.on_tool_call = on_tool_call
        self.on_tool_complete = on_tool_complete
        self.on_reasoning = on_reasoning
        self.on_batch_start = on_batch_start
        self.on_tool_active = on_tool_active
        self.on_batch_progress = on_batch_progress
        self.on_batch_halt = on_batch_halt
        self.on_batch_complete = on_batch_complete

        # Track cancelled tool calls to report on next send()
        self._pending_cancelled_tools: list[tuple[str, str]] = []  # [(tool_id, tool_name), ...]

    def add_cancelled_tools(self, tools: list[tuple[str, str]]) -> None:
        """Store cancelled tool calls to report on next send().

        Args:
            tools: List of (tool_id, tool_name) tuples that were cancelled.
        """
        self._pending_cancelled_tools.extend(tools)

    def _flush_cancelled_tools(self) -> None:
        """Add cancelled tool results to context and clear pending list."""
        if not self._pending_cancelled_tools or not self.context:
            self._pending_cancelled_tools.clear()
            return

        for tool_id, tool_name in self._pending_cancelled_tools:
            cancelled_result = ToolResult(
                error="Cancelled by user: tool execution was interrupted"
            )
            self.context.add_tool_result(tool_id, tool_name, cancelled_result)

        self._pending_cancelled_tools.clear()

    async def send(
        self,
        user_input: str,
        use_tools: bool = False,
        cancel_token: "CancellationToken | None" = None,
    ) -> AsyncIterator[str]:
        """Send a message and stream the response.

        If context is set, uses context for message history.
        Otherwise, single-turn mode (backwards compatible).

        Args:
            user_input: The user's message text.
            use_tools: If True, enable tool execution loop.
                      Automatically enabled if registry has tools.
            cancel_token: Optional cancellation token to cancel the operation.

        Yields:
            String chunks of the assistant's response.
        """
        if self.context:
            # Flush any cancelled tool results from previous turn
            self._flush_cancelled_tools()

            # Multi-turn: use context manager
            self.context.add_user_message(user_input)

            # Check if we should use tool mode
            has_tools = self.registry and self.registry.get_definitions()
            if use_tools or has_tools:
                # Use streaming tool execution loop
                async for chunk in self._execute_tool_loop_streaming(cancel_token):
                    yield chunk
                return

            messages = self.context.build_messages()
            tools = self.context.get_tool_definitions()
        else:
            # Single-turn: build messages directly (backwards compatible)
            if self.logger:
                self.logger.log_user(user_input)
            messages = [Message(role=Role.USER, content=user_input)]
            tools = None

        # Stream response from provider using new event-based interface
        final_message: Message | None = None
        async for event in self.provider.stream(messages, tools):
            if isinstance(event, ContentDelta):
                yield event.text
                if cancel_token and cancel_token.is_cancelled:
                    return
            elif isinstance(event, ToolCallStarted):
                # Notify callback if set (for display updates)
                if self.on_tool_call:
                    self.on_tool_call(event.name, event.id)
            elif isinstance(event, StreamComplete):
                final_message = event.message

        # Log/store assistant response
        if final_message:
            if self.context:
                self.context.add_assistant_message(
                    final_message.content, list(final_message.tool_calls)
                )
            elif self.logger:
                self.logger.log_assistant(final_message.content)

    async def _execute_tool_loop_streaming(
        self, cancel_token: "CancellationToken | None" = None
    ) -> AsyncIterator[str]:
        """Execute tools with streaming, yielding content as it arrives.

        This method handles the complete tool execution loop with streaming:
        1. Stream response from provider
        2. Yield content chunks as they arrive
        3. If tool_calls in final message, execute them
        4. Add results to context and repeat
        5. Return when no more tool calls

        Execution mode:
        - Default: Sequential (safe for dependent operations)
        - Parallel: If any tool call has "_parallel": true in arguments

        Args:
            cancel_token: Optional cancellation token to cancel the operation.

        Yields:
            String chunks of the assistant's response.
        """

        max_iterations = 10  # Prevent infinite loops

        for _ in range(max_iterations):
            messages = self.context.build_messages()
            tools = self.registry.get_definitions() if self.registry else None

            # Stream response, accumulating content and detecting tool calls
            final_message: Message | None = None
            is_reasoning = False  # Track if we're in reasoning mode
            async for event in self.provider.stream(messages, tools):
                if isinstance(event, ReasoningDelta):
                    # Notify callback when reasoning starts
                    if not is_reasoning and self.on_reasoning:
                        self.on_reasoning(True)
                    is_reasoning = True
                elif isinstance(event, ContentDelta):
                    # Notify callback when reasoning ends (transition to content)
                    if is_reasoning and self.on_reasoning:
                        self.on_reasoning(False)
                        is_reasoning = False
                    yield event.text
                    if cancel_token and cancel_token.is_cancelled:
                        return
                elif isinstance(event, ToolCallStarted):
                    # End reasoning if we were reasoning
                    if is_reasoning and self.on_reasoning:
                        self.on_reasoning(False)
                        is_reasoning = False
                    # Notify callback if set (for display updates)
                    if self.on_tool_call:
                        self.on_tool_call(event.name, event.id)
                elif isinstance(event, StreamComplete):
                    # End reasoning if stream completes while still reasoning
                    if is_reasoning and self.on_reasoning:
                        self.on_reasoning(False)
                        is_reasoning = False
                    final_message = event.message

            if final_message is None:
                # Should not happen, but handle gracefully
                return

            if final_message.tool_calls:
                # Add assistant message with tool calls
                self.context.add_assistant_message(
                    final_message.content, list(final_message.tool_calls)
                )

                # Notify batch start with all tool calls
                if self.on_batch_start:
                    self.on_batch_start(final_message.tool_calls)

                # Check if parallel execution requested
                parallel = any(
                    tc.arguments.get("_parallel", False)
                    for tc in final_message.tool_calls
                )

                # Collect results for batch completion
                batch_results: list[tuple[ToolCall, ToolResult]] = []

                if parallel:
                    # Check for cancellation before parallel execution
                    if cancel_token and cancel_token.is_cancelled:
                        return
                    # Parallel execution - all tools active at once
                    if self.on_tool_active:
                        for tc in final_message.tool_calls:
                            self.on_tool_active(tc.name, tc.id)
                    results = await self._execute_tools_parallel(final_message.tool_calls)
                    for tc, result in zip(final_message.tool_calls, results):
                        self.context.add_tool_result(tc.id, tc.name, result)
                        batch_results.append((tc, result))
                        # Progress callback for each completed tool
                        if self.on_batch_progress:
                            self.on_batch_progress(tc.name, tc.id, result.success, result.error)
                        # Legacy callback (deprecated)
                        if self.on_tool_complete:
                            self.on_tool_complete(tc.name, tc.id, result.success)
                else:
                    # Sequential execution (default - safe for dependent ops)
                    # Halts on first error
                    error_index = -1
                    for i, tc in enumerate(final_message.tool_calls):
                        # Check for cancellation before executing each tool
                        if cancel_token and cancel_token.is_cancelled:
                            return
                        # Mark tool as active before executing
                        if self.on_tool_active:
                            self.on_tool_active(tc.name, tc.id)
                        result = await self._execute_single_tool(tc)
                        self.context.add_tool_result(tc.id, tc.name, result)
                        batch_results.append((tc, result))
                        # Progress callback for each completed tool
                        if self.on_batch_progress:
                            self.on_batch_progress(tc.name, tc.id, result.success, result.error)
                        # Legacy callback (deprecated)
                        if self.on_tool_complete:
                            self.on_tool_complete(tc.name, tc.id, result.success)
                        # Stop on error for sequential execution
                        if not result.success:
                            error_index = i
                            # Mark remaining tools as halted
                            if self.on_batch_halt:
                                self.on_batch_halt()
                            break

                    # Add halted results for remaining tools
                    if error_index >= 0:
                        for tc in final_message.tool_calls[error_index + 1:]:
                            halted_result = ToolResult(
                                error="Did not execute: halted due to error in previous tool"
                            )
                            self.context.add_tool_result(tc.id, tc.name, halted_result)
                            batch_results.append((tc, halted_result))

                # Notify batch complete
                if self.on_batch_complete:
                    self.on_batch_complete()
            else:
                # No tool calls - this is the final response
                self.context.add_assistant_message(final_message.content)
                return

        # Max iterations reached
        yield "[Max tool iterations reached]"

    async def _execute_single_tool(self, tool_call: "ToolCall") -> ToolResult:
        """Execute a single tool call.

        Args:
            tool_call: The tool call to execute.

        Returns:
            The tool result.
        """
        skill = self.registry.get(tool_call.name) if self.registry else None
        if not skill:
            return ToolResult(error=f"Unknown skill: {tool_call.name}")

        # Strip internal arguments before passing to skill
        args = {k: v for k, v in tool_call.arguments.items() if not k.startswith("_")}

        try:
            return await skill.execute(**args)
        except Exception as e:
            return ToolResult(error=f"Skill execution error: {e}")

    async def _execute_tools_parallel(
        self, tool_calls: "tuple[ToolCall, ...]"
    ) -> list[ToolResult]:
        """Execute multiple tool calls in parallel.

        Args:
            tool_calls: The tool calls to execute.

        Returns:
            List of tool results in the same order as tool_calls.
        """
        import asyncio

        async def execute_one(tc: "ToolCall") -> ToolResult:
            return await self._execute_single_tool(tc)

        results = await asyncio.gather(
            *[execute_one(tc) for tc in tool_calls],
            return_exceptions=True,
        )

        # Convert exceptions to ToolResults
        final_results: list[ToolResult] = []
        for r in results:
            if isinstance(r, Exception):
                final_results.append(ToolResult(error=f"Execution error: {r}"))
            else:
                final_results.append(r)

        return final_results
