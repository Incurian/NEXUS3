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
from nexus3.core.paths import atomic_write_bytes
from nexus3.core.types import ToolResult
from nexus3.patch import (
    ApplyMode,
    HunkLineV2,
    HunkV2,
    PatchFile,
    PatchFileV2,
    RawLineV2,
    apply_patch_byte_strict,
    parse_unified_diff_v2,
    project_patch_file_v2_to_v1,
    validate_patch,
)
from nexus3.skill.base import FileSkill, file_skill_factory

HunkLinePrefix = Literal[" ", "-", "+"]


class PatchSkill(FileSkill):
    """Apply unified diffs to files with validation and multiple matching modes.

    Supports inline diffs or reading from .diff/.patch files.
    Validates patches before applying and can auto-fix common LLM errors.

    Example usage:
        # Apply inline diff
        patch(path="src/foo.py", diff=\"\"\"--- a/foo.py
        +++ b/foo.py
        @@ -1,3 +1,4 @@
         import os
        +import sys

         def main():
        \"\"\")

        # Apply from .diff file
        patch(path="src/foo.py", diff_file="changes.diff")

        # Use fuzzy matching for drifted code
        patch(path="src/foo.py", diff="...", mode="fuzzy")
    """

    @property
    def name(self) -> str:
        return "patch"

    @property
    def description(self) -> str:
        return (
            "Apply a unified diff to a file (strict/tolerant/fuzzy modes). "
            "Use for complex multi-line changes and diff-driven refactors. "
            "Prefer path= for the target file; target= remains a compatibility alias. "
            "Use dry_run=True to validate before applying and mode='fuzzy' for drifted code. "
            "Diff lines must be prefixed: ' ' context, '-' removal, '+' addition. "
            "When path/target is provided, single-file hunk-only diffs "
            "(`@@ ... @@` without `---`/`+++`) are normalized automatically."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Target file to patch (preferred). "
                        "Use this for consistency with other file-editing tools."
                    ),
                },
                "target": {
                    "type": "string",
                    "description": (
                        "Compatibility alias for path. "
                        "Prefer 'path' for new tool calls."
                    ),
                },
                "diff": {
                    "type": "string",
                    "description": (
                        "Unified diff content (inline). "
                        "Use either diff or diff_file, not both. "
                        "When path/target is provided, single-file hunk-only diffs "
                        "without file headers are normalized automatically."
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
                    "default": "byte_strict",
                    "description": (
                        "Patch fidelity engine: "
                        "byte_strict=AST-v2 parser with byte-fidelity apply path (default). "
                        "legacy is retired and rejected."
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
            "description": (
                "Provide exactly one file selector via 'path' (preferred) or "
                "'target' (compatibility alias). Runtime validation rejects "
                "missing selectors or conflicting values."
            ),
            "additionalProperties": False,
        }

    async def execute(
        self,
        path: str = "",
        target: str = "",
        diff: str | None = None,
        diff_file: str | None = None,
        mode: str = "strict",
        fidelity_mode: str = "byte_strict",
        fuzzy_threshold: float = 0.8,
        dry_run: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        """Apply a unified diff to the target file.

        Args:
            path: Preferred path to the file to patch
            target: Compatibility alias for path
            diff: Inline unified diff content
            diff_file: Path to a .diff/.patch file to read
            mode: Matching strictness (strict, tolerant, fuzzy)
            fidelity_mode: Patch engine fidelity (byte_strict only; legacy rejected)
            fuzzy_threshold: Similarity threshold for fuzzy mode (0.5-1.0)
            dry_run: If True, validate without applying changes

        Returns:
            ToolResult with success message or error
        """
        # Some tool-callers send empty-string placeholders for omitted alias/input
        # fields. Normalize those exact shapes before validation.
        if diff == "":
            diff = None
        if diff_file == "":
            diff_file = None

        # Keep explicit legacy rejection for callers using old migration flags.
        if fidelity_mode == "legacy":
            return ToolResult(
                error=(
                    "fidelity_mode='legacy' is no longer supported. "
                    "Use fidelity_mode='byte_strict' or omit the parameter."
                )
            )
        if fidelity_mode != "byte_strict":
            return ToolResult(
                error=(
                    f"Invalid fidelity_mode '{fidelity_mode}'. "
                    "Use: byte_strict"
                )
            )

        # Validate target path
        try:
            target_input, target_path, target_alias_used = self._resolve_target_argument(
                path=path,
                target=target,
            )
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

        original_diff_content = diff_content
        diff_content, normalization_note = self._normalize_hunk_only_diff(
            diff_content,
            target_path,
        )

        # Parse the diff with byte-strict AST-v2 only.
        patch_files: Sequence[PatchFileV2]
        try:
            patch_files = parse_unified_diff_v2(diff_content)
        except Exception as e:
            return ToolResult(error=f"Error parsing diff: {e}")

        if not patch_files:
            return ToolResult(
                error=self._format_no_hunks_error(original_diff_content, target_path)
            )

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
        result_prefix = (
            self._format_target_alias_note(target_alias_used)
            + normalization_note
            + multi_file_warning
        )

        if matching_error is not None:
            return ToolResult(error=matching_error)

        if matching_patch is None:
            file_list = ", ".join(pf.path for pf in patch_files)
            return ToolResult(
                error=f"No hunks found for target file '{target_basename}'. "
                f"Files in diff: {file_list}"
            )

        target_exists = await asyncio.to_thread(target_path.exists)

        # Read target file content (binary to detect line endings). New-file diffs
        # operate against an empty initial byte buffer when the target does not yet exist.
        if target_exists:
            try:
                raw_bytes = await asyncio.to_thread(target_path.read_bytes)
                target_content = raw_bytes.decode("utf-8", errors="surrogateescape")
            except OSError as e:
                return ToolResult(error=f"Error reading target file: {e}")
        elif matching_patch.is_new_file and not matching_patch.is_deleted:
            raw_bytes = b""
            target_content = ""
        else:
            return ToolResult(error=f"Target file not found: {target_input}")

        # Convert mode string to ApplyMode enum early (needed for validation decision)
        try:
            apply_mode = ApplyMode(mode)
        except ValueError:
            return ToolResult(error=f"Invalid mode '{mode}'. Use: strict, tolerant, fuzzy")

        # Validate the patch against target content
        validation_patch = project_patch_file_v2_to_v1(matching_patch)
        validation_result = validate_patch(validation_patch, target_content)

        patch_to_apply_v2 = matching_patch
        if validation_result.fixed_patch is not None:
            patch_to_apply_v2 = self._convert_patch_v1_to_v2(validation_result.fixed_patch)

        # For dry_run, return validation result
        if dry_run:
            return self._format_dry_run_result(
                validation_result,
                matching_patch,
                result_prefix,
            )

        # If validation failed and no auto-fix in STRICT mode, report errors.
        # For tolerant/fuzzy modes, proceed to byte-strict applier matching logic.
        if not validation_result.valid and validation_result.fixed_patch is None:
            if apply_mode == ApplyMode.STRICT:
                return self._format_validation_failure(
                    validation_result,
                    matching_patch,
                    result_prefix,
                )
            # Tolerant/fuzzy proceeds to applier-level matching.

        # Apply the patch
        apply_result = apply_patch_byte_strict(
            raw_bytes,
            patch_to_apply_v2,
            mode=apply_mode,
            fuzzy_threshold=fuzzy_threshold,
        )

        if not apply_result.success:
            return self._format_apply_failure(
                apply_result,
                matching_patch,
                result_prefix,
            )

        # Write the patched content atomically
        try:
            await asyncio.to_thread(target_path.parent.mkdir, parents=True, exist_ok=True)
            new_bytes = apply_result.new_content.encode("utf-8", errors="surrogateescape")
            await asyncio.to_thread(atomic_write_bytes, target_path, new_bytes)
        except OSError as e:
            return ToolResult(error=f"Error writing patched file: {e}")

        # Format success message
        return self._format_success(
            apply_result,
            matching_patch,
            result_prefix,
        )

    def _find_matching_patch(
        self,
        patch_files: Sequence[PatchFileV2],
        target_path: Path,
    ) -> tuple[PatchFileV2 | None, str | None]:
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
        basename_matches: list[PatchFileV2] = []
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

    def _patch_path_candidates(self, patch_file: PatchFileV2) -> tuple[str, ...]:
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
        patch_file: PatchFileV2,
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
        patch_file: PatchFileV2,
        warning_prefix: str,
    ) -> ToolResult:
        """Format a validation failure message."""
        error = f"{warning_prefix}Patch validation failed on {patch_file.path}:\n"
        for err in validation_result.errors:
            error += f"  - {err}\n"
        error += "No changes made."
        return ToolResult(error=error.rstrip())

    def _format_apply_failure(
        self,
        apply_result: Any,
        patch_file: PatchFileV2,
        warning_prefix: str,
    ) -> ToolResult:
        """Format an application failure message."""
        error = f"{warning_prefix}Patch failed on {patch_file.path}:\n"

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
        patch_file: PatchFileV2,
        warning_prefix: str,
    ) -> ToolResult:
        """Format a success message."""
        hunk_count = len(apply_result.applied_hunks)
        output = f"{warning_prefix}Applied patch to {patch_file.path}: {hunk_count} hunk(s) applied"

        if apply_result.warnings:
            for warning in apply_result.warnings:
                output += f"\n  Warning: {warning}"

        return ToolResult(output=output)

    def _resolve_target_argument(self, *, path: str, target: str) -> tuple[str, Path, bool]:
        """Resolve preferred `path` / legacy `target` arguments to one file path."""
        if path and target:
            path_resolved = self._validate_path(path)
            target_resolved = self._validate_path(target)
            if path_resolved != target_resolved:
                raise ValueError(
                    "Cannot provide both 'path' and 'target' with different values."
                )
            return path, path_resolved, False

        selected = path or target
        return selected, self._validate_path(selected), bool(target and not path)

    def _format_target_alias_note(self, target_alias_used: bool) -> str:
        """Return a compatibility reminder when callers still use target=."""
        if not target_alias_used:
            return ""
        return "Compatibility note: prefer 'path=' over legacy 'target=' for patch.\n"

    def _normalize_hunk_only_diff(
        self,
        diff_content: str,
        target_path: Path,
    ) -> tuple[str, str]:
        """Wrap a single-file hunk-only diff with synthetic file headers."""
        if not self._looks_like_hunk_only_diff(diff_content):
            return diff_content, ""

        diff_path = self._path_for_synthetic_diff_headers(target_path)
        newline = "\r\n" if "\r\n" in diff_content else "\n"
        wrapped = (
            f"--- a/{diff_path}{newline}"
            f"+++ b/{diff_path}{newline}"
            f"{diff_content}"
        )
        note = f"Note: normalized hunk-only diff using target path '{diff_path}'.\n"
        return wrapped, note

    def _looks_like_hunk_only_diff(self, diff_content: str) -> bool:
        """Return True for bare `@@` hunks without file headers."""
        saw_hunk = False
        for raw_line in diff_content.splitlines():
            line = raw_line.lstrip("\ufeff")
            if line.startswith("diff --git "):
                return False
            if line.startswith("--- ") or line.startswith("+++ "):
                return False
            if line.startswith("@@"):
                saw_hunk = True
        return saw_hunk

    def _format_no_hunks_error(self, diff_content: str, target_path: Path) -> str:
        """Return a targeted parse error for hunk-only input when possible."""
        if self._looks_like_hunk_only_diff(diff_content):
            diff_path = self._path_for_synthetic_diff_headers(target_path)
            return (
                f"Detected hunk-only diff for target '{diff_path}', but it is not a "
                "valid unified diff hunk. Include unified diff file headers ('---' / "
                "'+++') or provide a valid @@ hunk with leading line prefixes "
                "(' ', '-', '+')."
            )
        return "No patch hunks found in diff"

    def _path_for_synthetic_diff_headers(self, target_path: Path) -> str:
        """Return the best path string to use in synthesized diff headers."""
        relative_target = self._target_path_relative_to_cwd(target_path)
        candidate = relative_target if relative_target is not None else str(target_path)
        normalized = self._normalize_patch_path(candidate)
        return normalized or target_path.name


# Factory for dependency injection
patch_factory = file_skill_factory(PatchSkill)
