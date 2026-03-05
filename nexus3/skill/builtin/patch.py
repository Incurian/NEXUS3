"""Patch skill for applying unified diffs.

This skill provides the ability to apply unified diff patches to files,
with validation and multiple matching modes (strict, tolerant, fuzzy).
Supports inline diffs or reading from .diff/.patch files.
"""

import asyncio
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal, cast

from nexus3.core.errors import PathSecurityError
from nexus3.core.paths import atomic_write_bytes, detect_line_ending
from nexus3.core.types import ToolResult
from nexus3.patch import (
    ApplyMode,
    HunkLineV2,
    HunkV2,
    PatchFile,
    PatchFileV2,
    RawLineV2,
    apply_patch,
    apply_patch_byte_strict,
    parse_unified_diff,
    parse_unified_diff_v2,
    project_patch_file_v2_to_v1,
    validate_patch,
)
from nexus3.skill.base import FileSkill, file_skill_factory

PatchFileLike = PatchFile | PatchFileV2
FidelityMode = Literal["legacy", "byte_strict"]
HunkLinePrefix = Literal[" ", "-", "+"]


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
            "Apply a unified diff to a file (strict/tolerant/fuzzy modes). "
            "Use for complex multi-line changes and diff-driven refactors. "
            "Use dry_run=True to validate before applying and mode='fuzzy' for drifted code. "
            "Diff lines must be prefixed: ' ' context, '-' removal, '+' addition."
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
                "fidelity_mode": {
                    "type": "string",
                    "enum": ["legacy", "byte_strict"],
                    "default": "legacy",
                    "description": (
                        "Patch fidelity engine: "
                        "legacy=existing parser/applier flow, "
                        "byte_strict=AST-v2 parser with byte-fidelity apply path"
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
        fidelity_mode: str = "legacy",
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
            fidelity_mode: Patch engine fidelity (legacy, byte_strict)
            fuzzy_threshold: Similarity threshold for fuzzy mode (0.5-1.0)
            dry_run: If True, validate without applying changes

        Returns:
            ToolResult with success message or error
        """
        # Validate fidelity mode before any filesystem work
        if fidelity_mode not in ("legacy", "byte_strict"):
            return ToolResult(
                error=(
                    f"Invalid fidelity_mode '{fidelity_mode}'. "
                    "Use: legacy, byte_strict"
                )
            )
        selected_fidelity = cast(FidelityMode, fidelity_mode)

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
        patch_files: Sequence[PatchFileLike]
        try:
            if selected_fidelity == "byte_strict":
                patch_files = parse_unified_diff_v2(diff_content)
            else:
                patch_files = parse_unified_diff(diff_content)
        except Exception as e:
            return ToolResult(error=f"Error parsing diff: {e}")

        if not patch_files:
            return ToolResult(error="No patch hunks found in diff")

        # Find hunks matching the target file.
        target_basename = target_path.name
        matching_patch, matching_error = self._find_matching_patch(patch_files, target_path)

        # Build warning message for multi-file diffs
        multi_file_warning = ""
        if len(patch_files) > 1:
            multi_file_warning = (
                f"Diff contains {len(patch_files)} files, "
                f"applying only hunks for {target_basename}\n"
            )

        if matching_error is not None:
            return ToolResult(error=matching_error)

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
        validation_patch = (
            project_patch_file_v2_to_v1(matching_patch)
            if isinstance(matching_patch, PatchFileV2)
            else matching_patch
        )
        validation_result = validate_patch(validation_patch, target_content)

        patch_to_apply_v2: PatchFileV2 | None = None
        if selected_fidelity == "byte_strict":
            if not isinstance(matching_patch, PatchFileV2):
                return ToolResult(error="Internal error: expected AST-v2 patch in byte_strict mode")
            patch_to_apply_v2 = matching_patch
            if validation_result.fixed_patch is not None:
                patch_to_apply_v2 = self._convert_patch_v1_to_v2(validation_result.fixed_patch)
        patch_to_apply_v1 = validation_result.fixed_patch or validation_patch

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
        if selected_fidelity == "byte_strict":
            if patch_to_apply_v2 is None:
                return ToolResult(error="Internal error: missing AST-v2 patch for byte_strict mode")
            apply_result = apply_patch_byte_strict(
                target_content,
                patch_to_apply_v2,
                mode=apply_mode,
                fuzzy_threshold=fuzzy_threshold,
            )
        else:
            apply_result = apply_patch(
                target_content,
                patch_to_apply_v1,
                mode=apply_mode,
                fuzzy_threshold=fuzzy_threshold,
            )

        if not apply_result.success:
            return self._format_apply_failure(apply_result, matching_patch)

        # Convert back to original line endings and write atomically
        new_content = apply_result.new_content
        if selected_fidelity == "legacy":
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
        self,
        patch_files: Sequence[PatchFileLike],
        target_path: Path,
    ) -> tuple[PatchFileLike | None, str | None]:
        """Find the patch file matching target path.

        Args:
            patch_files: List of parsed patch files
            target_path: Resolved target file path

        Returns:
            Tuple of (matching patch file, error message).
            Error message is set for ambiguity fail-closed behavior.
        """
        target_basename = target_path.name
        target_display = str(target_path)
        target_exact_candidates: list[str] = []

        relative_target = self._target_path_relative_to_cwd(target_path)
        if relative_target is not None:
            normalized_relative = self._normalize_patch_path(relative_target)
            if normalized_relative:
                target_exact_candidates.append(normalized_relative)
                target_display = normalized_relative

        normalized_absolute = self._normalize_patch_path(str(target_path))
        if normalized_absolute and normalized_absolute not in target_exact_candidates:
            target_exact_candidates.append(normalized_absolute)

        # First pass: exact path matches (prefer relative-to-cwd when available).
        for exact_candidate in target_exact_candidates:
            for patch_file in patch_files:
                if exact_candidate in self._patch_path_candidates(patch_file):
                    return patch_file, None

        # Second pass: basename fallback with explicit ambiguity handling.
        basename_matches: list[PatchFileLike] = []
        for patch_file in patch_files:
            if any(
                os.path.basename(candidate) == target_basename
                for candidate in self._patch_path_candidates(patch_file)
            ):
                basename_matches.append(patch_file)

        if len(basename_matches) == 1:
            return basename_matches[0], None

        if len(basename_matches) > 1:
            ambiguous_paths = ", ".join(
                dict.fromkeys(
                    self._normalize_patch_path(pf.path) or pf.path for pf in basename_matches
                )
            )
            return (
                None,
                (
                    f"Ambiguous patch target '{target_display}': no exact path match was found, "
                    f"and basename '{target_basename}' matches multiple diff files: "
                    f"{ambiguous_paths}. "
                    "Use a target path that matches one diff file path exactly."
                ),
            )

        return None, None

    def _patch_path_candidates(self, patch_file: PatchFileLike) -> tuple[str, ...]:
        """Get normalized unique path candidates for a patch file."""
        normalized_paths: list[str] = []
        for raw_path in (patch_file.path, patch_file.old_path, patch_file.new_path):
            normalized = self._normalize_patch_path(raw_path)
            if normalized and normalized not in normalized_paths:
                normalized_paths.append(normalized)
        return tuple(normalized_paths)

    def _normalize_patch_path(self, patch_path: str) -> str:
        """Normalize diff path for reliable comparisons across formats."""
        normalized = os.path.normpath(patch_path.replace("\\", "/"))
        if normalized == ".":
            return ""
        if normalized.startswith("./"):
            return normalized[2:]
        return normalized

    def _target_path_relative_to_cwd(self, target_path: Path) -> str | None:
        """Return target path relative to agent cwd when target is inside it."""
        cwd_path = self._services.get_cwd().resolve()
        try:
            return target_path.relative_to(cwd_path).as_posix()
        except ValueError:
            return None

    def _convert_patch_v1_to_v2(self, patch_file: PatchFile) -> PatchFileV2:
        """Convert a legacy PatchFile to AST-v2 for byte_strict apply flow."""

        def _convert_hunk_line(prefix: str, content: str) -> HunkLineV2:
            if prefix not in (" ", "-", "+"):
                raise ValueError(f"Invalid hunk line prefix '{prefix}' in patch data")
            line_prefix = cast(HunkLinePrefix, prefix)
            raw_line = RawLineV2.from_text(f"{line_prefix}{content}", "\n")
            return HunkLineV2.from_raw_line(
                prefix=line_prefix,
                content=content,
                raw_line=raw_line,
            )

        hunks_v2 = [
            HunkV2(
                old_start=hunk.old_start,
                old_count=hunk.old_count,
                new_start=hunk.new_start,
                new_count=hunk.new_count,
                lines=[_convert_hunk_line(prefix, content) for prefix, content in hunk.lines],
                context=hunk.context,
            )
            for hunk in patch_file.hunks
        ]

        return PatchFileV2(
            old_path=patch_file.old_path,
            new_path=patch_file.new_path,
            hunks=hunks_v2,
            is_new_file=patch_file.is_new_file,
            is_deleted=patch_file.is_deleted,
        )

    def _format_dry_run_result(
        self,
        validation_result: Any,
        patch_file: PatchFileLike,
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
        patch_file: PatchFileLike,
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
        patch_file: PatchFileLike,
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
        patch_file: PatchFileLike,
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
