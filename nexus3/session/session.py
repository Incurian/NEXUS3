"""Chat session coordinator for NEXUS3."""

import asyncio
from collections.abc import AsyncIterator, Callable, Awaitable
from pathlib import Path
from typing import TYPE_CHECKING

from nexus3.context.compaction import (
    CompactionResult,
    build_summarize_prompt,
    create_summary_message,
    select_messages_for_compaction,
)
from nexus3.core.interfaces import AsyncProvider
from nexus3.core.permissions import AgentPermissions, ConfirmationResult
from nexus3.core.validation import ValidationError, validate_tool_arguments
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

if TYPE_CHECKING:
    from nexus3.config.schema import CompactionConfig, Config
    from nexus3.context.manager import ContextManager
    from nexus3.context.prompt_loader import PromptLoader
    from nexus3.core.cancel import CancellationToken
    from nexus3.session.logging import SessionLogger
    from nexus3.skill.registry import SkillRegistry
    from nexus3.skill.services import ServiceContainer

# Confirmation callback type - returns ConfirmationResult for allow once/always UI
ConfirmationCallback = Callable[["ToolCall", "Path | None"], Awaitable[ConfirmationResult]]


# Callback types for notifications
ToolCallCallback = Callable[[str, str], None]  # (tool_name, tool_id) -> None
ToolCompleteCallback = Callable[[str, str, bool], None]  # (tool_name, tool_id, success) -> None
# (is_reasoning) -> None - True when starts, False when ends
ReasoningCallback = Callable[[bool], None]

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
        max_tool_iterations: int = 10,
        skill_timeout: float = 30.0,
        max_concurrent_tools: int = 10,
        services: "ServiceContainer | None" = None,
        on_confirm: ConfirmationCallback | None = None,
        config: "Config | None" = None,
        prompt_loader: "PromptLoader | None" = None,
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
            prompt_loader: Optional PromptLoader to reload system prompt during
                          compaction.
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
        self._prompt_loader = prompt_loader

        # Track cancelled tool calls to report on next send()
        self._pending_cancelled_tools: list[tuple[str, str]] = []  # [(tool_id, tool_name), ...]

        # Lazy-loaded compaction provider (uses different model if configured)
        self._compaction_provider: AsyncProvider | None = None

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

    async def _request_confirmation(
        self, tool_call: "ToolCall", path: Path | None = None
    ) -> ConfirmationResult:
        """Request user confirmation for destructive action.

        Args:
            tool_call: The tool call requiring confirmation.
            path: Optional path being accessed (for path-based allowances).

        Returns:
            ConfirmationResult indicating user's decision.
        """
        if self.on_confirm is None:
            # No confirmation callback = no way to get user approval
            # Deny by default to enforce TRUSTED semantics in server mode
            return ConfirmationResult.DENY
        return await self.on_confirm(tool_call, path)

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
        for _ in range(self.max_tool_iterations):
            # Check for compaction BEFORE build_messages() to avoid truncation
            if self._should_compact():
                result = await self.compact(force=False)
                if result:
                    saved = result.original_token_count - result.new_token_count
                    yield f"\n[Context compacted: {saved:,} tokens reclaimed]\n\n"

            messages = self.context.build_messages()
            # Use context's tool definitions (filtered by permissions) rather than registry
            tools = self.context.get_tool_definitions()

            # Stream response, accumulating content and detecting tool calls
            final_message: Message | None = None
            is_reasoning = False  # Track if we're in reasoning mode
            # Only show reasoning display if reasoning is enabled for this agent's model
            show_reasoning = False
            if self._services:
                from nexus3.config.schema import ResolvedModel
                resolved_model: ResolvedModel | None = self._services.get("model")
                if resolved_model:
                    show_reasoning = resolved_model.reasoning
            elif self._config:
                show_reasoning = self._config.provider.reasoning
            async for event in self.provider.stream(messages, tools):
                if isinstance(event, ReasoningDelta):
                    # Notify callback when reasoning starts (only if reasoning enabled)
                    if show_reasoning and not is_reasoning and self.on_reasoning:
                        self.on_reasoning(True)
                    is_reasoning = True
                elif isinstance(event, ContentDelta):
                    # Notify callback when reasoning ends (transition to content)
                    if show_reasoning and is_reasoning and self.on_reasoning:
                        self.on_reasoning(False)
                    is_reasoning = False
                    yield event.text
                    if cancel_token and cancel_token.is_cancelled:
                        return
                elif isinstance(event, ToolCallStarted):
                    # End reasoning if we were reasoning
                    if show_reasoning and is_reasoning and self.on_reasoning:
                        self.on_reasoning(False)
                    is_reasoning = False
                    # Notify callback if set (for display updates)
                    if self.on_tool_call:
                        self.on_tool_call(event.name, event.id)
                elif isinstance(event, StreamComplete):
                    # End reasoning if stream completes while still reasoning
                    if show_reasoning and is_reasoning and self.on_reasoning:
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
                    for tc, result in zip(final_message.tool_calls, results, strict=True):
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

                # Check for auto-compaction after response is complete
                if self._should_compact():
                    result = await self.compact(force=False)
                    if result:
                        saved = result.original_token_count - result.new_token_count
                        yield f"\n\n[Context compacted: {saved:,} tokens reclaimed]"

                return

        # Max iterations reached
        yield "[Max tool iterations reached]"

    def _extract_path_from_tool_call(self, tool_call: "ToolCall") -> Path | None:
        """Extract the target path from a tool call's arguments.

        Used for path-based permission checks in TRUSTED mode.

        Args:
            tool_call: The tool call to extract path from.

        Returns:
            Path if the tool has a path argument, None otherwise.
        """
        # Tools that have path arguments
        path_arg = tool_call.arguments.get("path")
        if path_arg:
            return Path(path_arg)
        return None

    def _extract_exec_cwd_from_tool_call(self, tool_call: "ToolCall") -> Path:
        """Extract the working directory for execution tools.

        Used for exec permission checks in TRUSTED mode.

        Args:
            tool_call: The tool call to extract cwd from.

        Returns:
            The execution working directory (defaults to current cwd).
        """
        cwd_arg = tool_call.arguments.get("cwd")
        if cwd_arg:
            return Path(cwd_arg)
        return Path.cwd()

    async def _execute_single_tool(self, tool_call: "ToolCall") -> ToolResult:
        """Execute a single tool call with permission checks.

        Permission flow:
        1. Check if tool is enabled (via tool_permissions)
        2. For SANDBOXED: Check if action is allowed at all
        3. For TRUSTED: Check if path is within CWD or write_allowances
           - If not, request confirmation with allow once/always options
           - Handle confirmation result (add to allowances if requested)
        4. Execute the tool

        Args:
            tool_call: The tool call to execute.

        Returns:
            The tool result.
        """
        # Get permissions from services
        permissions: AgentPermissions | None = None
        if self._services:
            permissions = self._services.get("permissions")

        # Default timeout
        effective_timeout = self.skill_timeout

        if permissions:
            tool_perm = permissions.tool_permissions.get(tool_call.name)

            # Check if tool is enabled
            if tool_perm and not tool_perm.enabled:
                return ToolResult(error=f"Tool '{tool_call.name}' is disabled by permissions")

            # Check if action is allowed at all (SANDBOXED blocks execution tools)
            if not permissions.effective_policy.allows_action(tool_call.name):
                return ToolResult(error=f"Tool '{tool_call.name}' is not allowed in {permissions.effective_policy.level.value} mode")

            # Extract path/cwd for permission checks
            target_path = self._extract_path_from_tool_call(tool_call)
            exec_cwd = self._extract_exec_cwd_from_tool_call(tool_call) if tool_call.name in ("bash", "run_python") else None

            # Skip confirmation for nexus_destroy of own child agents
            skip_confirmation = False
            if tool_call.name == "nexus_destroy":
                target_agent_id = tool_call.arguments.get("agent_id")
                child_ids: set[str] | None = self.services.get("child_agent_ids") if self.services else None
                if target_agent_id and child_ids and target_agent_id in child_ids:
                    skip_confirmation = True

            # Check if confirmation required (TRUSTED mode with path/exec outside allowances)
            if not skip_confirmation and permissions.effective_policy.requires_confirmation(
                tool_call.name,
                path=target_path,
                exec_cwd=exec_cwd,
                session_allowances=permissions.session_allowances,
            ):
                result = await self._request_confirmation(tool_call, target_path)

                if result == ConfirmationResult.DENY:
                    return ToolResult(error="Action cancelled by user")

                # Handle "allow always" responses for write operations
                if result == ConfirmationResult.ALLOW_FILE and target_path is not None:
                    permissions.add_file_allowance(target_path)
                elif result == ConfirmationResult.ALLOW_WRITE_DIRECTORY and target_path is not None:
                    permissions.add_directory_allowance(target_path.parent)

                # Handle "allow always" responses for execution operations
                elif result == ConfirmationResult.ALLOW_EXEC_CWD and exec_cwd is not None:
                    permissions.add_exec_cwd_allowance(tool_call.name, exec_cwd)
                elif result == ConfirmationResult.ALLOW_EXEC_GLOBAL:
                    permissions.add_exec_global_allowance(tool_call.name)

                # ALLOW_ONCE just continues without adding to allowances

            # For SANDBOXED: Additional path check (sandbox enforcement)
            if target_path is not None:
                if not permissions.effective_policy.can_write_path(target_path):
                    return ToolResult(
                        error=f"Path '{target_path}' is outside the allowed sandbox"
                    )

            # Per-tool path restrictions (for write_file/edit_file with allowed_write_paths)
            if target_path is not None and tool_perm and tool_perm.allowed_paths is not None:
                # Check if target path is within any of the per-tool allowed paths
                path_allowed = False
                for allowed_path in tool_perm.allowed_paths:
                    try:
                        target_path.relative_to(allowed_path)
                        path_allowed = True
                        break
                    except ValueError:
                        continue
                if not path_allowed:
                    allowed_str = ", ".join(str(p) for p in tool_perm.allowed_paths)
                    return ToolResult(
                        error=f"Tool '{tool_call.name}' cannot access '{target_path}'. "
                        f"Allowed paths: [{allowed_str}]"
                    )

            # Get per-tool timeout
            if tool_perm and tool_perm.timeout is not None:
                effective_timeout = tool_perm.timeout

        # Get the skill
        skill = self.registry.get(tool_call.name) if self.registry else None
        if not skill:
            return ToolResult(error=f"Unknown skill: {tool_call.name}")

        # SECURITY: Validate arguments against skill's JSON schema
        try:
            args = validate_tool_arguments(
                tool_call.arguments,
                skill.parameters,
                logger=self.logger,
            )
        except ValidationError as e:
            return ToolResult(error=f"Invalid arguments for {tool_call.name}: {e.message}")

        try:
            if effective_timeout > 0:
                result = await asyncio.wait_for(
                    skill.execute(**args),
                    timeout=effective_timeout,
                )
            else:
                result = await skill.execute(**args)
            return result
        except asyncio.TimeoutError:
            return ToolResult(error=f"Skill '{tool_call.name}' timed out after {effective_timeout}s")
        except Exception as e:
            return ToolResult(error=f"Skill execution error: {e}")

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
                final_results.append(ToolResult(error=f"Execution error: {r}"))
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
        if self._prompt_loader:
            loaded = self._prompt_loader.load(is_repl=True)  # TODO: track is_repl
            new_system_prompt = loaded.content

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

        # Create a provider with the compaction model
        from nexus3.config.schema import ProviderConfig
        from nexus3.provider.openrouter import OpenRouterProvider

        compaction_config = ProviderConfig(
            type=self._config.provider.type,
            api_key_env=self._config.provider.api_key_env,
            model=compaction_model,
            base_url=self._config.provider.base_url,
        )
        self._compaction_provider = OpenRouterProvider(compaction_config)
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

        # Use compaction provider (may be different model than main)
        provider = self._get_compaction_provider()
        response = await provider.complete(summary_messages, tools=None)

        return response.content
