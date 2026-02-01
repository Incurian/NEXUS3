"""Validator for unified diff patches.

This module provides functions to validate patches against target file
content, detect common LLM-generated patch errors, and auto-fix where possible.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from nexus3.patch.types import Hunk, PatchFile


@dataclass
class ValidationResult:
    """Result of patch validation.

    Attributes:
        valid: True if patch can be applied successfully
        errors: List of critical errors that prevent application
        warnings: List of non-critical issues (patch may still apply)
        fixed_patch: Auto-corrected version of the patch (if fixable)
    """

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    fixed_patch: PatchFile | None = None


def _normalize_line(line: str) -> str:
    """Normalize a line for comparison (strip trailing whitespace)."""
    return line.rstrip()


def _get_file_lines(content: str) -> list[str]:
    """Split file content into lines, preserving line structure."""
    if not content:
        return []
    # Keep empty string for empty file
    return content.splitlines()


def _validate_hunk_counts(hunk: Hunk) -> tuple[bool, str | None, Hunk | None]:
    """Validate that hunk line counts match actual content.

    Returns:
        Tuple of (valid, error_message, fixed_hunk)
    """
    actual_old, actual_new = hunk.compute_counts()

    if actual_old == hunk.old_count and actual_new == hunk.new_count:
        return True, None, None

    # Counts don't match - create fixed version
    fixed_hunk = Hunk(
        old_start=hunk.old_start,
        old_count=actual_old,
        new_start=hunk.new_start,
        new_count=actual_new,
        lines=list(hunk.lines),
        context=hunk.context,
    )

    error_msg = (
        f"Hunk at line {hunk.old_start}: line count mismatch. "
        f"Header claims -{hunk.old_count},+{hunk.new_count} "
        f"but actual is -{actual_old},+{actual_new}"
    )

    return False, error_msg, fixed_hunk


def _validate_context_lines(
    hunk: Hunk, file_lines: list[str], file_path: str
) -> tuple[list[str], list[str]]:
    """Validate that context lines in hunk match file content.

    Returns:
        Tuple of (errors, warnings)
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Get the lines from the original file that this hunk references
    # hunk.old_start is 1-indexed
    start_idx = hunk.old_start - 1
    file_line_idx = start_idx

    for prefix, patch_line in hunk.lines:
        if prefix == "+":
            # Addition - doesn't reference original file
            continue

        # Context or removal - should match original file
        if file_line_idx >= len(file_lines):
            errors.append(
                f"Hunk at line {hunk.old_start}: references line {file_line_idx + 1} "
                f"but file only has {len(file_lines)} lines"
            )
            file_line_idx += 1
            continue

        file_line = file_lines[file_line_idx]
        patch_normalized = _normalize_line(patch_line)
        file_normalized = _normalize_line(file_line)

        if patch_normalized != file_normalized:
            if prefix == " ":
                errors.append(
                    f"Context mismatch at line {file_line_idx + 1}: "
                    f"expected {repr(patch_line)} but found {repr(file_line)}"
                )
            else:  # prefix == "-"
                errors.append(
                    f"Removal mismatch at line {file_line_idx + 1}: "
                    f"expected {repr(patch_line)} but found {repr(file_line)}"
                )
        elif patch_line != file_line:
            # Only whitespace difference
            warnings.append(
                f"Whitespace difference at line {file_line_idx + 1}: "
                f"trailing whitespace differs"
            )

        file_line_idx += 1

    return errors, warnings


def _fix_trailing_whitespace(hunk: Hunk, file_lines: list[str]) -> Hunk:
    """Create a new hunk with trailing whitespace normalized to match file.

    Args:
        hunk: Original hunk
        file_lines: Lines from the target file

    Returns:
        New Hunk with normalized whitespace
    """
    start_idx = hunk.old_start - 1
    file_line_idx = start_idx
    new_lines: list[tuple[str, str]] = []

    for prefix, patch_line in hunk.lines:
        if prefix == "+":
            # Keep additions as-is (they're new content)
            new_lines.append((prefix, patch_line))
        else:
            # Context or removal - normalize to match file
            if file_line_idx < len(file_lines):
                file_line = file_lines[file_line_idx]
                # If only difference is trailing whitespace, use file version
                if _normalize_line(patch_line) == _normalize_line(file_line):
                    new_lines.append((prefix, file_line))
                else:
                    new_lines.append((prefix, patch_line))
            else:
                new_lines.append((prefix, patch_line))
            file_line_idx += 1

    return Hunk(
        old_start=hunk.old_start,
        old_count=hunk.old_count,
        new_start=hunk.new_start,
        new_count=hunk.new_count,
        lines=new_lines,
        context=hunk.context,
    )


def validate_patch(patch: PatchFile, target_content: str) -> ValidationResult:
    """Validate a patch against target file content.

    Performs the following checks:
    1. Line counts in hunk headers match actual line counts
    2. Context lines in hunks match corresponding lines in target file
    3. Lines to be removed actually exist in target file

    Auto-fixes:
    - Line count mismatches (recomputes header from actual lines)
    - Trailing whitespace differences (normalizes to match file)

    Args:
        patch: PatchFile to validate
        target_content: Content of the file to be patched

    Returns:
        ValidationResult with validation status, errors, warnings,
        and optionally a fixed version of the patch.

    Example:
        >>> from nexus3.patch.types import PatchFile, Hunk
        >>> lines = [(" ", "line1"), ("-", "line2"), ("+", "new1"), ("+", "new2")]
        >>> patch = PatchFile(
        ...     old_path="test.py",
        ...     new_path="test.py",
        ...     hunks=[Hunk(1, 2, 1, 3, lines)]
        ... )
        >>> result = validate_patch(patch, "line1\\nline2\\n")
        >>> result.valid
        True
    """
    all_errors: list[str] = []
    all_warnings: list[str] = []
    file_lines = _get_file_lines(target_content)

    # Track if we need a fixed version
    needs_fix = False
    fixed_hunks: list[Hunk] = []

    for hunk in patch.hunks:
        # Validate line counts
        count_valid, count_error, fixed_hunk = _validate_hunk_counts(hunk)
        if not count_valid:
            all_warnings.append(count_error or "Line count mismatch")
            needs_fix = True
            current_hunk = fixed_hunk or hunk
        else:
            current_hunk = hunk

        # Validate context lines against file
        context_errors, context_warnings = _validate_context_lines(
            current_hunk, file_lines, patch.path
        )
        all_errors.extend(context_errors)
        all_warnings.extend(context_warnings)

        # If only whitespace warnings, try to fix
        if context_warnings and not context_errors:
            current_hunk = _fix_trailing_whitespace(current_hunk, file_lines)
            needs_fix = True

        fixed_hunks.append(current_hunk)

    # Create fixed patch if needed
    fixed_patch: PatchFile | None = None
    if needs_fix and not all_errors:
        fixed_patch = PatchFile(
            old_path=patch.old_path,
            new_path=patch.new_path,
            hunks=fixed_hunks,
            is_new_file=patch.is_new_file,
            is_deleted=patch.is_deleted,
        )

    return ValidationResult(
        valid=len(all_errors) == 0,
        errors=all_errors,
        warnings=all_warnings,
        fixed_patch=fixed_patch,
    )


def validate_patch_set(
    patches: list[PatchFile], get_content: Callable[[str], str]
) -> dict[str, ValidationResult]:
    """Validate multiple patches against their target files.

    Args:
        patches: List of PatchFile objects to validate
        get_content: Callable that takes a path and returns file content
            (or raises FileNotFoundError for missing files)

    Returns:
        Dictionary mapping file paths to their ValidationResult
    """
    results: dict[str, ValidationResult] = {}

    for patch in patches:
        try:
            if patch.is_new_file:
                # New files don't need validation against existing content
                results[patch.path] = ValidationResult(valid=True)
            else:
                content = get_content(patch.path)
                results[patch.path] = validate_patch(patch, content)
        except FileNotFoundError:
            results[patch.path] = ValidationResult(
                valid=False,
                errors=[f"Target file not found: {patch.path}"],
            )

    return results
