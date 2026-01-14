"""Regex replace skill for pattern-based file editing."""

import asyncio
import re
from typing import Any

from nexus3.core.errors import PathSecurityError
from nexus3.core.types import ToolResult
from nexus3.skill.base import FileSkill, file_skill_factory

# Safety limits
MAX_REPLACEMENTS = 10000
REGEX_TIMEOUT = 5.0  # seconds


class RegexReplaceSkill(FileSkill):
    """Skill that performs regex-based find/replace in files.

    Uses Python's re.sub() with safety limits for catastrophic backtracking.
    Supports backreferences in replacement strings (\\1, \\2, \\g<name>).

    This is separate from edit_file to keep APIs clean:
    - edit_file: Exact string replacement (simple, fast)
    - regex_replace: Pattern matching (powerful, needs safety guards)

    Inherits path validation from FileSkill.
    """

    @property
    def name(self) -> str:
        return "regex_replace"

    @property
    def description(self) -> str:
        return (
            "Replace text in a file using regular expression pattern. "
            "IMPORTANT: Read the file first to verify your pattern matches the intended text."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to file to edit"
                },
                "pattern": {
                    "type": "string",
                    "description": "Regular expression pattern to match"
                },
                "replacement": {
                    "type": "string",
                    "description": "Replacement string (supports \\1, \\g<name> backreferences)"
                },
                "count": {
                    "type": "integer",
                    "description": "Maximum replacements (0 = all)",
                    "default": 0
                },
                "ignore_case": {
                    "type": "boolean",
                    "description": "Case-insensitive matching",
                    "default": False
                },
                "multiline": {
                    "type": "boolean",
                    "description": "^ and $ match line boundaries",
                    "default": False
                },
                "dotall": {
                    "type": "boolean",
                    "description": ". matches newlines",
                    "default": False
                }
            },
            "required": ["path", "pattern", "replacement"]
        }

    async def execute(
        self,
        path: str = "",
        pattern: str = "",
        replacement: str = "",
        count: int = 0,
        ignore_case: bool = False,
        multiline: bool = False,
        dotall: bool = False,
        **kwargs: Any
    ) -> ToolResult:
        """Execute regex replacement.

        Args:
            path: File to edit
            pattern: Regex pattern
            replacement: Replacement string (supports backreferences)
            count: Max replacements (0 = unlimited)
            ignore_case: Case-insensitive flag
            multiline: Multiline flag (^ $ match line boundaries)
            dotall: Dotall flag (. matches newline)

        Returns:
            ToolResult with replacement count or error
        """
        if not path:
            return ToolResult(error="Path is required")
        if not pattern:
            return ToolResult(error="Pattern is required")

        # Build regex flags
        flags = 0
        if ignore_case:
            flags |= re.IGNORECASE
        if multiline:
            flags |= re.MULTILINE
        if dotall:
            flags |= re.DOTALL

        # Compile regex with error handling
        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            return ToolResult(error=f"Invalid regex pattern: {e}")

        try:
            # Validate path (resolves symlinks, checks allowed_paths if set)
            p = self._validate_path(path)

            # Read file
            try:
                content = await asyncio.to_thread(p.read_text, encoding="utf-8")
            except FileNotFoundError:
                return ToolResult(error=f"File not found: {path}")
            except PermissionError:
                return ToolResult(error=f"Permission denied: {path}")

            # Count matches first (for reporting)
            matches = regex.findall(content)
            match_count = len(matches)

            if match_count == 0:
                return ToolResult(output=f"No matches for pattern in {path}")

            # Safety check
            if match_count > MAX_REPLACEMENTS and count == 0:
                return ToolResult(
                    error=f"Pattern matches {match_count} times (max {MAX_REPLACEMENTS}). "
                    f"Use count parameter to limit replacements."
                )

            # Perform replacement with timeout
            try:
                def do_replace() -> tuple[str, int]:
                    if count == 0:
                        new_content = regex.sub(replacement, content)
                        return new_content, match_count
                    else:
                        new_content = regex.sub(replacement, content, count=count)
                        return new_content, min(match_count, count)

                new_content, actual_count = await asyncio.wait_for(
                    asyncio.to_thread(do_replace),
                    timeout=REGEX_TIMEOUT
                )
            except TimeoutError:
                return ToolResult(
                    error=f"Regex replacement timed out ({REGEX_TIMEOUT}s). "
                    "Pattern may have catastrophic backtracking."
                )

            # Check if anything changed
            if new_content == content:
                return ToolResult(output="Pattern matched but replacement produced no changes")

            # Write result
            await asyncio.to_thread(p.write_text, new_content, encoding="utf-8")

            return ToolResult(
                output=f"Replaced {actual_count} match(es) in {path}"
            )

        except PathSecurityError as e:
            return ToolResult(error=str(e))
        except Exception as e:
            return ToolResult(error=f"Error: {e}")


# Factory for dependency injection
regex_replace_factory = file_skill_factory(RegexReplaceSkill)
