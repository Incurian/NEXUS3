"""Typed AST v2 models for unified diff patches.

AST v2 is an additive API surface that keeps the legacy patch model intact
while carrying enough raw line metadata for future byte-fidelity paths.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from nexus3.patch.types import Hunk, PatchFile

LinePrefix = Literal[" ", "-", "+"]
NewlineToken = Literal["", "\n", "\r\n", "\r"]


def encode_patch_text(text: str) -> bytes:
    """Encode patch text to bytes in a reversible way for Python str payloads."""
    return text.encode("utf-8", errors="surrogatepass")


@dataclass(frozen=True, slots=True)
class RawLineV2:
    """Raw diff line payload with explicit newline metadata."""

    text: str
    raw_bytes: bytes
    newline: NewlineToken

    @classmethod
    def from_text(cls, text: str, newline: NewlineToken) -> "RawLineV2":
        """Build a RawLineV2 from parsed text/newline components."""
        return cls(text=text, raw_bytes=encode_patch_text(text), newline=newline)

    @property
    def has_newline(self) -> bool:
        """True when the source line ended with a recognized newline token."""
        return self.newline != ""


@dataclass(slots=True)
class HunkLineV2:
    """A parsed hunk line with raw bytes and newline metadata."""

    prefix: LinePrefix
    content: str
    raw_content_bytes: bytes
    raw_line: RawLineV2
    no_newline_at_eof: bool = False

    @classmethod
    def from_raw_line(
        cls,
        prefix: LinePrefix,
        content: str,
        raw_line: RawLineV2,
    ) -> "HunkLineV2":
        """Build a hunk line from an already split raw line."""
        return cls(
            prefix=prefix,
            content=content,
            raw_content_bytes=encode_patch_text(content),
            raw_line=raw_line,
        )


@dataclass(slots=True)
class HunkV2:
    """A single hunk in AST v2."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[HunkLineV2] = field(default_factory=list)
    context: str = ""
    header_line: RawLineV2 | None = None

    def count_removals(self) -> int:
        """Count lines being removed (- prefix)."""
        return sum(1 for line in self.lines if line.prefix == "-")

    def count_additions(self) -> int:
        """Count lines being added (+ prefix)."""
        return sum(1 for line in self.lines if line.prefix == "+")

    def count_context(self) -> int:
        """Count context lines (space prefix)."""
        return sum(1 for line in self.lines if line.prefix == " ")


@dataclass(slots=True)
class PatchFileV2:
    """A single-file patch in AST v2."""

    old_path: str
    new_path: str
    hunks: list[HunkV2] = field(default_factory=list)
    is_new_file: bool = False
    is_deleted: bool = False
    diff_header_line: RawLineV2 | None = None
    old_header_line: RawLineV2 | None = None
    new_header_line: RawLineV2 | None = None

    @property
    def path(self) -> str:
        """Get the effective file path (new_path for edits/creates, old_path for deletes)."""
        if self.is_deleted:
            return self.old_path
        return self.new_path


def project_hunk_v2_to_v1(hunk: HunkV2) -> Hunk:
    """Project a v2 hunk into the legacy v1 hunk model."""
    return Hunk(
        old_start=hunk.old_start,
        old_count=hunk.old_count,
        new_start=hunk.new_start,
        new_count=hunk.new_count,
        lines=[(line.prefix, line.content) for line in hunk.lines],
        context=hunk.context,
    )


def project_patch_file_v2_to_v1(patch: PatchFileV2) -> PatchFile:
    """Project a v2 single-file patch into the legacy v1 patch model."""
    return PatchFile(
        old_path=patch.old_path,
        new_path=patch.new_path,
        hunks=[project_hunk_v2_to_v1(hunk) for hunk in patch.hunks],
        is_new_file=patch.is_new_file,
        is_deleted=patch.is_deleted,
    )


def project_patch_files_v2_to_v1(patches: Sequence[PatchFileV2]) -> list[PatchFile]:
    """Project v2 patch files into legacy v1 patch files."""
    return [project_patch_file_v2_to_v1(patch) for patch in patches]


def coerce_patch_file_v1(patch: PatchFile | PatchFileV2) -> PatchFile:
    """Return a v1 patch file regardless of v1/v2 caller input."""
    if isinstance(patch, PatchFileV2):
        return project_patch_file_v2_to_v1(patch)
    return patch

