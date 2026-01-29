"""Applier for unified diff patches.

This module provides functions to apply parsed patches to file content
with configurable strictness levels: strict, tolerant, and fuzzy.
"""

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from enum import Enum

from nexus3.patch.types import Hunk, PatchFile


class ApplyMode(Enum):
    """Strictness level for applying patches."""

    STRICT = "strict"  # Exact context match required
    TOLERANT = "tolerant"  # Allow whitespace differences
    FUZZY = "fuzzy"  # SequenceMatcher fallback


@dataclass
class ApplyResult:
    """Result of applying a patch.

    Attributes:
        success: True if all hunks applied successfully
        new_content: The patched content (original if failed)
        applied_hunks: Indices of successfully applied hunks
        failed_hunks: List of (index, reason) for failed hunks
        warnings: Non-critical issues encountered during application
    """

    success: bool
    new_content: str
    applied_hunks: list[int] = field(default_factory=list)
    failed_hunks: list[tuple[int, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _normalize_line(line: str) -> str:
    """Normalize a line for tolerant comparison (strip trailing whitespace)."""
    return line.rstrip()


def _lines_match(line1: str, line2: str, mode: ApplyMode) -> bool:
    """Check if two lines match according to the given mode.

    Args:
        line1: First line to compare
        line2: Second line to compare
        mode: Matching strictness (STRICT or TOLERANT)

    Returns:
        True if lines match according to mode
    """
    if mode == ApplyMode.STRICT:
        return line1 == line2
    # TOLERANT: compare after stripping trailing whitespace
    return _normalize_line(line1) == _normalize_line(line2)


def _find_fuzzy_match(
    lines: list[str],
    hunk_context: list[str],
    start_hint: int,
    threshold: float,
) -> tuple[int, float] | None:
    """Find best fuzzy match location for hunk context.

    Args:
        lines: File lines to search
        hunk_context: Context/removal lines from hunk (prefix stripped)
        start_hint: Suggested starting position (0-indexed)
        threshold: Minimum similarity required (0.0-1.0)

    Returns:
        Tuple of (best_position, similarity) or None if no match found
    """
    if not hunk_context:
        return start_hint, 1.0

    hunk_text = "\n".join(hunk_context)
    best_pos = -1
    best_ratio = 0.0

    # Search window around the hint position
    # Wider search for fuzzy mode
    search_start = max(0, start_hint - 50)
    search_end = min(len(lines), start_hint + len(hunk_context) + 50)

    for pos in range(search_start, search_end - len(hunk_context) + 1):
        window = lines[pos : pos + len(hunk_context)]
        window_text = "\n".join(window)

        matcher = SequenceMatcher(None, hunk_text, window_text)
        ratio = matcher.ratio()

        if ratio > best_ratio:
            best_ratio = ratio
            best_pos = pos

    if best_ratio >= threshold:
        return best_pos, best_ratio

    return None


def _apply_hunk(
    lines: list[str],
    hunk: Hunk,
    offset: int,
    mode: ApplyMode,
    fuzzy_threshold: float,
) -> tuple[list[str], int, str | None, str | None]:
    """Apply a single hunk to file lines.

    Args:
        lines: Current file lines (will be modified in place)
        hunk: Hunk to apply
        offset: Cumulative line offset from previous hunks
        mode: Matching strictness
        fuzzy_threshold: Minimum similarity for fuzzy mode

    Returns:
        Tuple of (new_lines, new_offset, error_or_none, warning_or_none)
    """
    # Calculate target position (0-indexed, with offset)
    target_pos = hunk.old_start - 1 + offset

    # Collect context and removal lines for matching
    context_and_removals: list[str] = []
    for prefix, content in hunk.lines:
        if prefix in (" ", "-"):
            context_and_removals.append(content)

    # For new files (old_start=0), just apply additions at the start
    if hunk.old_start == 0 and hunk.old_count == 0:
        new_lines_to_add = [content for prefix, content in hunk.lines if prefix == "+"]
        result_lines = new_lines_to_add + lines
        new_offset = offset + len(new_lines_to_add)
        return result_lines, new_offset, None, None

    # Try to match at expected position
    match_pos = target_pos
    fuzzy_warning = None

    if mode in (ApplyMode.STRICT, ApplyMode.TOLERANT):
        # Verify context/removal lines match at expected position
        if not _verify_match(lines, context_and_removals, target_pos, mode):
            return (
                lines,
                offset,
                f"context mismatch at line {target_pos + 1}",
                None,
            )
    else:
        # FUZZY mode - find best match
        result = _find_fuzzy_match(
            lines, context_and_removals, target_pos, fuzzy_threshold
        )
        if result is None:
            return (
                lines,
                offset,
                f"no fuzzy match found (threshold {fuzzy_threshold})",
                None,
            )
        match_pos, similarity = result
        if match_pos != target_pos:
            fuzzy_warning = (
                f"fuzzy match ({similarity:.0%} similarity at line {match_pos + 1})"
            )

    # Apply the hunk at match_pos
    result_lines, lines_added, lines_removed = _perform_replacement(
        lines, hunk, match_pos
    )

    new_offset = offset + lines_added - lines_removed

    return result_lines, new_offset, None, fuzzy_warning


def _verify_match(
    lines: list[str], expected: list[str], pos: int, mode: ApplyMode
) -> bool:
    """Verify that lines at position match expected content.

    Args:
        lines: File lines
        expected: Expected lines (context + removals)
        pos: Position to check (0-indexed)
        mode: Matching strictness

    Returns:
        True if all expected lines match
    """
    if pos < 0:
        return False
    if pos + len(expected) > len(lines):
        return False

    for i, exp_line in enumerate(expected):
        if not _lines_match(lines[pos + i], exp_line, mode):
            return False

    return True


def _perform_replacement(
    lines: list[str], hunk: Hunk, pos: int
) -> tuple[list[str], int, int]:
    """Perform the actual line replacement for a hunk.

    Args:
        lines: File lines
        hunk: Hunk with lines to apply
        pos: Position to apply at (0-indexed)

    Returns:
        Tuple of (new_lines, additions_count, removals_count)
    """
    # Build new content for this section
    new_section: list[str] = []
    file_idx = pos
    additions = 0
    removals = 0

    for prefix, content in hunk.lines:
        if prefix == " ":
            # Context line - keep from file (preserves original whitespace)
            if file_idx < len(lines):
                new_section.append(lines[file_idx])
            else:
                new_section.append(content)
            file_idx += 1
        elif prefix == "-":
            # Removal - skip this line in the file
            file_idx += 1
            removals += 1
        elif prefix == "+":
            # Addition - insert new line
            new_section.append(content)
            additions += 1

    # Calculate how many original lines were covered
    original_span = hunk.old_count

    # Build result: lines before + new section + lines after
    result = lines[:pos] + new_section + lines[pos + original_span :]

    return result, additions, removals


def apply_patch(
    content: str,
    patch: PatchFile,
    mode: ApplyMode = ApplyMode.STRICT,
    fuzzy_threshold: float = 0.8,
) -> ApplyResult:
    """Apply a patch to content.

    Applies all hunks from the patch to the content. If any hunk fails,
    the original content is returned unchanged (atomic rollback).

    Args:
        content: Original file content
        patch: Patch to apply
        mode: Matching strictness (STRICT, TOLERANT, FUZZY)
        fuzzy_threshold: Minimum similarity for fuzzy mode (0.5-1.0)

    Returns:
        ApplyResult with new content if successful, original content if failed

    Example:
        >>> from nexus3.patch.types import PatchFile, Hunk
        >>> lines = [(" ", "line1"), ("-", "line2"), ("+", "new_line")]
        >>> patch = PatchFile("f.py", "f.py", [Hunk(1, 2, 1, 2, lines)])
        >>> result = apply_patch("line1\\nline2\\n", patch)
        >>> result.success
        True
        >>> result.new_content
        'line1\\nnew_line\\n'
    """
    # Handle empty content (new file case)
    if not content:
        lines: list[str] = []
    else:
        # Split content into lines, preserving structure
        lines = content.splitlines()

    # Handle case with no hunks
    if not patch.hunks:
        return ApplyResult(
            success=True,
            new_content=content,
            applied_hunks=[],
            failed_hunks=[],
            warnings=[],
        )

    # Track results
    applied_hunks: list[int] = []
    failed_hunks: list[tuple[int, str]] = []
    warnings: list[str] = []

    current_lines = list(lines)  # Work on a copy
    offset = 0

    for i, hunk in enumerate(patch.hunks):
        new_lines, new_offset, error, warning = _apply_hunk(
            current_lines, hunk, offset, mode, fuzzy_threshold
        )

        if error:
            failed_hunks.append((i, error))
            # Rollback - return original content
            return ApplyResult(
                success=False,
                new_content=content,
                applied_hunks=applied_hunks,
                failed_hunks=failed_hunks,
                warnings=warnings,
            )

        if warning:
            warnings.append(f"Hunk {i + 1} applied via {warning}")

        current_lines = new_lines
        offset = new_offset
        applied_hunks.append(i)

    # Reconstruct content from lines
    # Preserve original ending style
    if current_lines:
        new_content = "\n".join(current_lines)
        # Add trailing newline if original had one
        if content.endswith("\n"):
            new_content += "\n"
    else:
        new_content = ""

    return ApplyResult(
        success=True,
        new_content=new_content,
        applied_hunks=applied_hunks,
        failed_hunks=[],
        warnings=warnings,
    )
