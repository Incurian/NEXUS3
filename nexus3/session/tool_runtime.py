"""Tool execution runtime helpers extracted from Session."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from nexus3.core.errors import sanitize_error_for_agent
from nexus3.core.types import ToolCall, ToolResult

if TYPE_CHECKING:
    from nexus3.skill.base import Skill


ExecuteSingleTool = Callable[[ToolCall], Awaitable[ToolResult]]


async def execute_skill(
    skill: Skill,
    args: dict[str, Any],
    timeout: float,
    *,
    runtime_logger: logging.Logger,
) -> ToolResult:
    """Execute a skill with timeout and Session-equivalent sanitization."""
    try:
        if timeout > 0:
            result = await asyncio.wait_for(
                skill.execute(**args),
                timeout=timeout,
            )
        else:
            result = await skill.execute(**args)

        if result.error:
            runtime_logger.debug("Skill '%s' returned error: %s", skill.name, result.error)
            sanitized_error = sanitize_error_for_agent(result.error, skill.name)
            if sanitized_error != result.error:
                runtime_logger.debug("Sanitized error for agent: %s", sanitized_error)
                result = ToolResult(output=result.output, error=sanitized_error or "")

        return result
    except TimeoutError:
        runtime_logger.debug("Skill '%s' timed out after %ss", skill.name, timeout)
        return ToolResult(error=f"Skill timed out after {timeout}s")
    except Exception as e:
        runtime_logger.debug("Skill '%s' raised exception: %s", skill.name, e, exc_info=True)
        raw = f"Skill execution error: {e}"
        safe = sanitize_error_for_agent(raw, skill.name)
        return ToolResult(error=safe or "Skill execution error")


async def execute_tools_parallel(
    tool_calls: tuple[ToolCall, ...],
    *,
    tool_semaphore: asyncio.Semaphore,
    execute_single_tool: ExecuteSingleTool,
) -> list[ToolResult]:
    """Execute multiple tool calls in parallel with bounded concurrency."""

    async def execute_one(tc: ToolCall) -> ToolResult:
        async with tool_semaphore:
            return await execute_single_tool(tc)

    results = await asyncio.gather(
        *[execute_one(tc) for tc in tool_calls],
        return_exceptions=True,
    )

    final_results: list[ToolResult] = []
    for result in results:
        if isinstance(result, BaseException):
            raw = f"Execution error: {result}"
            safe = sanitize_error_for_agent(raw, "")
            final_results.append(ToolResult(error=safe or "Execution error"))
        else:
            final_results.append(result)

    return final_results
