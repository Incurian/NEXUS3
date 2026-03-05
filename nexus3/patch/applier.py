"""Applier for unified diff patches.

This module provides functions to apply parsed patches to file content
with configurable strictness levels: strict, tolerant, and fuzzy.
"""

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from enum import Enum

from nexus3.patch.ast_v2 import (
    HunkLineV2,
    HunkV2,
    NewlineToken,
    PatchFileV2,
    coerce_patch_file_v1,
)
from nexus3.patch.types import Hunk, PatchFile

PatchInput = PatchFile | PatchFileV2


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


@dataclass(slots=True)
class _ContentLine:
    """Internal content line with explicit newline token."""

    text: str
    newline: NewlineToken


def _split_line_newline_token(line_with_newline: str) -> tuple[str, NewlineToken]:
    """Split a line into content + normalized newline token."""
    if line_with_newline.endswith("\r\n"):
        return line_with_newline[:-2], "\r\n"
    if line_with_newline.endswith("\n"):
        return line_with_newline[:-1], "\n"
    if line_with_newline.endswith("\r"):
        return line_with_newline[:-1], "\r"
    return line_with_newline, ""


def _split_content_lines_byte_strict(content: str) -> list[_ContentLine]:
    """Split content into internal lines while retaining newline tokens."""
    content_lines: list[_ContentLine] = []
    for line_with_newline in content.splitlines(keepends=True):
        text, newline = _split_line_newline_token(line_with_newline)
        content_lines.append(_ContentLine(text=text, newline=newline))
    return content_lines


def _join_content_lines_byte_strict(lines: list[_ContentLine]) -> str:
    """Join internal content lines back to text without normalizing newlines."""
    return "".join(f"{line.text}{line.newline}" for line in lines)


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
        lines, hunk, match_pos, mode
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
    lines: list[str], hunk: Hunk, pos: int, mode: ApplyMode = ApplyMode.STRICT
) -> tuple[list[str], int, int]:
    """Perform the actual line replacement for a hunk.

    Args:
        lines: File lines
        hunk: Hunk with lines to apply
        pos: Position to apply at (0-indexed)
        mode: Matching mode (affects whitespace handling for additions)

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
            # In tolerant/fuzzy mode, normalize to avoid whitespace artifacts
            # (e.g., diff line "+ " becomes content=" " which should be "")
            if mode != ApplyMode.STRICT:
                content = _normalize_line(content)
            new_section.append(content)
            additions += 1

    # Calculate how many original lines were covered
    original_span = hunk.old_count

    # Build result: lines before + new section + lines after
    result = lines[:pos] + new_section + lines[pos + original_span :]

    return result, additions, removals


def _collect_hunk_old_side_lines_v2(hunk: HunkV2) -> list[HunkLineV2]:
    """Collect context/removal lines from a v2 hunk for old-side matching."""
    return [line for line in hunk.lines if line.prefix in (" ", "-")]


def _verify_noeol_constraints_at_match_v2(
    lines: list[_ContentLine], expected: list[HunkLineV2], pos: int
) -> str | None:
    """Verify EOF marker constraints for already-selected old-side match lines."""
    if pos < 0 or pos + len(expected) > len(lines):
        return f"context mismatch at line {pos + 1}"

    for i, expected_line in enumerate(expected):
        if not expected_line.no_newline_at_eof:
            continue

        target_idx = pos + i
        if target_idx != len(lines) - 1:
            return (
                f"EOF marker mismatch at line {target_idx + 1}: "
                "expected line at end of file"
            )
        if lines[target_idx].newline != "":
            return (
                f"EOF marker mismatch at line {target_idx + 1}: "
                "expected no trailing newline"
            )

    return None


def _verify_match_byte_strict(
    lines: list[_ContentLine], expected: list[HunkLineV2], pos: int, mode: ApplyMode
) -> str | None:
    """Verify old-side match content with strict EOF marker checks."""
    if pos < 0 or pos + len(expected) > len(lines):
        return f"context mismatch at line {pos + 1}"

    for i, expected_line in enumerate(expected):
        if not _lines_match(lines[pos + i].text, expected_line.content, mode):
            return f"context mismatch at line {pos + i + 1}"

    return _verify_noeol_constraints_at_match_v2(lines, expected, pos)


def _infer_newline_token(lines: list[_ContentLine]) -> NewlineToken | None:
    """Return the first known newline token from file lines, if any."""
    for line in lines:
        if line.newline != "":
            return line.newline
    return None


def _resolve_addition_newline_token(
    hunk_line: HunkLineV2,
    lines: list[_ContentLine],
    pos: int,
    file_idx: int,
    new_section: list[_ContentLine],
) -> NewlineToken:
    """Resolve newline token for an added line without normalizing file style."""
    if hunk_line.no_newline_at_eof:
        return ""

    if file_idx < len(lines) and lines[file_idx].newline != "":
        return lines[file_idx].newline

    if new_section and new_section[-1].newline != "":
        return new_section[-1].newline

    if pos > 0 and pos <= len(lines) and lines[pos - 1].newline != "":
        return lines[pos - 1].newline

    inferred = _infer_newline_token(lines)
    if inferred is not None:
        return inferred

    if hunk_line.raw_line.newline != "":
        return hunk_line.raw_line.newline

    return "\n"


def _validate_hunk_counts_v2(hunk: HunkV2) -> str | None:
    """Fail fast when parsed hunk headers disagree with parsed hunk lines."""
    expected_old_count = hunk.count_context() + hunk.count_removals()
    if expected_old_count != hunk.old_count:
        return (
            "hunk old_count mismatch: "
            f"header={hunk.old_count}, parsed={expected_old_count}"
        )

    expected_new_count = hunk.count_context() + hunk.count_additions()
    if expected_new_count != hunk.new_count:
        return (
            "hunk new_count mismatch: "
            f"header={hunk.new_count}, parsed={expected_new_count}"
        )

    return None


def _validate_added_noeol_markers_v2(
    hunk: HunkV2, lines: list[_ContentLine], pos: int
) -> str | None:
    """Ensure added no-EOL markers target the final output line only."""
    has_trailing_file_content = pos + hunk.old_count < len(lines)

    for i, hunk_line in enumerate(hunk.lines):
        if hunk_line.prefix != "+" or not hunk_line.no_newline_at_eof:
            continue

        has_trailing_hunk_output = any(
            later_line.prefix in (" ", "+") for later_line in hunk.lines[i + 1 :]
        )
        if has_trailing_hunk_output or has_trailing_file_content:
            return (
                f"EOF marker mismatch at hunk line {i + 1}: "
                "marker must target final output line"
            )

    return None


def _perform_replacement_byte_strict(
    lines: list[_ContentLine], hunk: HunkV2, pos: int
) -> tuple[list[_ContentLine], int, int]:
    """Perform v2 hunk replacement while preserving per-line newline tokens."""
    new_section: list[_ContentLine] = []
    file_idx = pos
    additions = 0
    removals = 0
    removed_newline_queue: list[NewlineToken] = []

    for hunk_line in hunk.lines:
        if hunk_line.prefix == " ":
            # End of a replacement run; do not carry removed-line newlines further.
            removed_newline_queue.clear()
            if file_idx < len(lines):
                new_section.append(lines[file_idx])
            else:
                newline = _resolve_addition_newline_token(
                    hunk_line, lines, pos, file_idx, new_section
                )
                new_section.append(_ContentLine(text=hunk_line.content, newline=newline))
            file_idx += 1
        elif hunk_line.prefix == "-":
            if file_idx < len(lines):
                removed_newline_queue.append(lines[file_idx].newline)
            file_idx += 1
            removals += 1
        else:
            if not hunk_line.no_newline_at_eof and removed_newline_queue:
                newline = removed_newline_queue.pop(0)
            else:
                newline = _resolve_addition_newline_token(
                    hunk_line, lines, pos, file_idx, new_section
                )
            new_section.append(_ContentLine(text=hunk_line.content, newline=newline))
            additions += 1

    original_span = hunk.old_count
    result = lines[:pos] + new_section + lines[pos + original_span :]

    return result, additions, removals


def _apply_hunk_byte_strict(
    lines: list[_ContentLine],
    hunk: HunkV2,
    offset: int,
    mode: ApplyMode,
    fuzzy_threshold: float,
) -> tuple[list[_ContentLine], int, str | None, str | None]:
    """Apply a single AST-v2 hunk to newline-aware content lines."""
    count_error = _validate_hunk_counts_v2(hunk)
    if count_error:
        return lines, offset, count_error, None

    target_pos = hunk.old_start - 1 + offset
    old_side_lines = _collect_hunk_old_side_lines_v2(hunk)

    if hunk.old_start == 0 and hunk.old_count == 0:
        new_lines_to_add: list[_ContentLine] = []
        for hunk_line in hunk.lines:
            if hunk_line.prefix != "+":
                continue
            newline = _resolve_addition_newline_token(
                hunk_line, lines, pos=0, file_idx=0, new_section=new_lines_to_add
            )
            new_lines_to_add.append(_ContentLine(text=hunk_line.content, newline=newline))

        result_lines = new_lines_to_add + lines
        new_offset = offset + len(new_lines_to_add)
        return result_lines, new_offset, None, None

    match_pos = target_pos
    fuzzy_warning: str | None = None

    if mode in (ApplyMode.STRICT, ApplyMode.TOLERANT):
        match_error = _verify_match_byte_strict(lines, old_side_lines, target_pos, mode)
        if match_error:
            return lines, offset, match_error, None
    else:
        fuzzy_result = _find_fuzzy_match(
            lines=[line.text for line in lines],
            hunk_context=[line.content for line in old_side_lines],
            start_hint=target_pos,
            threshold=fuzzy_threshold,
        )
        if fuzzy_result is None:
            return (
                lines,
                offset,
                f"no fuzzy match found (threshold {fuzzy_threshold})",
                None,
            )

        match_pos, similarity = fuzzy_result
        match_pos = max(0, min(len(lines), match_pos))

        marker_error = _verify_noeol_constraints_at_match_v2(
            lines, old_side_lines, match_pos
        )
        if marker_error:
            return lines, offset, marker_error, None

        if match_pos != target_pos:
            fuzzy_warning = (
                f"fuzzy match ({similarity:.0%} similarity at line {match_pos + 1})"
            )

    added_marker_error = _validate_added_noeol_markers_v2(hunk, lines, match_pos)
    if added_marker_error:
        return lines, offset, added_marker_error, None

    result_lines, lines_added, lines_removed = _perform_replacement_byte_strict(
        lines, hunk, match_pos
    )
    new_offset = offset + lines_added - lines_removed

    return result_lines, new_offset, None, fuzzy_warning


def apply_patch_byte_strict(
    content: str,
    patch: PatchFileV2,
    mode: ApplyMode = ApplyMode.STRICT,
    fuzzy_threshold: float = 0.8,
) -> ApplyResult:
    """Apply an AST-v2 patch while preserving newline/EOF semantics."""
    if not patch.hunks:
        return ApplyResult(
            success=True,
            new_content=content,
            applied_hunks=[],
            failed_hunks=[],
            warnings=[],
        )

    current_lines = _split_content_lines_byte_strict(content)
    applied_hunks: list[int] = []
    failed_hunks: list[tuple[int, str]] = []
    warnings: list[str] = []
    offset = 0

    for i, hunk in enumerate(patch.hunks):
        new_lines, new_offset, error, warning = _apply_hunk_byte_strict(
            current_lines, hunk, offset, mode, fuzzy_threshold
        )

        if error:
            failed_hunks.append((i, error))
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

    return ApplyResult(
        success=True,
        new_content=_join_content_lines_byte_strict(current_lines),
        applied_hunks=applied_hunks,
        failed_hunks=[],
        warnings=warnings,
    )


def apply_patch(
    content: str,
    patch: PatchInput,
    mode: ApplyMode = ApplyMode.STRICT,
    fuzzy_threshold: float = 0.8,
) -> ApplyResult:
    """Apply a patch to content.

    Applies all hunks from the patch to the content. If any hunk fails,
    the original content is returned unchanged (atomic rollback).

    Args:
        content: Original file content
        patch: Patch to apply (legacy PatchFile or AST-v2 PatchFileV2)
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
    patch_v1 = coerce_patch_file_v1(patch)

    # Handle empty content (new file case)
    if not content:
        lines: list[str] = []
    else:
        # Split content into lines, preserving structure
        lines = content.splitlines()

    # Handle case with no hunks
    if not patch_v1.hunks:
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

    for i, hunk in enumerate(patch_v1.hunks):
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
