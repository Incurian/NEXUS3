"""Regex replace skill for pattern-based file editing."""

import asyncio
import re
from typing import Any

from nexus3.core.errors import PathSecurityError
from nexus3.core.paths import atomic_write_bytes, detect_line_ending
from nexus3.core.types import ToolResult
from nexus3.skill.base import FileSkill, file_skill_factory

# Guardrails
MAX_REPLACEMENTS = 10000
REGEX_TIMEOUT = 5.0  # Best-effort local wait window in seconds.


def _count_matches_up_to_limit(
    regex: re.Pattern[str],
    content: str,
    stop_after: int | None = None,
) -> int:
    """Count regex matches without materializing an unbounded match list."""
    match_count = 0
    for _ in regex.finditer(content):
        match_count += 1
        if stop_after is not None and match_count >= stop_after:
            break
    return match_count


class RegexReplaceSkill(FileSkill):
    """Skill that performs regex-based find/replace in files.

    Uses Python's re.subn() with replacement-volume guardrails and a
    best-effort local wait window.
    Supports backreferences in replacement strings (\\1, \\2, \\g<name>).

    This is separate from the exact-string edit tools to keep APIs clean:
    - edit_file / edit_file_batch: Exact string replacement (simple, fast)
    - regex_replace: Pattern matching (powerful, needs safety guards)

    Inherits path validation from FileSkill.
    """

    @property
    def name(self) -> str:
        return "regex_replace"

    @property
    def description(self) -> str:
        return (
            "Replace text in a file using a regular expression pattern. "
            "Use for pattern-driven edits and broad renames where exact string "
            "replacement is insufficient. "
            "IMPORTANT: Use specific patterns to avoid unintended matches; "
            "use edit_file or edit_file_batch for literal replacements."
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
            "required": ["path", "pattern", "replacement"],
            "additionalProperties": False,
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
        if count < 0:
            return ToolResult(error="count must be >= 0")

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
                content_bytes = await asyncio.to_thread(p.read_bytes)
                raw_content = content_bytes.decode("utf-8")
                original_line_ending = detect_line_ending(raw_content)
                # Normalize to LF for processing
                content = raw_content.replace('\r\n', '\n').replace('\r', '\n')
            except FileNotFoundError:
                return ToolResult(error=f"File not found: {path}")
            except PermissionError:
                return ToolResult(error=f"Permission denied: {path}")
            except UnicodeDecodeError:
                return ToolResult(
                    error=(
                        f"File is not valid UTF-8 text: {path}. "
                        "Use patch with fidelity_mode='byte_strict' for byte-sensitive edits."
                    )
                )

            # Count matches first (for reporting)
            precheck_limit = 1 if count > 0 else MAX_REPLACEMENTS + 1
            match_count = _count_matches_up_to_limit(regex, content, precheck_limit)

            if match_count == 0:
                return ToolResult(output=f"No matches for pattern in {path}")

            # Guardrail against unbounded broad replacements.
            if match_count > MAX_REPLACEMENTS and count == 0:
                return ToolResult(
                    error=f"Pattern matches {match_count} times (max {MAX_REPLACEMENTS}). "
                    f"Use count parameter to limit replacements."
                )

            # Perform replacement with timeout
            try:
                def do_replace() -> tuple[str, int]:
                    return regex.subn(replacement, content, count=count)

                new_content, actual_count = await asyncio.wait_for(
                    asyncio.to_thread(do_replace),
                    timeout=REGEX_TIMEOUT
                )
            except TimeoutError:
                return ToolResult(
                    error=(
                        f"Regex replacement exceeded the {REGEX_TIMEOUT}s local wait "
                        "window. Narrow the pattern or limit the edit scope and retry."
                    )
                )

            # Check if anything changed
            if new_content == content:
                return ToolResult(output="Pattern matched but replacement produced no changes")

            # Write result atomically (temp file + rename)
            if original_line_ending != '\n':
                new_content = new_content.replace('\n', original_line_ending)
            await asyncio.to_thread(atomic_write_bytes, p, new_content.encode('utf-8'))

            return ToolResult(
                output=f"Replaced {actual_count} match(es) in {path}"
            )

        except (PathSecurityError, ValueError) as e:
            return ToolResult(error=str(e))
        except Exception as e:
            return ToolResult(error=f"Error: {e}")


# Factory for dependency injection
regex_replace_factory = file_skill_factory(RegexReplaceSkill)
