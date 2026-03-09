"""Chat session coordinator for NEXUS3."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nexus3.context.compaction import (
    CompactionResult,
    create_summary_message,
    select_messages_for_compaction,
)
from nexus3.context.compiler import compile_context_messages
from nexus3.core.authorization_kernel import (
    AdapterAuthorizationKernel,
)
from nexus3.core.interfaces import AsyncProvider
from nexus3.core.permissions import AgentPermissions, ConfirmationResult
from nexus3.core.types import (
    ContentDelta,
    Message,
    Role,
    StreamComplete,
    ToolCall,
    ToolCallStarted,
    ToolResult,
)
from nexus3.session.compaction_runtime import (
    generate_summary as generate_compaction_summary,
)
from nexus3.session.compaction_runtime import (
    get_compaction_provider as get_compaction_provider_runtime,
)
from nexus3.session.confirmation import ConfirmationController
from nexus3.session.dispatcher import ToolDispatcher
from nexus3.session.enforcer import PermissionEnforcer
from nexus3.session.events import (
    ContentChunk,
    SessionCancelled,
    SessionCompleted,
    SessionEvent,
    ToolDetected,
)
from nexus3.session.http_logging import clear_current_logger, set_current_logger
from nexus3.session.permission_runtime import (
    _GitLabLevelAuthorizationAdapter,
    _McpLevelAuthorizationAdapter,
)
from nexus3.session.permission_runtime import (
    handle_gitlab_permissions as handle_gitlab_permissions_runtime,
)
from nexus3.session.permission_runtime import (
    handle_mcp_permissions as handle_mcp_permissions_runtime,
)
from nexus3.session.single_tool_runtime import (
    execute_single_tool as execute_single_tool_runtime,
)
from nexus3.session.streaming_runtime import (
    execute_tool_loop_streaming as execute_tool_loop_streaming_runtime,
)
from nexus3.session.tool_loop_events_runtime import (
    execute_tool_loop_events as execute_tool_loop_events_runtime,
)
from nexus3.session.tool_runtime import (
    execute_skill as execute_skill_runtime,
)
from nexus3.session.tool_runtime import (
    execute_tools_parallel as execute_tools_parallel_runtime,
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
# (name, id, success, error_msg, output)
BatchProgressCallback = Callable[[str, str, bool, str, str], None]
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
        self._mcp_authorization_kernel = AdapterAuthorizationKernel(
            adapters=(_McpLevelAuthorizationAdapter(),),
            default_allow=False,
        )
        self._gitlab_authorization_kernel = AdapterAuthorizationKernel(
            adapters=(_GitLabLevelAuthorizationAdapter(),),
            default_allow=False,
        )

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

    def _log_provider_preflight(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        dynamic_context: str | None,
        *,
        path: str,
    ) -> None:
        """Emit a compact role-sequence snapshot before provider calls."""
        if not self.logger:
            return

        snapshot: list[dict[str, Any]] = []
        for i, msg in enumerate(messages):
            row: dict[str, Any] = {
                "i": i,
                "role": msg.role.value,
                "content_len": len(msg.content),
            }
            if msg.tool_call_id:
                row["tool_call_id"] = msg.tool_call_id
            if msg.tool_calls:
                row["tool_calls"] = [{"id": tc.id, "name": tc.name} for tc in msg.tool_calls]
            snapshot.append(row)

        preflight = {
            "path": path,
            "message_count": len(messages),
            "tool_count": len(tools or []),
            "dynamic_context_len": len(dynamic_context) if dynamic_context else 0,
            "messages": snapshot,
        }
        self.logger.log_http_debug("session.preflight", json.dumps(preflight))

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

        # Only flush cancelled results for tool IDs that are still expected by
        # an assistant tool_calls batch and do not already have a result.
        expected_ids: set[str] = set()
        found_result_ids: set[str] = set()
        for msg in self.context.messages:
            if msg.role == Role.ASSISTANT and msg.tool_calls:
                expected_ids.update(tc.id for tc in msg.tool_calls)
            elif msg.role == Role.TOOL and msg.tool_call_id:
                found_result_ids.add(msg.tool_call_id)

        valid_ids = expected_ids - found_result_ids
        for tool_id, tool_name in self._pending_cancelled_tools:
            if tool_id not in valid_ids:
                logger.debug(
                    "Dropping stale cancelled tool result without matching "
                    "assistant tool_call: %s (%s)",
                    tool_id,
                    tool_name,
                )
                continue
            cancelled_result = ToolResult(
                error="Cancelled by user: tool execution was interrupted"
            )
            self.context.add_tool_result(tool_id, tool_name, cancelled_result)

        self._pending_cancelled_tools.clear()

    def _normalize_context_preflight(self, *, path: str) -> None:
        """Repair context history through compiler invariants before new user turns."""
        if not self.context:
            return

        compiled = compile_context_messages(
            self.context.messages,
            system_prompt=None,
        )
        self.context.replace_messages(list(compiled.messages))

        diagnostics = compiled.diagnostics
        changed = (
            diagnostics.pruned_tool_results > 0
            or diagnostics.synthesized_tool_results > 0
            or diagnostics.appended_assistant_after_tool_results
        )
        if changed:
            logger.warning(
                "Compiler preflight repaired context "
                "(path=%s, pruned=%d, synthesized=%d, appended=%s)",
                path,
                diagnostics.pruned_tool_results,
                diagnostics.synthesized_tool_results,
                diagnostics.appended_assistant_after_tool_results,
            )

        if diagnostics.invariant_errors:
            logger.warning(
                "Compiler preflight left invariant violations (path=%s): %s",
                path,
                list(diagnostics.invariant_errors),
            )

        if self.logger:
            payload = {
                "path": path,
                "pruned_tool_results": diagnostics.pruned_tool_results,
                "synthesized_tool_results": diagnostics.synthesized_tool_results,
                "appended_assistant_after_tool_results": (
                    diagnostics.appended_assistant_after_tool_results
                ),
                "invariant_error_count": len(diagnostics.invariant_errors),
            }
            self.logger.log_http_debug(
                "session.compiler_preflight",
                json.dumps(payload),
            )

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
                # Normalize context through compiler-backed invariants before
                # appending the next user turn.
                self._normalize_context_preflight(path="send.pre_user")

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
                dynamic_context = self.context.build_dynamic_context()
            else:
                # Single-turn: build messages directly (backwards compatible)
                if self.logger:
                    self.logger.log_user(user_input)
                messages = [Message(role=Role.USER, content=user_input)]
                tools = None
                dynamic_context = None

            # Stream response from provider using new event-based interface
            final_message: Message | None = None
            self._log_provider_preflight(
                messages, tools, dynamic_context, path="send.simple",
            )
            async for event in self.provider.stream(
                messages, tools, dynamic_context=dynamic_context,
            ):
                if cancel_token and cancel_token.is_cancelled:
                    return
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

            # If cancellation arrived mid-stream before StreamComplete,
            # exit quietly instead of treating as empty provider output.
            if cancel_token and cancel_token.is_cancelled:
                return

            # Log/store assistant response
            if final_message:
                if not final_message.content and not final_message.tool_calls:
                    yield "[Provider returned an empty response]"
                elif self.context:
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
            # Normalize context through compiler-backed invariants before
            # appending the next user turn.
            self._normalize_context_preflight(path="run_turn.pre_user")

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
            dynamic_context = self.context.build_dynamic_context()

            final_message: Message | None = None
            self._log_provider_preflight(
                messages, tools, dynamic_context, path="run_turn.simple",
            )
            async for stream_event in self.provider.stream(
                messages, tools, dynamic_context=dynamic_context,
            ):
                if cancel_token and cancel_token.is_cancelled:
                    yield SessionCancelled()
                    return
                if isinstance(stream_event, ContentDelta):
                    yield ContentChunk(text=stream_event.text)
                    if cancel_token and cancel_token.is_cancelled:
                        yield SessionCancelled()
                        return
                elif isinstance(stream_event, ToolCallStarted):
                    yield ToolDetected(name=stream_event.name, tool_id=stream_event.id)
                elif isinstance(stream_event, StreamComplete):
                    final_message = stream_event.message

            if cancel_token and cancel_token.is_cancelled:
                yield SessionCancelled()
                return

            # Store assistant response
            if final_message:
                if not final_message.content and not final_message.tool_calls:
                    yield ContentChunk(text="[Provider returned an empty response]")
                else:
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
        async for event in execute_tool_loop_events_runtime(
            self,
            cancel_token=cancel_token,
        ):
            yield event

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
        async for chunk in execute_tool_loop_streaming_runtime(
            execute_tool_loop_events=self._execute_tool_loop_events,
            cancel_token=cancel_token,
            on_tool_call=self.on_tool_call,
            on_tool_complete=self.on_tool_complete,
            on_reasoning=self.on_reasoning,
            on_batch_start=self.on_batch_start,
            on_tool_active=self.on_tool_active,
            on_batch_progress=self.on_batch_progress,
            on_batch_halt=self.on_batch_halt,
            on_batch_complete=self.on_batch_complete,
        ):
            yield chunk

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
        return await execute_single_tool_runtime(
            tool_call=tool_call,
            services=self._services,
            enforcer=self._enforcer,
            confirmation=self._confirmation,
            dispatcher=self._dispatcher,
            on_confirm=self.on_confirm,
            handle_mcp_permissions=self._handle_mcp_permissions,
            handle_gitlab_permissions=self._handle_gitlab_permissions,
            execute_skill=self._execute_skill,
            skill_timeout=self.skill_timeout,
            runtime_logger=logger,
        )

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
        return await handle_mcp_permissions_runtime(
            tool_call=tool_call,
            skill=skill,
            server_name=server_name,
            permissions=permissions,
            authorization_kernel=self._mcp_authorization_kernel,
            confirmation=self._confirmation,
            services=self._services,
            on_confirm=self.on_confirm,
        )

    async def _handle_gitlab_permissions(
        self,
        tool_call: "ToolCall",
        skill: "Skill | None",
        permissions: AgentPermissions,
    ) -> ToolResult | None:
        """Handle GitLab-specific permission checks and confirmation.

        Args:
            tool_call: The GitLab tool call.
            skill: The resolved GitLab skill (may be None).
            permissions: Agent permissions.

        Returns:
            ToolResult with error if permission denied, None if allowed.
        """
        return await handle_gitlab_permissions_runtime(
            tool_call=tool_call,
            skill=skill,
            permissions=permissions,
            authorization_kernel=self._gitlab_authorization_kernel,
            confirmation=self._confirmation,
            services=self._services,
            on_confirm=self.on_confirm,
        )

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
        return await execute_skill_runtime(
            skill=skill,
            args=args,
            timeout=timeout,
            runtime_logger=logger,
        )

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
        return await execute_tools_parallel_runtime(
            tool_calls=tool_calls,
            tool_semaphore=self._tool_semaphore,
            execute_single_tool=self._execute_single_tool,
        )

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

        # Refresh git context (picks up any changes since last refresh)
        cwd = self._services.get_cwd() if self._services else Path.cwd()
        self.context.refresh_git_context(cwd)

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
        return get_compaction_provider_runtime(self)

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
        return await generate_compaction_summary(self, messages, compaction_config)
