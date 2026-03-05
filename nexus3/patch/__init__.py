"""Patch module for parsing, validating, and applying unified diffs.

This module provides tools for working with unified diff format patches,
commonly used by git diff, diff -u, and other tools.

Main components:
- Types: Hunk, PatchFile, PatchSet - structured representation of diffs
- Parser: parse_unified_diff() and parse_unified_diff_v2() - convert diff text to objects
- Validator: validate_patch() - verify patches against file content
- Applier: apply_patch() plus apply_patch_byte_strict() for AST-v2 byte fidelity

Example usage:
    >>> from nexus3.patch import parse_unified_diff, validate_patch, apply_patch
    >>> diff_text = '''
    ... --- a/file.py
    ... +++ b/file.py
    ... @@ -1,3 +1,4 @@
    ...  line1
    ... -line2
    ... +new_line
    ... +another_line
    ...  line3
    ... '''
    >>> files = parse_unified_diff(diff_text)
    >>> result = validate_patch(files[0], "line1\\nline2\\nline3\\n")
    >>> result.valid
    True
    >>> apply_result = apply_patch("line1\\nline2\\nline3\\n", files[0])
    >>> apply_result.success
    True
"""

from nexus3.patch.applier import (
    ApplyMode,
    ApplyResult,
    apply_patch,
    apply_patch_byte_strict,
)
from nexus3.patch.ast_v2 import (
    HunkLineV2,
    HunkV2,
    PatchFileV2,
    RawLineV2,
    project_patch_file_v2_to_v1,
    project_patch_files_v2_to_v1,
)
from nexus3.patch.parser import parse_unified_diff, parse_unified_diff_v2
from nexus3.patch.types import Hunk, PatchFile, PatchSet
from nexus3.patch.validator import ValidationResult, validate_patch, validate_patch_set

__all__ = [
    # Types
    "Hunk",
    "PatchFile",
    "PatchSet",
    "RawLineV2",
    "HunkLineV2",
    "HunkV2",
    "PatchFileV2",
    "project_patch_file_v2_to_v1",
    "project_patch_files_v2_to_v1",
    # Parser
    "parse_unified_diff",
    "parse_unified_diff_v2",
    # Validator
    "ValidationResult",
    "validate_patch",
    "validate_patch_set",
    # Applier
    "ApplyMode",
    "ApplyResult",
    "apply_patch",
    "apply_patch_byte_strict",
]
