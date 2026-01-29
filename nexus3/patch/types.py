"""Types for unified diff patch representation.

This module provides dataclasses for representing unified diff patches
in a structured format suitable for parsing, validation, and application.
"""

from dataclasses import dataclass, field


@dataclass
class Hunk:
    """A single hunk in a unified diff.

    A hunk represents a contiguous section of changes in a file,
    including context lines before and after the actual modifications.

    Attributes:
        old_start: Line number in original file (1-indexed)
        old_count: Number of lines from original (context + removed)
        new_start: Line number in new file (1-indexed)
        new_count: Number of lines in new version (context + added)
        lines: List of (prefix, content) tuples where prefix is:
            ' ' = context line (unchanged)
            '-' = line removed from original
            '+' = line added in new version
        context: Optional function/class context from @@ line
    """

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[tuple[str, str]] = field(default_factory=list)
    context: str = ""

    def count_removals(self) -> int:
        """Count lines being removed (- prefix)."""
        return sum(1 for prefix, _ in self.lines if prefix == "-")

    def count_additions(self) -> int:
        """Count lines being added (+ prefix)."""
        return sum(1 for prefix, _ in self.lines if prefix == "+")

    def count_context(self) -> int:
        """Count context lines (space prefix)."""
        return sum(1 for prefix, _ in self.lines if prefix == " ")

    def compute_counts(self) -> tuple[int, int]:
        """Compute actual old_count and new_count from lines.

        Returns:
            Tuple of (old_count, new_count) based on actual line prefixes.
            old_count = context + removals
            new_count = context + additions
        """
        context = self.count_context()
        removals = self.count_removals()
        additions = self.count_additions()
        return (context + removals, context + additions)


@dataclass
class PatchFile:
    """A patch for a single file.

    Represents all the changes to be applied to a single file,
    which may consist of multiple non-contiguous hunks.

    Attributes:
        old_path: Path to original file (from --- line, without a/ prefix)
        new_path: Path to new file (from +++ line, without b/ prefix)
        hunks: List of Hunk objects representing changes
        is_new_file: True if this is a new file (old_path is /dev/null)
        is_deleted: True if file is being deleted (new_path is /dev/null)
    """

    old_path: str
    new_path: str
    hunks: list[Hunk] = field(default_factory=list)
    is_new_file: bool = False
    is_deleted: bool = False

    @property
    def path(self) -> str:
        """Get the effective file path (new_path for edits/creates, old_path for deletes)."""
        if self.is_deleted:
            return self.old_path
        return self.new_path


@dataclass
class PatchSet:
    """A collection of patches for multiple files.

    Represents a complete diff that may affect multiple files,
    as produced by commands like `git diff` or `diff -ru`.

    Attributes:
        files: List of PatchFile objects, one per affected file
    """

    files: list[PatchFile] = field(default_factory=list)

    def get_file(self, path: str) -> PatchFile | None:
        """Get patch for a specific file path."""
        for pf in self.files:
            if pf.path == path or pf.old_path == path or pf.new_path == path:
                return pf
        return None

    def file_paths(self) -> list[str]:
        """Get list of all affected file paths."""
        return [pf.path for pf in self.files]
