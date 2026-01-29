"""Patch skill for applying unified diffs.

This skill provides the ability to apply unified diff patches to files,
with validation and multiple matching modes (strict, tolerant, fuzzy).
Supports inline diffs or reading from .diff/.patch files.
"""

import asyncio
import os
from typing import Any

from nexus3.core.errors import PathSecurityError
from nexus3.core.paths import atomic_write_bytes, detect_line_ending
from nexus3.core.types import ToolResult
from nexus3.patch import (
    ApplyMode,
    PatchFile,
    apply_patch,
    parse_unified_diff,
    validate_patch,
)
from nexus3.skill.base import FileSkill, file_skill_factory


class PatchSkill(FileSkill):
    """Apply unified diffs to files with validation and multiple matching modes.

    Supports inline diffs or reading from .diff/.patch files.
    Validates patches before applying and can auto-fix common LLM errors.

    Example usage:
        # Apply inline diff
        patch(target="src/foo.py", diff=\"\"\"--- a/foo.py
        +++ b/foo.py
        @@ -1,3 +1,4 @@
         import os
        +import sys

         def main():
        \"\"\")

        # Apply from .diff file
        patch(target="src/foo.py", diff_file="changes.diff")

        # Use fuzzy matching for drifted code
        patch(target="src/foo.py", diff="...", mode="fuzzy")
    """

    @property
    def name(self) -> str:
        return "patch"

    @property
    def description(self) -> str:
        return (
            "Apply a unified diff to a file. "
            "Validates patches before applying and auto-fixes common LLM errors. "
            "Use mode='fuzzy' for code that may have drifted slightly. "
            "Use dry_run=True to validate without applying changes. "
            "DIFF FORMAT TIPS: (1) Every line in a hunk needs a prefix: ' ' for context, "
            "'-' for removal, '+' for addition. (2) Blank context lines need a space prefix "
            "(not empty). (3) Line numbers are 1-indexed. (4) Context lines must match "
            "the actual file content exactly."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Target file to patch (required)",
                },
                "diff": {
                    "type": "string",
                    "description": (
                        "Unified diff content (inline). "
                        "Use either diff or diff_file, not both."
                    ),
                },
                "diff_file": {
                    "type": "string",
                    "description": (
                        "Path to .diff/.patch file to read. "
                        "Use either diff or diff_file, not both."
                    ),
                },
                "mode": {
                    "type": "string",
                    "enum": ["strict", "tolerant", "fuzzy"],
                    "default": "strict",
                    "description": (
                        "Matching strictness: "
                        "strict=exact, tolerant=ignore whitespace, "
                        "fuzzy=similarity-based"
                    ),
                },
                "fuzzy_threshold": {
                    "type": "number",
                    "minimum": 0.5,
                    "maximum": 1.0,
                    "default": 0.8,
                    "description": "Similarity threshold for fuzzy mode (0.5-1.0)",
                },
                "dry_run": {
                    "type": "boolean",
                    "default": False,
                    "description": "Validate and report without applying changes",
                },
            },
            "required": ["target"],
        }

    async def execute(
        self,
        target: str = "",
        diff: str | None = None,
        diff_file: str | None = None,
        mode: str = "strict",
        fuzzy_threshold: float = 0.8,
        dry_run: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        """Apply a unified diff to the target file.

        Args:
            target: Path to the file to patch
            diff: Inline unified diff content
            diff_file: Path to a .diff/.patch file to read
            mode: Matching strictness (strict, tolerant, fuzzy)
            fuzzy_threshold: Similarity threshold for fuzzy mode (0.5-1.0)
            dry_run: If True, validate without applying changes

        Returns:
            ToolResult with success message or error
        """
        # Validate target path
        try:
            target_path = self._validate_path(target)
        except (PathSecurityError, ValueError) as e:
            return ToolResult(error=str(e))

        # Validate mutual exclusion of diff and diff_file
        if diff is not None and diff_file is not None:
            return ToolResult(
                error="Cannot provide both 'diff' and 'diff_file'. Use one or the other."
            )

        if diff is None and diff_file is None:
            return ToolResult(
                error="Must provide either 'diff' (inline) or 'diff_file' (path)."
            )

        # Get diff content
        diff_content: str
        if diff_file is not None:
            # Validate diff_file path
            try:
                diff_path = self._validate_path(diff_file)
            except (PathSecurityError, ValueError) as e:
                return ToolResult(error=f"diff_file path error: {e}")

            if not diff_path.exists():
                return ToolResult(error=f"Diff file not found: {diff_file}")

            try:
                diff_content = await asyncio.to_thread(
                    diff_path.read_text, encoding="utf-8", errors="replace"
                )
            except OSError as e:
                return ToolResult(error=f"Error reading diff file: {e}")
        else:
            diff_content = diff  # type: ignore[assignment]

        # Verify target file exists
        if not target_path.exists():
            return ToolResult(error=f"Target file not found: {target}")

        # Parse the diff
        try:
            patch_files = parse_unified_diff(diff_content)
        except Exception as e:
            return ToolResult(error=f"Error parsing diff: {e}")

        if not patch_files:
            return ToolResult(error="No patch hunks found in diff")

        # Find hunks matching the target file (by basename)
        target_basename = target_path.name
        matching_patch = self._find_matching_patch(patch_files, target_basename)

        # Build warning message for multi-file diffs
        multi_file_warning = ""
        if len(patch_files) > 1:
            multi_file_warning = (
                f"Diff contains {len(patch_files)} files, "
                f"applying only hunks for {target_basename}\n"
            )

        if matching_patch is None:
            file_list = ", ".join(pf.path for pf in patch_files)
            return ToolResult(
                error=f"No hunks found for target file '{target_basename}'. "
                f"Files in diff: {file_list}"
            )

        # Read target file content (binary to detect line endings)
        try:
            raw_bytes = await asyncio.to_thread(target_path.read_bytes)
            target_content = raw_bytes.decode("utf-8", errors="replace")
        except OSError as e:
            return ToolResult(error=f"Error reading target file: {e}")

        # Detect original line ending
        original_line_ending = detect_line_ending(target_content)

        # Convert mode string to ApplyMode enum early (needed for validation decision)
        try:
            apply_mode = ApplyMode(mode)
        except ValueError:
            return ToolResult(error=f"Invalid mode '{mode}'. Use: strict, tolerant, fuzzy")

        # Validate the patch against target content
        validation_result = validate_patch(matching_patch, target_content)

        # Use auto-fixed version if available, otherwise use original
        patch_to_apply = validation_result.fixed_patch or matching_patch

        # For dry_run, return validation result
        if dry_run:
            return self._format_dry_run_result(
                validation_result,
                matching_patch,
                multi_file_warning,
            )

        # If validation failed and no auto-fix in STRICT mode, report errors
        # For tolerant/fuzzy modes, skip validation failure and let apply_patch() handle it
        if not validation_result.valid and validation_result.fixed_patch is None:
            if apply_mode == ApplyMode.STRICT:
                return self._format_validation_failure(validation_result, matching_patch)
            # For tolerant/fuzzy, proceed to apply_patch() which has its own matching logic

        # Apply the patch
        apply_result = apply_patch(
            target_content,
            patch_to_apply,
            mode=apply_mode,
            fuzzy_threshold=fuzzy_threshold,
        )

        if not apply_result.success:
            return self._format_apply_failure(apply_result, matching_patch)

        # Convert back to original line endings and write atomically
        new_content = apply_result.new_content
        if original_line_ending == "\r\n" and "\r\n" not in new_content:
            # Convert LF to CRLF
            new_content = new_content.replace("\n", "\r\n")
        elif original_line_ending == "\r" and "\r" not in new_content:
            # Convert LF to CR (legacy)
            new_content = new_content.replace("\n", "\r")

        # Write the patched content atomically
        try:
            await asyncio.to_thread(target_path.parent.mkdir, parents=True, exist_ok=True)
            new_bytes = new_content.encode("utf-8")
            await asyncio.to_thread(atomic_write_bytes, target_path, new_bytes)
        except OSError as e:
            return ToolResult(error=f"Error writing patched file: {e}")

        # Format success message
        return self._format_success(
            apply_result,
            matching_patch,
            multi_file_warning,
        )

    def _find_matching_patch(
        self, patch_files: list[PatchFile], target_basename: str
    ) -> PatchFile | None:
        """Find the patch file matching the target basename.

        Args:
            patch_files: List of parsed patch files
            target_basename: Basename of the target file to match

        Returns:
            The matching PatchFile or None
        """
        for pf in patch_files:
            # Check various path forms
            if os.path.basename(pf.path) == target_basename:
                return pf
            if os.path.basename(pf.old_path) == target_basename:
                return pf
            if os.path.basename(pf.new_path) == target_basename:
                return pf
        return None

    def _format_dry_run_result(
        self,
        validation_result: Any,
        patch_file: PatchFile,
        warning_prefix: str,
    ) -> ToolResult:
        """Format the dry run result message."""
        hunk_count = len(patch_file.hunks)

        if validation_result.valid or validation_result.fixed_patch is not None:
            output = f"{warning_prefix}Dry run - no changes made:\n"
            output += f"  {patch_file.path}: {hunk_count} hunk(s) would apply"

            if validation_result.warnings:
                output += "\n  Warnings:"
                for warning in validation_result.warnings:
                    output += f"\n    - {warning}"

            if validation_result.fixed_patch is not None:
                output += "\n  Note: Patch would be auto-corrected before applying"

            return ToolResult(output=output)
        else:
            error = f"{warning_prefix}Dry run - patch would fail:\n"
            for err in validation_result.errors:
                error += f"  - {err}\n"
            return ToolResult(error=error.rstrip())

    def _format_validation_failure(
        self,
        validation_result: Any,
        patch_file: PatchFile,
    ) -> ToolResult:
        """Format a validation failure message."""
        error = f"Patch validation failed on {patch_file.path}:\n"
        for err in validation_result.errors:
            error += f"  - {err}\n"
        error += "No changes made."
        return ToolResult(error=error.rstrip())

    def _format_apply_failure(
        self,
        apply_result: Any,
        patch_file: PatchFile,
    ) -> ToolResult:
        """Format an application failure message."""
        error = f"Patch failed on {patch_file.path}:\n"

        if apply_result.applied_hunks:
            applied_str = ", ".join(str(i + 1) for i in apply_result.applied_hunks)
            error += f"  Hunks {applied_str}: applied\n"

        for hunk_idx, reason in apply_result.failed_hunks:
            error += f"  Hunk {hunk_idx + 1} failed: {reason}\n"

        error += "No changes made (atomic rollback)."
        return ToolResult(error=error)

    def _format_success(
        self,
        apply_result: Any,
        patch_file: PatchFile,
        warning_prefix: str,
    ) -> ToolResult:
        """Format a success message."""
        hunk_count = len(apply_result.applied_hunks)
        output = f"{warning_prefix}Applied patch to {patch_file.path}: {hunk_count} hunk(s) applied"

        if apply_result.warnings:
            for warning in apply_result.warnings:
                output += f"\n  Warning: {warning}"

        return ToolResult(output=output)


# Factory for dependency injection
patch_factory = file_skill_factory(PatchSkill)
