#!/usr/bin/env python3
"""
Recursively find files with specific extensions and concatenate their contents.

Cross-platform compatible: Linux, macOS, Windows.

Usage: concat_files.py <extension1> [extension2] ... [options]

Options:
    --dir=PATH        Search directory (default: current directory)
    --lines=N         Max lines per file (default: unlimited)
    --max-total=N     Stop after N total lines (default: unlimited)
    --exclude=PATTERN Exclude pattern (repeatable)
    --gitignore       Respect .gitignore rules (requires git)
    --format=FORMAT   Output format: plain (default), markdown, xml
    --sort=ORDER      Sort order: alpha (default), mtime, size
    --dry-run         Show stats without creating output file
    --stdout          Output to stdout instead of file
    -h, --help        Show this help message

Examples:
    concat_files.py py                              # All Python files
    concat_files.py py js --dir=./src               # Python and JS in src/
    concat_files.py py --exclude=test --lines=50    # Skip test dirs, limit per file
    concat_files.py py --dry-run                    # Show what would be concatenated
    concat_files.py py --format=markdown            # Output with code fences
    concat_files.py py --gitignore                  # Respect .gitignore
    concat_files.py py --sort=mtime                 # Most recently modified first
"""

from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Literal, TextIO

# Detect platform
IS_WINDOWS = platform.system() == "Windows"

# Default exclusions (common non-source directories)
DEFAULT_EXCLUDES = frozenset({
    "node_modules",
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    ".tox",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".egg-info",
    ".next",
    ".nuxt",
    "coverage",
    ".coverage",
    "htmlcov",
    "target",
    "vendor",
    # Windows-specific
    "Debug",
    "Release",
    "x64",
    "x86",
    ".vs",
    "packages",
})

# Extension to language mapping for markdown code fences
EXT_TO_LANG: dict[str, str] = {
    "py": "python",
    "pyi": "python",
    "pyx": "cython",
    "pxd": "cython",
    "js": "javascript",
    "mjs": "javascript",
    "cjs": "javascript",
    "ts": "typescript",
    "mts": "typescript",
    "cts": "typescript",
    "jsx": "jsx",
    "tsx": "tsx",
    "rb": "ruby",
    "rs": "rust",
    "go": "go",
    "java": "java",
    "c": "c",
    "cpp": "cpp",
    "cc": "cpp",
    "cxx": "cpp",
    "h": "c",
    "hpp": "cpp",
    "hxx": "cpp",
    "cs": "csharp",
    "php": "php",
    "swift": "swift",
    "kt": "kotlin",
    "kts": "kotlin",
    "scala": "scala",
    "sh": "bash",
    "bash": "bash",
    "zsh": "zsh",
    "fish": "fish",
    "ps1": "powershell",
    "psm1": "powershell",
    "psd1": "powershell",
    "bat": "batch",
    "cmd": "batch",
    "sql": "sql",
    "html": "html",
    "htm": "html",
    "css": "css",
    "scss": "scss",
    "sass": "sass",
    "less": "less",
    "json": "json",
    "jsonc": "jsonc",
    "json5": "json5",
    "yaml": "yaml",
    "yml": "yaml",
    "toml": "toml",
    "xml": "xml",
    "xsl": "xml",
    "xslt": "xml",
    "md": "markdown",
    "markdown": "markdown",
    "rst": "rst",
    "lua": "lua",
    "r": "r",
    "R": "r",
    "pl": "perl",
    "pm": "perl",
    "ex": "elixir",
    "exs": "elixir",
    "erl": "erlang",
    "hrl": "erlang",
    "clj": "clojure",
    "cljs": "clojure",
    "cljc": "clojure",
    "hs": "haskell",
    "lhs": "haskell",
    "ml": "ocaml",
    "mli": "ocaml",
    "fs": "fsharp",
    "fsi": "fsharp",
    "fsx": "fsharp",
    "vim": "vim",
    "el": "elisp",
    "lisp": "lisp",
    "cl": "lisp",
    "scm": "scheme",
    "rkt": "racket",
    "zig": "zig",
    "nim": "nim",
    "v": "v",
    "d": "d",
    "ada": "ada",
    "adb": "ada",
    "ads": "ada",
    "f": "fortran",
    "f90": "fortran",
    "f95": "fortran",
    "f03": "fortran",
    "cob": "cobol",
    "cbl": "cobol",
    "asm": "asm",
    "s": "asm",
    "dockerfile": "dockerfile",
    "makefile": "makefile",
    "mk": "makefile",
    "cmake": "cmake",
    "gradle": "gradle",
    "groovy": "groovy",
    "tf": "terraform",
    "tfvars": "terraform",
    "proto": "protobuf",
    "graphql": "graphql",
    "gql": "graphql",
    "vue": "vue",
    "svelte": "svelte",
    "astro": "astro",
    "prisma": "prisma",
    "sol": "solidity",
    "cairo": "cairo",
    "move": "move",
    "wgsl": "wgsl",
    "glsl": "glsl",
    "hlsl": "hlsl",
}

OutputFormat = Literal["plain", "markdown", "xml"]
SortOrder = Literal["alpha", "mtime", "size"]


@dataclass
class FileInfo:
    """Information about a file to be concatenated."""

    path: Path
    lines: int
    chars: int
    mtime: float
    size: int


@dataclass
class ConcatConfig:
    """Configuration for file concatenation."""

    extensions: list[str]
    search_dir: Path = field(default_factory=lambda: Path("."))
    max_lines_per_file: int = 0  # 0 = unlimited
    max_total_lines: int = 0  # 0 = unlimited
    excludes: list[str] = field(default_factory=list)
    use_gitignore: bool = False
    output_format: OutputFormat = "plain"
    sort_order: SortOrder = "alpha"
    dry_run: bool = False
    use_stdout: bool = False


@dataclass
class DryRunStats:
    """Statistics from a dry run."""

    file_count: int
    binary_skipped: int
    total_lines: int
    total_chars: int
    estimated_tokens: int
    files: list[tuple[str, int, int]]  # (path, original_lines, included_lines)


def is_binary(path: Path) -> bool:
    """Check if a file is binary by looking for null bytes in first 8KB."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(8192)
            return b"\x00" in chunk
    except (OSError, IOError):
        return True  # Treat unreadable files as binary


def get_lang_for_file(path: Path) -> str:
    """Get the language identifier for a file based on its extension."""
    ext = path.suffix.lstrip(".").lower()

    # Handle special filenames
    name_lower = path.name.lower()
    if name_lower == "dockerfile":
        return "dockerfile"
    if name_lower in ("makefile", "gnumakefile"):
        return "makefile"

    return EXT_TO_LANG.get(ext, ext)


def estimate_tokens(chars: int) -> int:
    """Estimate token count (rough: ~4 chars per token)."""
    return (chars + 3) // 4


def xml_escape(text: str) -> str:
    """Escape special XML characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def normalize_path_display(path: Path) -> str:
    """Normalize path for display (use forward slashes on all platforms)."""
    # Convert to posix-style path for consistent display
    return str(PurePosixPath(path))


def should_exclude(path: Path, excludes: frozenset[str]) -> bool:
    """Check if a path should be excluded based on patterns."""
    parts = path.parts
    for exclude in excludes:
        # Check if any part of the path matches the exclude pattern
        # Case-insensitive on Windows
        if IS_WINDOWS:
            exclude_lower = exclude.lower()
            if any(part.lower() == exclude_lower for part in parts):
                return True
            # Check glob patterns
            if exclude.startswith("*"):
                suffix = exclude[1:].lower()
                if any(part.lower().endswith(suffix) for part in parts):
                    return True
        else:
            if exclude in parts:
                return True
            # Check glob patterns
            if exclude.startswith("*"):
                suffix = exclude[1:]
                if any(part.endswith(suffix) for part in parts):
                    return True
    return False


def find_files_with_find(
    search_dir: Path, extensions: list[str], excludes: frozenset[str]
) -> list[Path]:
    """Find files using pathlib (works on all platforms)."""
    files: list[Path] = []

    for ext in extensions:
        pattern = f"**/*.{ext}"
        try:
            for path in search_dir.glob(pattern):
                if path.is_file() and not should_exclude(path, excludes):
                    files.append(path)
        except (OSError, PermissionError):
            # Skip directories we can't access
            continue

    return files


def find_files_with_git(
    search_dir: Path, extensions: list[str], user_excludes: list[str]
) -> list[Path]:
    """Find files using git ls-files (respects .gitignore)."""
    files: list[Path] = []
    patterns = [f"*.{ext}" for ext in extensions]

    # Determine git executable (might be 'git.exe' on Windows)
    git_cmd = "git"

    try:
        # Use CREATE_NO_WINDOW on Windows to avoid console popup
        kwargs: dict = {
            "cwd": search_dir,
            "capture_output": True,
            "text": True,
            "check": True,
        }
        if IS_WINDOWS:
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore

        # Get tracked files
        tracked = subprocess.run(
            [git_cmd, "ls-files", "-z", "--", *patterns],
            **kwargs,
        )

        # Get untracked but not ignored files
        untracked = subprocess.run(
            [git_cmd, "ls-files", "-z", "--others", "--exclude-standard", "--", *patterns],
            **kwargs,
        )

        # Combine and deduplicate
        all_files = set()
        for output in [tracked.stdout, untracked.stdout]:
            for filename in output.split("\0"):
                if filename:
                    all_files.add(filename)

        # Convert to paths and apply user excludes
        user_exclude_set = set(user_excludes)
        for filename in all_files:
            path = search_dir / filename
            try:
                if path.is_file():
                    # Apply user excludes
                    excluded = False
                    for exclude in user_exclude_set:
                        if exclude in str(path):
                            excluded = True
                            break
                    if not excluded:
                        files.append(path)
            except (OSError, PermissionError):
                continue

    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        # Fallback to regular find if git fails
        return find_files_with_find(
            search_dir, extensions, DEFAULT_EXCLUDES | set(user_excludes)
        )

    return files


def count_lines(content: str) -> int:
    """Count lines in content, handling both Unix and Windows line endings."""
    if not content:
        return 0
    # Normalize line endings and count
    # This handles \n, \r\n, and \r
    lines = content.replace("\r\n", "\n").replace("\r", "\n")
    count = lines.count("\n")
    # Add 1 if content doesn't end with newline (partial last line)
    if lines and not lines.endswith("\n"):
        count += 1
    return count


def get_file_info(path: Path) -> FileInfo | None:
    """Get information about a file. Returns None if file is binary or unreadable."""
    if is_binary(path):
        return None

    try:
        stat = path.stat()
        with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
            content = f.read()

        lines = count_lines(content)

        return FileInfo(
            path=path,
            lines=lines,
            chars=len(content),
            mtime=stat.st_mtime,
            size=stat.st_size,
        )
    except (OSError, IOError, PermissionError):
        return None


def sort_files(files: list[FileInfo], order: SortOrder) -> list[FileInfo]:
    """Sort files according to the specified order."""
    if order == "alpha":
        return sorted(files, key=lambda f: str(f.path).lower() if IS_WINDOWS else str(f.path))
    elif order == "mtime":
        return sorted(files, key=lambda f: f.mtime, reverse=True)
    elif order == "size":
        return sorted(files, key=lambda f: f.size, reverse=True)
    return files


def compute_dry_run_stats(config: ConcatConfig, files: list[FileInfo]) -> DryRunStats:
    """Compute statistics for a dry run."""
    total_lines = 0
    total_chars = 0
    file_details: list[tuple[str, int, int]] = []
    binary_skipped = 0

    for info in files:
        included_lines = info.lines

        # Apply per-file limit
        if config.max_lines_per_file > 0 and included_lines > config.max_lines_per_file:
            # Estimate chars for limited lines
            avg_chars = info.chars / (info.lines + 1) if info.lines > 0 else 0
            included_lines = config.max_lines_per_file
            file_chars = int(avg_chars * included_lines)
        else:
            file_chars = info.chars

        # Check total limit
        if config.max_total_lines > 0:
            remaining = config.max_total_lines - total_lines
            if remaining <= 0:
                break
            if included_lines > remaining:
                included_lines = remaining

        total_lines += included_lines
        total_chars += file_chars
        file_details.append((normalize_path_display(info.path), info.lines, included_lines))

    # Add header overhead estimate
    overhead_per_file = {"plain": 200, "markdown": 150, "xml": 250}
    base_overhead = {"plain": 500, "markdown": 300, "xml": 400}
    total_chars += len(files) * overhead_per_file.get(config.output_format, 200)
    total_chars += base_overhead.get(config.output_format, 500)

    return DryRunStats(
        file_count=len(files),
        binary_skipped=binary_skipped,
        total_lines=total_lines,
        total_chars=total_chars,
        estimated_tokens=estimate_tokens(total_chars),
        files=file_details,
    )


def print_dry_run_stats(config: ConcatConfig, stats: DryRunStats) -> None:
    """Print dry run statistics to stderr."""
    print(f"\n=== Dry Run Results ===\n", file=sys.stderr)
    print(f"Files found:      {stats.file_count}", file=sys.stderr)
    if stats.binary_skipped > 0:
        print(f"Binary (skipped): {stats.binary_skipped}", file=sys.stderr)
    print(f"Extensions:       {' '.join(config.extensions)}", file=sys.stderr)
    print(f"Search dir:       {normalize_path_display(config.search_dir)}", file=sys.stderr)
    print(f"Sort order:       {config.sort_order}", file=sys.stderr)
    print(f"Output format:    {config.output_format}", file=sys.stderr)
    if config.use_gitignore:
        print("Using .gitignore: yes", file=sys.stderr)
    print(file=sys.stderr)
    print("Estimated output:", file=sys.stderr)
    print(f"  Lines:          {stats.total_lines}", file=sys.stderr)
    print(f"  Characters:     {stats.total_chars}", file=sys.stderr)
    print(f"  Tokens (est):   ~{stats.estimated_tokens}", file=sys.stderr)
    print(file=sys.stderr)

    if config.max_lines_per_file > 0:
        print(f"Per-file limit:   {config.max_lines_per_file} lines", file=sys.stderr)
    if config.max_total_lines > 0:
        print(f"Total limit:      {config.max_total_lines} lines", file=sys.stderr)
    if config.excludes:
        print(f"User excludes:    {' '.join(config.excludes)}", file=sys.stderr)

    print(f"\nFiles to include:", file=sys.stderr)
    for path, original, included in stats.files:
        if original != included:
            print(f"  {path} ({original} lines, truncated to {included})", file=sys.stderr)
        else:
            print(f"  {path} ({original} lines)", file=sys.stderr)


class OutputWriter:
    """Handles writing concatenated output in various formats."""

    def __init__(
        self,
        output: TextIO,
        config: ConcatConfig,
        file_count: int,
    ):
        self.output = output
        self.config = config
        self.file_count = file_count

    def write(self, text: str) -> None:
        """Write a line to output."""
        self.output.write(text + "\n")

    def write_header(self) -> None:
        """Write the document header."""
        timestamp = datetime.now(timezone.utc).isoformat()
        cfg = self.config
        search_dir_display = normalize_path_display(cfg.search_dir)

        if cfg.output_format == "plain":
            self.write(f"# Concatenated files with extensions: {' '.join(cfg.extensions)}")
            self.write(f"# From directory: '{search_dir_display}'")
            self.write(f"# Created on {timestamp}")
            self.write(f"# Contains {self.file_count} files")
            self.write(f"# Sort order: {cfg.sort_order}")
            if cfg.max_lines_per_file > 0:
                self.write(f"# Limited to maximum {cfg.max_lines_per_file} lines per file")
            if cfg.max_total_lines > 0:
                self.write(f"# Limited to maximum {cfg.max_total_lines} total lines")
            if cfg.excludes:
                self.write(f"# User excludes: {' '.join(cfg.excludes)}")
            if cfg.use_gitignore:
                self.write("# Respecting .gitignore rules")
            self.write("# ==========================================================")
            self.write("")

        elif cfg.output_format == "markdown":
            self.write("# Concatenated Files")
            self.write("")
            self.write(f"- **Extensions:** {' '.join(cfg.extensions)}")
            self.write(f"- **Directory:** `{search_dir_display}`")
            self.write(f"- **Created:** {timestamp}")
            self.write(f"- **Files:** {self.file_count}")
            self.write(f"- **Sort:** {cfg.sort_order}")
            if cfg.max_lines_per_file > 0:
                self.write(f"- **Per-file limit:** {cfg.max_lines_per_file} lines")
            if cfg.max_total_lines > 0:
                self.write(f"- **Total limit:** {cfg.max_total_lines} lines")
            if cfg.excludes:
                self.write(f"- **Excludes:** {' '.join(cfg.excludes)}")
            if cfg.use_gitignore:
                self.write("- **Gitignore:** enabled")
            self.write("")
            self.write("---")
            self.write("")

        elif cfg.output_format == "xml":
            self.write('<?xml version="1.0" encoding="UTF-8"?>')
            self.write("<concatenation>")
            self.write("  <metadata>")
            self.write(f"    <extensions>{' '.join(cfg.extensions)}</extensions>")
            self.write(f"    <directory>{xml_escape(search_dir_display)}</directory>")
            self.write(f"    <created>{timestamp}</created>")
            self.write(f"    <file_count>{self.file_count}</file_count>")
            self.write(f"    <sort_order>{cfg.sort_order}</sort_order>")
            if cfg.max_lines_per_file > 0:
                self.write(f"    <max_lines_per_file>{cfg.max_lines_per_file}</max_lines_per_file>")
            if cfg.max_total_lines > 0:
                self.write(f"    <max_total_lines>{cfg.max_total_lines}</max_total_lines>")
            if cfg.excludes:
                self.write(f"    <excludes>{' '.join(cfg.excludes)}</excludes>")
            if cfg.use_gitignore:
                self.write("    <gitignore>true</gitignore>")
            self.write("  </metadata>")
            self.write("  <files>")

    def write_file_header(self, path: Path, line_count: int, showing: int) -> None:
        """Write the header for an individual file."""
        lang = get_lang_for_file(path)
        path_display = normalize_path_display(path)

        if self.config.output_format == "plain":
            self.write("")
            self.write("# ==========================================")
            self.write(f"# File: {path_display}")
            self.write(f"# Lines: {line_count}")
            if showing < line_count:
                self.write(f"# NOTE: Showing only first {showing} of {line_count} lines")
            self.write("# ==========================================")
            self.write("")

        elif self.config.output_format == "markdown":
            self.write(f"## `{path_display}`")
            self.write("")
            if showing < line_count:
                self.write(f"_Lines: {line_count} (showing first {showing})_")
            else:
                self.write(f"_Lines: {line_count}_")
            self.write("")
            self.write(f"```{lang}")

        elif self.config.output_format == "xml":
            self.write("    <file>")
            self.write(f"      <path>{xml_escape(path_display)}</path>")
            self.write(f"      <lines>{line_count}</lines>")
            if showing < line_count:
                self.write(f"      <truncated_to>{showing}</truncated_to>")
            self.write("      <content><![CDATA[")

    def write_file_content(self, content: str) -> None:
        """Write file content (already truncated if needed)."""
        # Normalize line endings to Unix style for consistent output
        normalized = content.replace("\r\n", "\n").replace("\r", "\n")
        # Write without adding extra newline (content includes its own newlines)
        self.output.write(normalized)
        if normalized and not normalized.endswith("\n"):
            self.output.write("\n")

    def write_file_footer(self, line_count: int, showing: int) -> None:
        """Write the footer for an individual file."""
        if self.config.output_format == "plain":
            if showing < line_count:
                self.write("")
                self.write(f"# ... ({line_count - showing} more lines) ...")

        elif self.config.output_format == "markdown":
            self.write("```")
            if showing < line_count:
                self.write("")
                self.write(f"_... ({line_count - showing} more lines) ..._")
            self.write("")

        elif self.config.output_format == "xml":
            self.write("]]></content>")
            self.write("    </file>")

    def write_budget_exhausted(self, budget: int) -> None:
        """Write message when line budget is exhausted."""
        if self.config.output_format == "plain":
            self.write("")
            self.write("# ==========================================")
            self.write(f"# NOTE: Total line budget ({budget}) exhausted")
            self.write("# Remaining files skipped")
            self.write("# ==========================================")

        elif self.config.output_format == "markdown":
            self.write("")
            self.write(f"> **Note:** Total line budget ({budget}) exhausted. Remaining files skipped.")
            self.write("")

        elif self.config.output_format == "xml":
            self.write(f"    <!-- Total line budget ({budget}) exhausted. Remaining files skipped. -->")

    def write_footer(self) -> None:
        """Write the document footer."""
        if self.config.output_format == "xml":
            self.write("  </files>")
            self.write("</concatenation>")


def read_file_lines(path: Path, max_lines: int = 0) -> tuple[str, int]:
    """
    Read file content, optionally limiting to max_lines.

    Returns (content, total_line_count).
    Handles both Unix and Windows line endings.
    """
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
        if max_lines <= 0:
            content = f.read()
            lines = count_lines(content)
            return content, lines

        # Read limited lines - handle different line endings
        lines_read = []
        total_lines = 0

        # Read character by character to handle all line ending styles
        buffer = []
        while True:
            char = f.read(1)
            if not char:
                # End of file
                if buffer:
                    total_lines += 1
                    if len(lines_read) < max_lines:
                        lines_read.append("".join(buffer))
                break

            if char == "\r":
                # Could be \r or \r\n
                total_lines += 1
                if len(lines_read) < max_lines:
                    lines_read.append("".join(buffer))
                buffer = []
                # Peek for \n
                next_char = f.read(1)
                if next_char and next_char != "\n":
                    # It was just \r, put back the character we read
                    buffer.append(next_char)
            elif char == "\n":
                total_lines += 1
                if len(lines_read) < max_lines:
                    lines_read.append("".join(buffer))
                buffer = []
            else:
                buffer.append(char)

        # Count remaining lines without storing them
        remaining = f.read()
        if remaining:
            total_lines += count_lines(remaining)

        # Join with Unix newlines for consistent output
        return "\n".join(lines_read) + ("\n" if lines_read else ""), total_lines


def concatenate_files(config: ConcatConfig, files: list[FileInfo], output: TextIO) -> int:
    """
    Concatenate files to output.

    Returns the number of binary files skipped.
    """
    writer = OutputWriter(output, config, len(files))
    writer.write_header()

    total_lines_written = 0
    skipped_binary = 0

    for info in files:
        # Check total budget
        if config.max_total_lines > 0 and total_lines_written >= config.max_total_lines:
            writer.write_budget_exhausted(config.max_total_lines)
            break

        # Calculate lines to include
        lines_to_include = info.lines
        if config.max_lines_per_file > 0 and lines_to_include > config.max_lines_per_file:
            lines_to_include = config.max_lines_per_file

        # Apply total limit
        if config.max_total_lines > 0:
            remaining = config.max_total_lines - total_lines_written
            if lines_to_include > remaining:
                lines_to_include = remaining

        # Read and write file
        writer.write_file_header(info.path, info.lines, lines_to_include)

        content, _ = read_file_lines(info.path, lines_to_include if lines_to_include < info.lines else 0)
        writer.write_file_content(content)

        writer.write_file_footer(info.lines, lines_to_include)

        total_lines_written += lines_to_include

    writer.write_footer()
    return skipped_binary


def generate_output_filename(config: ConcatConfig) -> str:
    """Generate the output filename based on configuration."""
    if config.search_dir == Path("."):
        dir_name = Path.cwd().name
    else:
        dir_name = config.search_dir.name

    ext_string = "_".join(config.extensions)

    file_ext = {"plain": "txt", "markdown": "md", "xml": "xml"}[config.output_format]

    if config.max_lines_per_file > 0:
        return f"{dir_name}_{ext_string}_{config.max_lines_per_file}lines.{file_ext}"
    else:
        return f"{dir_name}_{ext_string}_files.{file_ext}"


def check_git_available(search_dir: Path) -> bool:
    """Check if git is available and search_dir is in a git repo."""
    try:
        kwargs: dict = {
            "capture_output": True,
            "check": True,
        }
        if IS_WINDOWS:
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore

        subprocess.run(
            ["git", "-C", str(search_dir), "rev-parse", "--git-dir"],
            **kwargs,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return False


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Recursively find files with specific extensions and concatenate their contents.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Output Formats:
  plain     Comment-style headers (default)
  markdown  GitHub-flavored markdown with code fences
  xml       XML structure with CDATA content

Sort Orders:
  alpha     Alphabetical by path (default)
  mtime     Most recently modified first
  size      Largest files first

Cross-platform: Works on Linux, macOS, and Windows.
""",
    )

    parser.add_argument(
        "extensions",
        nargs="*",
        help="File extensions to include (without dots)",
    )
    parser.add_argument(
        "--dir",
        dest="search_dir",
        default=".",
        help="Search directory (default: current directory)",
    )
    parser.add_argument(
        "--lines",
        type=int,
        default=0,
        help="Max lines per file (default: unlimited)",
    )
    parser.add_argument(
        "--max-total",
        type=int,
        default=0,
        help="Stop after N total lines (default: unlimited)",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Exclude pattern (repeatable)",
    )
    parser.add_argument(
        "--gitignore",
        action="store_true",
        help="Respect .gitignore rules (requires git)",
    )
    parser.add_argument(
        "--format",
        choices=["plain", "markdown", "xml"],
        default="plain",
        help="Output format (default: plain)",
    )
    parser.add_argument(
        "--sort",
        choices=["alpha", "mtime", "size"],
        default="alpha",
        help="Sort order (default: alpha)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show stats without creating output file",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Output to stdout instead of file",
    )

    args = parser.parse_args()

    if not args.extensions:
        parser.print_help()
        return 1

    # Build configuration
    config = ConcatConfig(
        extensions=args.extensions,
        search_dir=Path(args.search_dir),
        max_lines_per_file=args.lines,
        max_total_lines=args.max_total,
        excludes=args.exclude,
        use_gitignore=args.gitignore,
        output_format=args.format,
        sort_order=args.sort,
        dry_run=args.dry_run,
        use_stdout=args.stdout,
    )

    # Validate search directory
    if not config.search_dir.is_dir():
        print(f"Error: Directory '{config.search_dir}' not found", file=sys.stderr)
        return 1

    # Check gitignore requirements
    if config.use_gitignore:
        if not check_git_available(config.search_dir):
            print(
                f"Warning: --gitignore specified but '{config.search_dir}' is not in a git repository",
                file=sys.stderr,
            )
            print("Continuing without gitignore filtering...", file=sys.stderr)
            config.use_gitignore = False

    # Find files
    all_excludes = DEFAULT_EXCLUDES | set(config.excludes)

    if config.use_gitignore:
        file_paths = find_files_with_git(config.search_dir, config.extensions, config.excludes)
    else:
        file_paths = find_files_with_find(config.search_dir, config.extensions, all_excludes)

    if not file_paths:
        print(
            f"No files with extensions ({' '.join(config.extensions)}) found in '{config.search_dir}'",
            file=sys.stderr,
        )
        return 0

    # Get file info (filtering out binary files)
    files: list[FileInfo] = []
    binary_count = 0
    for path in file_paths:
        info = get_file_info(path)
        if info is not None:
            files.append(info)
        else:
            binary_count += 1

    # Sort files
    files = sort_files(files, config.sort_order)

    print(f"Found {len(files)} files with extensions ({' '.join(config.extensions)})", file=sys.stderr)
    if binary_count > 0:
        print(f"Skipped {binary_count} binary file(s)", file=sys.stderr)
    print(f"Format: {config.output_format}, Sort: {config.sort_order}", file=sys.stderr)
    if config.use_gitignore:
        print("Using .gitignore rules", file=sys.stderr)

    # Dry run mode
    if config.dry_run:
        stats = compute_dry_run_stats(config, files)
        stats = DryRunStats(
            file_count=len(files),
            binary_skipped=binary_count,
            total_lines=stats.total_lines,
            total_chars=stats.total_chars,
            estimated_tokens=stats.estimated_tokens,
            files=stats.files,
        )
        print_dry_run_stats(config, stats)
        return 0

    # Determine output
    if config.use_stdout:
        output_file = sys.stdout
        output_path = None
    else:
        output_path = generate_output_filename(config)
        print(f"Writing to: {output_path}", file=sys.stderr)
        output_file = open(output_path, "w", encoding="utf-8", newline="\n")

    try:
        skipped = concatenate_files(config, files, output_file)

        if not config.use_stdout:
            output_file.close()

            # Print final stats
            stat = Path(output_path).stat()
            total_chars = stat.st_size
            with open(output_path, "r", encoding="utf-8") as f:
                total_lines = sum(1 for _ in f)

            print(file=sys.stderr)
            print(f"Concatenation complete: {output_path}", file=sys.stderr)
            print(f"  Lines:        {total_lines}", file=sys.stderr)
            print(f"  Size:         {total_chars} chars", file=sys.stderr)
            print(f"  Tokens (est): ~{estimate_tokens(total_chars)}", file=sys.stderr)
        else:
            print(file=sys.stderr)
            print("Output complete", file=sys.stderr)

    finally:
        if not config.use_stdout and not output_file.closed:
            output_file.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
