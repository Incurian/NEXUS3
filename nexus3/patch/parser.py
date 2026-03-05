"""Parser for unified diff format.

This module provides functions to parse unified diff text into
structured PatchFile and Hunk objects.
"""

import re
from collections.abc import Iterator
from typing import cast

from nexus3.patch.ast_v2 import (
    HunkLineV2,
    HunkV2,
    LinePrefix,
    NewlineToken,
    PatchFileV2,
    RawLineV2,
)
from nexus3.patch.types import Hunk, PatchFile

# Pattern for hunk header: @@ -old_start[,old_count] +new_start[,new_count] @@ [context]
HUNK_HEADER_RE = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$"
)

# Pattern for file header in standard unified diff format
UNIFIED_OLD_RE = re.compile(r"^--- (.+?)(?:\t.*)?$")
UNIFIED_NEW_RE = re.compile(r"^\+\+\+ (.+?)(?:\t.*)?$")

# Pattern for git extended diff format
GIT_DIFF_RE = re.compile(r"^diff --git a/(.+) b/(.+)$")


def _strip_path_prefix(path: str) -> str:
    """Strip a/ or b/ prefix from path if present."""
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path


def _parse_hunk_header(line: str) -> Hunk | None:
    """Parse a hunk header line into a Hunk object.

    Args:
        line: Line starting with @@

    Returns:
        Hunk object with header values, or None if line is malformed.
    """
    match = HUNK_HEADER_RE.match(line)
    if not match:
        return None

    old_start = int(match.group(1))
    # Count defaults to 1 if omitted (e.g., @@ -1 +1,2 @@)
    old_count = int(match.group(2)) if match.group(2) else 1
    new_start = int(match.group(3))
    new_count = int(match.group(4)) if match.group(4) else 1
    context = match.group(5).strip()

    return Hunk(
        old_start=old_start,
        old_count=old_count,
        new_start=new_start,
        new_count=new_count,
        lines=[],
        context=context,
    )


def _parse_hunk_lines(lines_iter: Iterator[str], hunk: Hunk) -> None:
    """Parse hunk content lines and add them to the hunk.

    Args:
        lines_iter: Iterator over remaining lines
        hunk: Hunk object to add lines to

    Reads lines until encountering another hunk header, file header,
    or end of iterator.
    """
    for line in lines_iter:
        # Stop at next hunk or file boundary
        if line.startswith("@@"):
            # Put the line back by returning; caller handles this
            raise _HunkBoundary(line)
        if line.startswith("---") or line.startswith("diff --git"):
            raise _FileBoundary(line)

        # Handle the "no newline at end of file" marker
        if line.startswith("\\ No newline at end of file"):
            # This is a marker, not actual diff content
            continue

        # Parse by prefix
        if line and line[0] in " -+":
            prefix = line[0]
            content = line[1:]
            hunk.lines.append((prefix, content))
        elif line == "":
            # Empty line in diff - treat as context line
            hunk.lines.append((" ", ""))


class _HunkBoundary(Exception):
    """Internal exception to signal a new hunk was encountered."""

    def __init__(self, line: str) -> None:
        self.line = line


class _FileBoundary(Exception):
    """Internal exception to signal a new file was encountered."""

    def __init__(self, line: str) -> None:
        self.line = line


def _parse_single_file(lines: list[str], start_idx: int) -> tuple[PatchFile | None, int]:
    """Parse a single file's diff starting at given index.

    Args:
        lines: All lines of the diff
        start_idx: Index to start parsing from

    Returns:
        Tuple of (PatchFile or None, next_index)
    """
    idx = start_idx
    n = len(lines)

    if idx >= n:
        return None, idx

    old_path = ""
    new_path = ""

    # Handle git extended format: diff --git a/path b/path
    if lines[idx].startswith("diff --git"):
        match = GIT_DIFF_RE.match(lines[idx])
        if match:
            old_path = match.group(1)
            new_path = match.group(2)
        idx += 1

        # Skip git metadata lines (index, mode, etc.) until we hit --- or @@
        while idx < n:
            line = lines[idx]
            if line.startswith("---") or line.startswith("@@"):
                break
            if line.startswith("new file mode"):
                pass  # Will detect from /dev/null
            if line.startswith("deleted file mode"):
                pass  # Will detect from /dev/null
            idx += 1

    # Parse --- line (may not exist for new files in some formats)
    if idx < n and lines[idx].startswith("---"):
        match = UNIFIED_OLD_RE.match(lines[idx])
        if match:
            old_path = _strip_path_prefix(match.group(1))
        idx += 1

    # Parse +++ line
    if idx < n and lines[idx].startswith("+++"):
        match = UNIFIED_NEW_RE.match(lines[idx])
        if match:
            new_path = _strip_path_prefix(match.group(1))
        idx += 1

    # If we have no paths, this isn't a valid file section
    if not old_path and not new_path:
        return None, start_idx + 1

    # Detect new file / deleted file
    is_new_file = old_path == "/dev/null"
    is_deleted = new_path == "/dev/null"

    # Normalize /dev/null paths
    if is_new_file:
        old_path = new_path
    if is_deleted:
        new_path = old_path

    patch_file = PatchFile(
        old_path=old_path,
        new_path=new_path,
        hunks=[],
        is_new_file=is_new_file,
        is_deleted=is_deleted,
    )

    # Parse hunks
    while idx < n:
        line = lines[idx]

        # Check for next file
        is_new_file_header = (
            line.startswith("---") and idx + 1 < n and lines[idx + 1].startswith("+++")
        )
        if line.startswith("diff --git") or is_new_file_header:
            break

        # Parse hunk
        if line.startswith("@@"):
            hunk = _parse_hunk_header(line)
            if hunk is None:
                # Malformed hunk header, skip this line
                idx += 1
                continue

            idx += 1

            # Parse hunk content
            while idx < n:
                line = lines[idx]

                # Stop at next hunk or file
                if line.startswith("@@"):
                    break
                if line.startswith("diff --git"):
                    break
                if line.startswith("---") and idx + 1 < n and lines[idx + 1].startswith("+++"):
                    break

                # Handle no newline marker
                if line.startswith("\\ No newline at end of file"):
                    idx += 1
                    continue

                # Parse by prefix
                if line and line[0] in " -+":
                    prefix = line[0]
                    content = line[1:]
                    hunk.lines.append((prefix, content))
                elif line == "":
                    # Empty line in diff - treat as blank context line
                    # LLMs often forget the space prefix for blank lines
                    # In valid unified diff, blank context = " \n" not "\n"
                    hunk.lines.append((" ", ""))

                idx += 1

            patch_file.hunks.append(hunk)
        else:
            idx += 1

    return patch_file, idx


def parse_unified_diff(text: str) -> list[PatchFile]:
    """Parse unified diff text into structured PatchFile objects.

    Handles:
    - Standard unified diff format (--- a/path, +++ b/path, @@ ... @@)
    - Git extended format (diff --git a/path b/path)
    - Context lines (space prefix), removals (-), additions (+)
    - '\\ No newline at end of file' marker
    - Files with /dev/null paths (new files, deletions)

    Args:
        text: Unified diff text to parse

    Returns:
        List of PatchFile objects, one per file in the diff.
        Returns empty list if text cannot be parsed as a valid diff.

    Example:
        >>> diff_text = '''
        ... --- a/file.py
        ... +++ b/file.py
        ... @@ -1,3 +1,4 @@
        ...  context
        ... -removed
        ... +added
        ...  more context
        ... '''
        >>> files = parse_unified_diff(diff_text)
        >>> len(files)
        1
        >>> files[0].path
        'file.py'
    """
    if not text or not text.strip():
        return []

    lines = text.splitlines()
    result: list[PatchFile] = []
    idx = 0

    while idx < len(lines):
        # Skip empty lines and lines that aren't file boundaries
        line = lines[idx]
        if not line or not (line.startswith("diff --git") or line.startswith("---")):
            idx += 1
            continue

        patch_file, idx = _parse_single_file(lines, idx)
        if patch_file is not None:
            if patch_file.hunks or patch_file.is_new_file or patch_file.is_deleted:
                result.append(patch_file)

    return result


def _split_line_newline_token(line_with_newline: str) -> tuple[str, NewlineToken]:
    """Split a line with terminator into text and normalized newline token."""
    if line_with_newline.endswith("\r\n"):
        return line_with_newline[:-2], "\r\n"
    if line_with_newline.endswith("\n"):
        return line_with_newline[:-1], "\n"
    if line_with_newline.endswith("\r"):
        return line_with_newline[:-1], "\r"
    return line_with_newline, ""


def _split_raw_lines_v2(text: str) -> list[RawLineV2]:
    """Split source text into raw AST-v2 lines while retaining newline metadata."""
    raw_lines: list[RawLineV2] = []
    for line_with_newline in text.splitlines(keepends=True):
        line_text, newline = _split_line_newline_token(line_with_newline)
        raw_lines.append(RawLineV2.from_text(line_text, newline))
    return raw_lines


def _parse_hunk_header_v2(line: RawLineV2) -> HunkV2 | None:
    """Parse an AST-v2 hunk header line."""
    match = HUNK_HEADER_RE.match(line.text)
    if not match:
        return None

    old_start = int(match.group(1))
    old_count = int(match.group(2)) if match.group(2) else 1
    new_start = int(match.group(3))
    new_count = int(match.group(4)) if match.group(4) else 1
    context = match.group(5).strip()

    return HunkV2(
        old_start=old_start,
        old_count=old_count,
        new_start=new_start,
        new_count=new_count,
        lines=[],
        context=context,
        header_line=line,
    )


def _parse_single_file_v2(
    lines: list[RawLineV2], start_idx: int
) -> tuple[PatchFileV2 | None, int]:
    """Parse a single file patch as AST v2."""
    idx = start_idx
    n = len(lines)

    if idx >= n:
        return None, idx

    old_path = ""
    new_path = ""
    diff_header_line: RawLineV2 | None = None
    old_header_line: RawLineV2 | None = None
    new_header_line: RawLineV2 | None = None

    if lines[idx].text.startswith("diff --git"):
        diff_header_line = lines[idx]
        match = GIT_DIFF_RE.match(lines[idx].text)
        if match:
            old_path = match.group(1)
            new_path = match.group(2)
        idx += 1

        while idx < n:
            line_text = lines[idx].text
            if line_text.startswith("---") or line_text.startswith("@@"):
                break
            idx += 1

    if idx < n and lines[idx].text.startswith("---"):
        old_header_line = lines[idx]
        match = UNIFIED_OLD_RE.match(lines[idx].text)
        if match:
            old_path = _strip_path_prefix(match.group(1))
        idx += 1

    if idx < n and lines[idx].text.startswith("+++"):
        new_header_line = lines[idx]
        match = UNIFIED_NEW_RE.match(lines[idx].text)
        if match:
            new_path = _strip_path_prefix(match.group(1))
        idx += 1

    if not old_path and not new_path:
        return None, start_idx + 1

    is_new_file = old_path == "/dev/null"
    is_deleted = new_path == "/dev/null"
    if is_new_file:
        old_path = new_path
    if is_deleted:
        new_path = old_path

    patch_file = PatchFileV2(
        old_path=old_path,
        new_path=new_path,
        hunks=[],
        is_new_file=is_new_file,
        is_deleted=is_deleted,
        diff_header_line=diff_header_line,
        old_header_line=old_header_line,
        new_header_line=new_header_line,
    )

    while idx < n:
        line_text = lines[idx].text
        is_new_file_header = (
            line_text.startswith("---")
            and idx + 1 < n
            and lines[idx + 1].text.startswith("+++")
        )
        if line_text.startswith("diff --git") or is_new_file_header:
            break

        if line_text.startswith("@@"):
            hunk = _parse_hunk_header_v2(lines[idx])
            if hunk is None:
                idx += 1
                continue

            idx += 1
            while idx < n:
                current_line = lines[idx]
                current_text = current_line.text
                if current_text.startswith("@@") or current_text.startswith("diff --git"):
                    break
                if (
                    current_text.startswith("---")
                    and idx + 1 < n
                    and lines[idx + 1].text.startswith("+++")
                ):
                    break

                if current_text.startswith("\\ No newline at end of file"):
                    if hunk.lines:
                        hunk.lines[-1].no_newline_at_eof = True
                    idx += 1
                    continue

                if current_text and current_text[0] in " -+":
                    prefix = cast(LinePrefix, current_text[0])
                    hunk.lines.append(
                        HunkLineV2.from_raw_line(
                            prefix=prefix,
                            content=current_text[1:],
                            raw_line=current_line,
                        )
                    )
                elif current_text == "":
                    hunk.lines.append(
                        HunkLineV2.from_raw_line(
                            prefix=" ",
                            content="",
                            raw_line=current_line,
                        )
                    )

                idx += 1

            patch_file.hunks.append(hunk)
        else:
            idx += 1

    return patch_file, idx


def parse_unified_diff_v2(text: str) -> list[PatchFileV2]:
    """Parse unified diff text into AST-v2 patch files with raw-line metadata."""
    if not text or not text.strip():
        return []

    lines = _split_raw_lines_v2(text)
    result: list[PatchFileV2] = []
    idx = 0

    while idx < len(lines):
        line = lines[idx].text
        if not line or not (line.startswith("diff --git") or line.startswith("---")):
            idx += 1
            continue

        patch_file, idx = _parse_single_file_v2(lines, idx)
        if patch_file is not None:
            if patch_file.hunks or patch_file.is_new_file or patch_file.is_deleted:
                result.append(patch_file)

    return result
