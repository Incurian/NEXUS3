"""Chat session coordinator for NEXUS3."""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nexus3.context.compaction import (
    CompactionResult,
    build_summarize_prompt,
    create_summary_message,
    select_messages_for_compaction,
)
from nexus3.core.errors import sanitize_error_for_agent
from nexus3.core.interfaces import AsyncProvider
from nexus3.core.permissions import AgentPermissions, ConfirmationResult
from nexus3.core.types import (
    ContentDelta,
    Message,
    ReasoningDelta,
    Role,
    StreamComplete,
    ToolCall,
    ToolCallStarted,
    ToolResult,
)
from nexus3.core.validation import ValidationError, validate_tool_arguments
from nexus3.session.confirmation import ConfirmationController
from nexus3.session.dispatcher import ToolDispatcher
from nexus3.session.enforcer import PermissionEnforcer
from nexus3.session.http_logging import clear_current_logger, set_current_logger
from nexus3.session.events import (
    ContentChunk,
    IterationCompleted,
    ReasoningEnded,
    ReasoningStarted,
    SessionCancelled,
    SessionCompleted,
    SessionEvent,
    ToolBatchCompleted,
    ToolBatchHalted,
    ToolBatchStarted,
    ToolCompleted,
    ToolDetected,
    ToolStarted,
)

if TYPE_CHECKING:
    from nexus3.config.schema import CompactionConfig, Config
    from nexus3.context.loader import ContextLoader
    from nexus3.context.manager import ContextManager
    from nexus3.core.cancel import CancellationToken
    from nexus3.session.logging import SessionLogger
    from nexus3.skill.base import Skill
    from nexus3.skill.registry import SkillRegistry
    from nexus3.skill.services import ServiceContainer

logger = logging.getLogger(__name__)

# Confirmation callback type - returns ConfirmationResult for allow once/always UI
# Args: (tool_call, target_path, agent_cwd) where agent_cwd is the agent's working directory
ConfirmationCallback = Callable[["ToolCall", "Path | None", "Path"], Awaitable[ConfirmationResult]]


# Callback types for notifications
ToolCallCallback = Callable[[str, str], None]  # (tool_name, tool_id) -> None
ToolCompleteCallback = Callable[[str, str, bool], None]  # (tool_name, tool_id, success) -> None
# (is_reasoning) -> None - True when starts, False when ends
ReasoningCallback = Callable[[bool], None]

# New batch-aware callback types
BatchStartCallback = Callable[["tuple[ToolCall, ...]"], None]  # All tools in batch
ToolActiveCallback = Callable[[str, str], None]  # (name, id) - tool starting execution
BatchProgressCallback = Callable[[str, str, bool, str, str], None]  # (name, id, success, error_msg, output)
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
        max_tool_iterations: int = 10,
        skill_timeout: float = 30.0,
        max_concurrent_tools: int = 10,
        services: "ServiceContainer | None" = None,
        on_confirm: ConfirmationCallback | None = None,
        config: "Config | None" = None,
        context_loader: "ContextLoader | None" = None,
        is_repl: bool = False,
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
            max_tool_iterations: Maximum iterations of the tool execution loop.
                               Prevents infinite loops. Default is 10.
            skill_timeout: Timeout in seconds for skill execution.
                          0 means no timeout. Default is 30.0.
            max_concurrent_tools: Maximum number of tools to execute in parallel.
                                 Default is 10.
            services: Optional ServiceContainer for accessing shared services
                     like permissions.
            on_confirm: Optional callback for requesting user confirmation on
                       destructive actions. Returns True if confirmed.
            config: Optional Config for compaction settings and other options.
            context_loader: Optional ContextLoader to reload system prompt during
                           compaction.
            is_repl: Whether running in REPL mode. Affects context loading during
                    compaction (REPL mode includes terminal info in environment).
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
        self.max_tool_iterations = max_tool_iterations
        self.skill_timeout = skill_timeout
        self._tool_semaphore = asyncio.Semaphore(max_concurrent_tools)
        self._services = services
        self.on_confirm = on_confirm
        self._config = config
        self._context_loader = context_loader
        self._is_repl = is_repl

        # Tool execution components
        self._dispatcher = ToolDispatcher(registry=registry, services=services)
        self._enforcer = PermissionEnforcer(services=services)
        self._confirmation = ConfirmationController()

        # Track cancelled tool calls to report on next send()
        self._pending_cancelled_tools: list[tuple[str, str]] = []  # [(tool_id, tool_name), ...]

        # Track tool iteration state for status reporting
        self._halted_at_iteration_limit: bool = False
        self._last_iteration_count: int = 0

        # Track last action timestamp (when agent took an action, not received messages)
        self._last_action_at: datetime | None = None

        # Lazy-loaded compaction provider (uses different model if configured)
        self._compaction_provider: AsyncProvider | None = None

    def _log_event(self, event: "SessionEvent") -> None:
        """Dispatch event to logger (DB always, verbose.md optional)."""
        if self.logger:
            self.logger.log_session_event(event)

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

    @property
    def halted_at_iteration_limit(self) -> bool:
        """Whether the last send() halted due to max tool iterations."""
        return self._halted_at_iteration_limit

    @property
    def last_iteration_count(self) -> int:
        """Number of tool iterations in the last send() call."""
        return self._last_iteration_count

    @property
    def last_action_at(self) -> datetime | None:
        """Timestamp of the last action taken by the agent (tool call or response)."""
        return self._last_action_at

    async def send(
        self,
        user_input: str,
        use_tools: bool = False,
        cancel_token: "CancellationToken | None" = None,
        user_meta: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        """Send a message and stream the response.

        If context is set, uses context for message history.
        Otherwise, single-turn mode (backwards compatible).

        Args:
            user_input: The user's message text.
            use_tools: If True, enable tool execution loop.
                      Automatically enabled if registry has tools.
            cancel_token: Optional cancellation token to cancel the operation.
            user_meta: Optional metadata for the user message (e.g., source attribution).

        Yields:
            String chunks of the assistant's response.
        """
        # Set current logger for HTTP debug routing to verbose.md
        if self.logger:
            set_current_logger(self.logger)

        try:
            if self.context:
                # Flush any cancelled tool results from previous turn
                self._flush_cancelled_tools()

                # Reset iteration state for this send()
                self._halted_at_iteration_limit = False
                self._last_iteration_count = 0

                # Multi-turn: use context manager
                self.context.add_user_message(user_input, meta=user_meta)

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
        finally:
            # Clear current logger after send completes
            clear_current_logger()

    async def run_turn(
        self,
        user_input: str,
        use_tools: bool = False,
        cancel_token: "CancellationToken | None" = None,
        user_meta: dict[str, Any] | None = None,
    ) -> AsyncIterator[SessionEvent]:
        """Send a message and yield events during processing.

        This is the event-based alternative to send(). Instead of using callbacks,
        it yields SessionEvent objects that can be processed by the caller.

        Args:
            user_input: The user's message text.
            use_tools: If True, enable tool execution loop. Default False but
                auto-enables if tools are registered.
            cancel_token: Optional cancellation token to cancel the operation.
            user_meta: Optional metadata for the user message (e.g., source attribution).

        Yields:
            SessionEvent objects for content, tool execution, and session lifecycle.
        """
        if not self.context:
            # Single-turn mode not supported for event-based streaming
            raise RuntimeError("run_turn() requires a context manager")

        # Set current logger for HTTP debug routing to verbose.md
        if self.logger:
            set_current_logger(self.logger)

        try:
            # Flush any cancelled tool results from previous turn
            self._flush_cancelled_tools()

            # Reset iteration state for this turn
            self._halted_at_iteration_limit = False
            self._last_iteration_count = 0

            # Add user message to context
            self.context.add_user_message(user_input, meta=user_meta)

            # Check if we should use tool mode
            has_tools = self.registry and self.registry.get_definitions()
            if use_tools or has_tools:
                # Use streaming tool execution loop with events
                async for event in self._execute_tool_loop_events(cancel_token):
                    yield event
                return

            # No tools - simple streaming mode
            messages = self.context.build_messages()
            tools = self.context.get_tool_definitions()

            final_message: Message | None = None
            async for stream_event in self.provider.stream(messages, tools):
                if isinstance(stream_event, ContentDelta):
                    yield ContentChunk(text=stream_event.text)
                    if cancel_token and cancel_token.is_cancelled:
                        yield SessionCancelled()
                        return
                elif isinstance(stream_event, ToolCallStarted):
                    yield ToolDetected(name=stream_event.name, tool_id=stream_event.id)
                elif isinstance(stream_event, StreamComplete):
                    final_message = stream_event.message

            # Store assistant response
            if final_message:
                self.context.add_assistant_message(
                    final_message.content, list(final_message.tool_calls)
                )

            yield SessionCompleted(halted_at_limit=False)
        finally:
            # Clear current logger after turn completes
            clear_current_logger()

    async def _execute_tool_loop_events(
        self, cancel_token: "CancellationToken | None" = None
    ) -> AsyncIterator[SessionEvent]:
        """Execute tools yielding events, not calling callbacks.

        This is the event-based version of _execute_tool_loop_streaming().
        Instead of calling callback functions, it yields SessionEvent objects.

        Args:
            cancel_token: Optional cancellation token to cancel the operation.

        Yields:
            SessionEvent objects for all tool execution lifecycle events.
        """
        for iteration_num in range(self.max_tool_iterations):
            self._last_iteration_count = iteration_num + 1

            # Check for compaction BEFORE build_messages() to avoid truncation
            if self._should_compact():
                compact_result = await self.compact(force=False)
                if compact_result:
                    saved = compact_result.original_token_count - compact_result.new_token_count
                    yield ContentChunk(
                        text=f"\n[Context compacted: {saved:,} tokens reclaimed]\n\n"
                    )

            # Type narrowing: run_turn() requires context, so it's guaranteed here
            assert self.context is not None
            messages = self.context.build_messages()
            tools = self.context.get_tool_definitions()

            # Stream response, accumulating content and detecting tool calls
            final_message: Message | None = None
            is_reasoning = False
            show_reasoning = False
            if self._services:
                from nexus3.config.schema import ResolvedModel
                resolved_model: ResolvedModel | None = self._services.get("model")
                if resolved_model:
                    show_reasoning = resolved_model.reasoning
            elif self._config:
                default_model = self._config.resolve_model()
                show_reasoning = default_model.reasoning

            async for event in self.provider.stream(messages, tools):
                if isinstance(event, ReasoningDelta):
                    if show_reasoning and not is_reasoning:
                        yield ReasoningStarted()
                    is_reasoning = True
                elif isinstance(event, ContentDelta):
                    if show_reasoning and is_reasoning:
                        yield ReasoningEnded()
                    is_reasoning = False
                    yield ContentChunk(text=event.text)
                    if cancel_token and cancel_token.is_cancelled:
                        yield SessionCancelled()
                        return
                elif isinstance(event, ToolCallStarted):
                    if show_reasoning and is_reasoning:
                        yield ReasoningEnded()
                    is_reasoning = False
                    yield ToolDetected(name=event.name, tool_id=event.id)
                elif isinstance(event, StreamComplete):
                    if show_reasoning and is_reasoning:
                        yield ReasoningEnded()
                    is_reasoning = False
                    final_message = event.message

            if final_message is None:
                yield SessionCompleted(halted_at_limit=False)
                return

            # Check cancellation before adding assistant message with tool_calls
            # This prevents orphaned tool_use blocks if cancelled during streaming
            if cancel_token and cancel_token.is_cancelled:
                yield SessionCancelled()
                return

            if final_message.tool_calls:
                # Add assistant message with tool calls
                self.context.add_assistant_message(
                    final_message.content, list(final_message.tool_calls)
                )

                # Check if parallel execution requested
                parallel = any(
                    tc.arguments.get("_parallel", False)
                    for tc in final_message.tool_calls
                )

                # Yield batch start event with parallel flag
                batch_start = ToolBatchStarted(
                    tool_calls=final_message.tool_calls, parallel=parallel
                )
                self._log_event(batch_start)
                yield batch_start

                if parallel:
                    if cancel_token and cancel_token.is_cancelled:
                        yield SessionCancelled()
                        return
                    # Parallel execution - all tools active at once
                    for tc in final_message.tool_calls:
                        tool_start = ToolStarted(name=tc.name, tool_id=tc.id)
                        self._log_event(tool_start)
                        yield tool_start
                    tool_results = await self._execute_tools_parallel(final_message.tool_calls)
                    for i, (tc, tool_result) in enumerate(
                        zip(final_message.tool_calls, tool_results, strict=True), start=1
                    ):
                        self.context.add_tool_result(
                            tc.id, tc.name, tool_result,
                            call_index=i, arguments=tc.arguments,
                        )
                        tool_complete = ToolCompleted(
                            name=tc.name,
                            tool_id=tc.id,
                            success=tool_result.success,
                            error=tool_result.error,
                            output=tool_result.output if tool_result.success else "",
                        )
                        self._log_event(tool_complete)
                        yield tool_complete
                else:
                    # Sequential execution - halts on first error or cancellation
                    error_index = -1
                    cancel_index = -1
                    for i, tc in enumerate(final_message.tool_calls):
                        # Check cancellation before starting each tool
                        if cancel_token and cancel_token.is_cancelled:
                            cancel_index = i
                            break
                        tool_start = ToolStarted(name=tc.name, tool_id=tc.id)
                        self._log_event(tool_start)
                        yield tool_start
                        # Handle mid-execution cancellation
                        try:
                            tool_result = await self._execute_single_tool(tc)
                        except asyncio.CancelledError:
                            # Tool was interrupted mid-execution
                            tool_result = ToolResult(
                                error="Cancelled by user: tool execution was interrupted"
                            )
                        self.context.add_tool_result(
                            tc.id, tc.name, tool_result,
                            call_index=i + 1, arguments=tc.arguments,
                        )
                        tool_complete = ToolCompleted(
                            name=tc.name,
                            tool_id=tc.id,
                            success=tool_result.success,
                            error=tool_result.error,
                            output=tool_result.output if tool_result.success else "",
                        )
                        self._log_event(tool_complete)
                        yield tool_complete
                        # Check cancellation after tool completes (for next iteration)
                        if cancel_token and cancel_token.is_cancelled:
                            cancel_index = i + 1  # This tool finished, cancel starts after
                            break
                        if not tool_result.success:
                            error_index = i
                            batch_halted = ToolBatchHalted()
                            self._log_event(batch_halted)
                            yield batch_halted
                            break

                    # Add cancelled results for remaining tools (ensures Anthropic
                    # API gets matching tool_result for every tool_use block)
                    if cancel_index >= 0:
                        for j, tc in enumerate(
                            final_message.tool_calls[cancel_index:],
                            start=cancel_index,
                        ):
                            cancelled_result = ToolResult(
                                error="Cancelled by user: tool execution was interrupted"
                            )
                            self.context.add_tool_result(
                                tc.id, tc.name, cancelled_result,
                                call_index=j + 1, arguments=tc.arguments,
                            )
                        yield SessionCancelled()
                        return

                    # Add halted results for remaining tools
                    if error_index >= 0:
                        for tc in final_message.tool_calls[error_index + 1:]:
                            halted_result = ToolResult(
                                error="Did not execute: halted due to error in previous tool"
                            )
                            self.context.add_tool_result(tc.id, tc.name, halted_result)

                # Yield batch complete and iteration complete
                batch_complete = ToolBatchCompleted()
                self._log_event(batch_complete)
                yield batch_complete
                yield IterationCompleted(
                    iteration=iteration_num + 1,
                    will_continue=True,
                )

                # Update last action timestamp
                self._last_action_at = datetime.now()
            else:
                # No tool calls - this is the final response
                self.context.add_assistant_message(final_message.content)
                self._last_action_at = datetime.now()

                # Check for auto-compaction after response
                if self._should_compact():
                    compact_result = await self.compact(force=False)
                    if compact_result:
                        saved = compact_result.original_token_count - compact_result.new_token_count
                        yield ContentChunk(
                            text=f"\n\n[Context compacted: {saved:,} tokens reclaimed]"
                        )

                yield SessionCompleted(halted_at_limit=False)
                return

        # Max iterations reached
        self._halted_at_iteration_limit = True
        yield ContentChunk(text="[Max tool iterations reached]")
        yield SessionCompleted(halted_at_limit=True)

    async def _execute_tool_loop_streaming(
        self, cancel_token: "CancellationToken | None" = None
    ) -> AsyncIterator[str]:
        """Execute tools with streaming, yielding content as it arrives.

        This method wraps the event-based _execute_tool_loop_events() and
        converts events back to callbacks for backward compatibility.

        Execution mode:
        - Default: Sequential (safe for dependent operations)
        - Parallel: If any tool call has "_parallel": true in arguments

        Args:
            cancel_token: Optional cancellation token to cancel the operation.

        Yields:
            String chunks of the assistant's response.
        """
        async for event in self._execute_tool_loop_events(cancel_token):
            # Convert events to callbacks and yield content
            if isinstance(event, ContentChunk):
                yield event.text
            elif isinstance(event, ReasoningStarted):
                if self.on_reasoning:
                    self.on_reasoning(True)
            elif isinstance(event, ReasoningEnded):
                if self.on_reasoning:
                    self.on_reasoning(False)
            elif isinstance(event, ToolDetected):
                if self.on_tool_call:
                    self.on_tool_call(event.name, event.tool_id)
            elif isinstance(event, ToolBatchStarted):
                if self.on_batch_start:
                    self.on_batch_start(event.tool_calls)
            elif isinstance(event, ToolStarted):
                if self.on_tool_active:
                    self.on_tool_active(event.name, event.tool_id)
            elif isinstance(event, ToolCompleted):
                if self.on_batch_progress:
                    self.on_batch_progress(
                        event.name, event.tool_id, event.success, event.error, event.output
                    )
                # Legacy callback (deprecated)
                if self.on_tool_complete:
                    self.on_tool_complete(event.name, event.tool_id, event.success)
            elif isinstance(event, ToolBatchHalted):
                if self.on_batch_halt:
                    self.on_batch_halt()
            elif isinstance(event, ToolBatchCompleted):
                if self.on_batch_complete:
                    self.on_batch_complete()
            # IterationCompleted and SessionCompleted are internal events
            # not mapped to callbacks in the original implementation

    async def _execute_single_tool(self, tool_call: "ToolCall") -> ToolResult:
        """Execute a single tool call with permission checks.

        Delegates to extracted components:
        - PermissionEnforcer: Permission checks (enabled, action, path)
        - ConfirmationController: User confirmation flow
        - ToolDispatcher: Skill resolution

        Args:
            tool_call: The tool call to execute.

        Returns:
            The tool result.
        """
        permissions = self._services.get_permissions() if self._services else None

        # Fail-closed: require permissions for tool execution (H3 fix)
        if permissions is None:
            return ToolResult(
                error="Tool execution denied: permissions not configured. "
                "This is a programming error - all Sessions should have permissions."
            )

        # 1. Permission checks (enabled, action allowed, path restrictions)
        error = self._enforcer.check_all(tool_call, permissions)
        if error:
            return error

        # 2. Check if confirmation needed
        if self._enforcer.requires_confirmation(tool_call, permissions):
            # Fix 1.2: Get display path and ALL write paths for multi-path tools
            display_path, write_paths = self._enforcer.get_confirmation_context(tool_call)
            exec_cwd = self._enforcer.extract_exec_cwd(tool_call)
            agent_cwd = self._services.get_cwd() if self._services else Path.cwd()

            # Show confirmation for the write target (display_path)
            result = await self._confirmation.request(
                tool_call, display_path, agent_cwd, self.on_confirm
            )

            if result == ConfirmationResult.DENY:
                return ToolResult(error="Action cancelled by user")

            # Fix 1.2: Apply allowance to ALL write paths (e.g., destination for copy_file)
            if permissions and write_paths:
                for write_path in write_paths:
                    self._confirmation.apply_result(
                        permissions, result, tool_call, write_path, exec_cwd
                    )
            elif permissions:
                # Fallback for tools without explicit write paths (e.g., exec tools)
                self._confirmation.apply_result(
                    permissions, result, tool_call, display_path, exec_cwd
                )

        # 3. Resolve skill
        skill, mcp_server_name = self._dispatcher.find_skill(tool_call)

        # 4. MCP permission check and confirmation (if MCP skill)
        if mcp_server_name and permissions:
            error = await self._handle_mcp_permissions(
                tool_call, skill, mcp_server_name, permissions
            )
            if error:
                return error

        # 5. Unknown skill check
        if not skill:
            logger.debug("Unknown skill requested: %s", tool_call.name)
            return ToolResult(error=f"Unknown skill: {tool_call.name}")

        # 6. Validate arguments
        try:
            args = validate_tool_arguments(
                tool_call.arguments,
                skill.parameters,
                logger=self.logger,
            )
        except ValidationError as e:
            return ToolResult(error=f"Invalid arguments for {tool_call.name}: {e.message}")

        # 7. Execute with timeout
        effective_timeout = self._enforcer.get_effective_timeout(
            tool_call.name, permissions, self.skill_timeout
        )

        return await self._execute_skill(skill, args, effective_timeout)

    async def _handle_mcp_permissions(
        self,
        tool_call: "ToolCall",
        skill: "Skill | None",
        server_name: str,
        permissions: AgentPermissions,
    ) -> ToolResult | None:
        """Handle MCP-specific permission checks and confirmation.

        Args:
            tool_call: The MCP tool call.
            skill: The resolved MCP skill (may be None).
            server_name: MCP server name.
            permissions: Agent permissions.

        Returns:
            ToolResult with error if permission denied, None if allowed.
        """
        from nexus3.core.permissions import PermissionLevel
        from nexus3.mcp.permissions import can_use_mcp

        # Check MCP permission level
        if not can_use_mcp(permissions):
            return ToolResult(error="MCP tools require TRUSTED or YOLO permission level")

        if not skill:
            return None  # Let caller handle unknown skill

        # Check if confirmation needed for this MCP tool/server
        level = permissions.effective_policy.level
        if level != PermissionLevel.YOLO:
            allowances = permissions.session_allowances
            server_allowed = allowances.is_mcp_server_allowed(server_name)
            tool_allowed = allowances.is_mcp_tool_allowed(tool_call.name)

            if not server_allowed and not tool_allowed:
                agent_cwd = self._services.get_cwd() if self._services else Path.cwd()
                result = await self._confirmation.request(
                    tool_call, None, agent_cwd, self.on_confirm
                )

                if result == ConfirmationResult.DENY:
                    return ToolResult(error="MCP tool action denied by user")

                self._confirmation.apply_mcp_result(
                    permissions, result, tool_call.name, server_name
                )

        return None

    async def _execute_skill(
        self,
        skill: "Skill",
        args: dict[str, Any],
        timeout: float,
    ) -> ToolResult:
        """Execute a skill with timeout.

        Args:
            skill: The skill to execute.
            args: Validated arguments.
            timeout: Timeout in seconds (0 = no timeout).

        Returns:
            The tool result.
        """
        try:
            if timeout > 0:
                result = await asyncio.wait_for(
                    skill.execute(**args),
                    timeout=timeout,
                )
            else:
                result = await skill.execute(**args)

            if result.error:
                # Log full error for debugging (debug level to avoid Live display artifacts)
                logger.debug("Skill '%s' returned error: %s", skill.name, result.error)
                # Sanitize for agent
                sanitized_error = sanitize_error_for_agent(result.error, skill.name)
                if sanitized_error != result.error:
                    logger.debug("Sanitized error for agent: %s", sanitized_error)
                    result = ToolResult(output=result.output, error=sanitized_error)

            return result
        except TimeoutError:
            logger.debug("Skill '%s' timed out after %ss", skill.name, timeout)
            return ToolResult(error=f"Skill timed out after {timeout}s")
        except Exception as e:
            logger.debug("Skill '%s' raised exception: %s", skill.name, e, exc_info=True)
            raw = f"Skill execution error: {e}"
            safe = sanitize_error_for_agent(raw, skill.name)
            return ToolResult(error=safe or "Skill execution error")

    async def _execute_tools_parallel(
        self, tool_calls: "tuple[ToolCall, ...]"
    ) -> list[ToolResult]:
        """Execute multiple tool calls in parallel.

        Uses a semaphore to limit concurrency to max_concurrent_tools.

        Args:
            tool_calls: The tool calls to execute.

        Returns:
            List of tool results in the same order as tool_calls.
        """
        async def execute_one(tc: "ToolCall") -> ToolResult:
            async with self._tool_semaphore:
                return await self._execute_single_tool(tc)

        results = await asyncio.gather(
            *[execute_one(tc) for tc in tool_calls],
            return_exceptions=True,
        )

        # Convert exceptions to ToolResults
        final_results: list[ToolResult] = []
        for r in results:
            if isinstance(r, Exception):
                raw = f"Execution error: {r}"
                safe = sanitize_error_for_agent(raw, "")
                final_results.append(ToolResult(error=safe or "Execution error"))
            else:
                final_results.append(r)

        return final_results

    # === Context Compaction ===

    def _should_compact(self) -> bool:
        """Check if context should be compacted based on token threshold.

        Returns:
            True if compaction should be triggered, False otherwise.
        """
        if self._config is None:
            return False

        compaction_config = self._config.compaction
        if not compaction_config.enabled:
            return False

        if self.context is None:
            return False

        usage = self.context.get_token_usage()
        threshold = int(usage["available"] * compaction_config.trigger_threshold)

        return usage["total"] > threshold

    async def compact(self, force: bool = False) -> CompactionResult | None:
        """Compact context by summarizing old messages.

        Args:
            force: If True, compact even if under threshold

        Returns:
            CompactionResult if compaction occurred, None otherwise
        """
        if not force and not self._should_compact():
            return None

        if self.context is None:
            return None

        messages = self.context.messages
        if len(messages) < 2:
            return None

        if self._config is None:
            return None

        usage = self.context.get_token_usage()
        compaction_config = self._config.compaction

        # Select messages to summarize vs preserve
        to_summarize, to_preserve = select_messages_for_compaction(
            messages=messages,
            token_counter=self.context._counter,
            available_budget=usage["available"],
            recent_preserve_ratio=compaction_config.recent_preserve_ratio,
        )

        if not to_summarize:
            return None

        # Generate summary via LLM
        summary_text = await self._generate_summary(to_summarize, compaction_config)
        summary_message = create_summary_message(summary_text)

        # Reload system prompt fresh (picks up NEXUS.md changes)
        new_system_prompt = None
        if self._context_loader:
            loaded = self._context_loader.load(is_repl=self._is_repl)
            new_system_prompt = loaded.system_prompt

        # Calculate token counts
        original_tokens = usage["messages"]

        # Apply to context
        self.context.apply_compaction(summary_message, to_preserve, new_system_prompt)

        new_usage = self.context.get_token_usage()

        return CompactionResult(
            summary_message=summary_message,
            preserved_messages=to_preserve,
            original_token_count=original_tokens,
            new_token_count=new_usage["messages"],
        )

    def _get_compaction_provider(self) -> AsyncProvider:
        """Get or create the provider for compaction.

        If compaction.model is configured, creates a separate provider with that model.
        Otherwise uses the main provider.

        Returns:
            Provider for compaction requests.
        """
        if self._compaction_provider is not None:
            return self._compaction_provider

        if self._config is None:
            return self.provider

        compaction_model = self._config.compaction.model
        if compaction_model is None:
            # No separate model configured, use main provider
            return self.provider

        # Resolve compaction model alias to get provider and model_id
        from nexus3.provider import create_provider

        resolved = self._config.resolve_model(compaction_model)
        provider_config = self._config.get_provider_config(resolved.provider_name)
        self._compaction_provider = create_provider(
            provider_config, resolved.model_id
        )
        return self._compaction_provider

    async def _generate_summary(
        self, messages: list[Message], compaction_config: "CompactionConfig"
    ) -> str:
        """Generate summary of messages via LLM call.

        Args:
            messages: Messages to summarize
            compaction_config: Compaction configuration

        Returns:
            Summary text
        """
        prompt = build_summarize_prompt(messages)

        # Build minimal message for summarization
        summary_messages = [
            Message(role=Role.USER, content=prompt)
        ]

        # Set current logger for HTTP debug routing to verbose.md
        if self.logger:
            set_current_logger(self.logger)

        try:
            # Use compaction provider (may be different model than main)
            provider = self._get_compaction_provider()
            response = await provider.complete(summary_messages, tools=None)

            return response.content
        finally:
            clear_current_logger()
