"""Concat files skill for finding and concatenating source files.

Recursively finds files by extension and concatenates them into a single output
with token estimation. Useful for preparing code context for LLMs.

Supports:
- Multiple file extensions
- Exclusion patterns (default + custom)
- Line limits (per-file and total)
- Multiple output formats (plain, markdown, xml)
- Sorting by name, modification time, or size
- .gitignore integration when git is available
- Dry run mode for preview with token estimation
"""

import asyncio
import fnmatch
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from nexus3.core.errors import PathSecurityError
from nexus3.core.paths import validate_path
from nexus3.core.process import WINDOWS_CREATIONFLAGS
from nexus3.core.types import ToolResult
from nexus3.skill.base import FileSkill, file_skill_factory

if TYPE_CHECKING:
    from nexus3.skill.services import ServiceContainer


# =============================================================================
# Constants
# =============================================================================

# Default exclusions (common non-source directories)
DEFAULT_EXCLUDES: frozenset[str] = frozenset({
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
    # Python
    "py": "python",
    "pyi": "python",
    "pyx": "cython",
    "pxd": "cython",
    # JavaScript/TypeScript
    "js": "javascript",
    "mjs": "javascript",
    "cjs": "javascript",
    "ts": "typescript",
    "mts": "typescript",
    "cts": "typescript",
    "jsx": "jsx",
    "tsx": "tsx",
    # Systems languages
    "rs": "rust",
    "go": "go",
    "c": "c",
    "cpp": "cpp",
    "cc": "cpp",
    "cxx": "cpp",
    "h": "c",
    "hpp": "cpp",
    "hxx": "cpp",
    # JVM languages
    "java": "java",
    "kt": "kotlin",
    "kts": "kotlin",
    "scala": "scala",
    "groovy": "groovy",
    # .NET languages
    "cs": "csharp",
    "fs": "fsharp",
    "fsi": "fsharp",
    "fsx": "fsharp",
    # Other compiled languages
    "swift": "swift",
    "rb": "ruby",
    "php": "php",
    # Shell
    "sh": "bash",
    "bash": "bash",
    "zsh": "zsh",
    "fish": "fish",
    "ps1": "powershell",
    "psm1": "powershell",
    "psd1": "powershell",
    "bat": "batch",
    "cmd": "batch",
    # Data/config
    "sql": "sql",
    "json": "json",
    "jsonc": "jsonc",
    "json5": "json5",
    "yaml": "yaml",
    "yml": "yaml",
    "toml": "toml",
    "xml": "xml",
    "xsl": "xml",
    "xslt": "xml",
    # Markup
    "html": "html",
    "htm": "html",
    "css": "css",
    "scss": "scss",
    "sass": "sass",
    "less": "less",
    "md": "markdown",
    "markdown": "markdown",
    "rst": "rst",
    "txt": "text",
    # Scripting languages
    "lua": "lua",
    "r": "r",
    "R": "r",
    "pl": "perl",
    "pm": "perl",
    # Functional languages
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
    # Lisp family
    "el": "elisp",
    "lisp": "lisp",
    "cl": "lisp",
    "scm": "scheme",
    "rkt": "racket",
    # Editor/config
    "vim": "vim",
    # Build systems
    "dockerfile": "dockerfile",
    "makefile": "makefile",
    "mk": "makefile",
    "cmake": "cmake",
    "gradle": "gradle",
    # Infrastructure
    "tf": "terraform",
    "tfvars": "terraform",
    "hcl": "hcl",
    "proto": "protobuf",
    "graphql": "graphql",
    "gql": "graphql",
    # Frontend frameworks
    "vue": "vue",
    "svelte": "svelte",
    "astro": "astro",
    # Other
    "prisma": "prisma",
    "sol": "solidity",
    "cairo": "cairo",
    "move": "move",
    "wgsl": "wgsl",
    "glsl": "glsl",
    "hlsl": "hlsl",
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
}

# Detect platform for case-insensitive path matching
IS_WINDOWS = sys.platform == "win32"


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class FileInfo:
    """Information about a file to be concatenated."""

    path: Path
    lines: int
    chars: int
    mtime: float
    size: int


@dataclass
class DryRunResult:
    """Statistics from a dry run."""

    file_count: int
    binary_skipped: int
    total_lines: int
    total_chars: int
    estimated_tokens: int
    # (path, original_lines, included_lines)
    files: list[tuple[str, int, int]] = field(default_factory=list)
    output_path: str = ""  # Generated output filename


# =============================================================================
# Skill Implementation
# =============================================================================

class ConcatFilesSkill(FileSkill):
    """Skill that finds files by extension and concatenates them.

    Useful for preparing code context for LLMs. Supports multiple output
    formats, line limits, and dry run mode with token estimation.

    Inherits path validation from FileSkill.
    """

    def __init__(self, services: "ServiceContainer") -> None:
        """Initialize ConcatFilesSkill with ServiceContainer.

        Args:
            services: ServiceContainer for accessing permissions and resolving
                per-tool allowed_paths at validation time.
        """
        super().__init__(services)

    @property
    def name(self) -> str:
        return "concat_files"

    @property
    def description(self) -> str:
        return (
            "Find files by extension and concatenate them into a single output. "
            "Supports line limits, multiple formats (plain/markdown/xml), and "
            "dry run mode with token estimation. Use dry_run=true first to preview."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "extensions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "File extensions to include (without dots). "
                        "Example: ['py', 'ts'] for Python and TypeScript files."
                    ),
                },
                "path": {
                    "type": "string",
                    "description": "Directory to search (default: current directory)",
                    "default": ".",
                },
                "exclude": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Additional patterns to exclude. Supports glob patterns. "
                        "Common directories like node_modules, .git are excluded by default."
                    ),
                },
                "lines": {
                    "type": "integer",
                    "description": "Maximum lines per file (0 = unlimited)",
                    "default": 0,
                },
                "max_total": {
                    "type": "integer",
                    "description": "Maximum total lines across all files (0 = unlimited)",
                    "default": 0,
                },
                "format": {
                    "type": "string",
                    "enum": ["plain", "markdown", "xml"],
                    "description": "Output format: plain (comments), markdown (code fences), xml",
                    "default": "plain",
                },
                "sort": {
                    "type": "string",
                    "enum": ["alpha", "mtime", "size"],
                    "description": (
                        "Sort order: alpha (alphabetical), mtime (most recent first), "
                        "size (largest first)"
                    ),
                    "default": "alpha",
                },
                "gitignore": {
                    "type": "boolean",
                    "description": "Use .gitignore rules for filtering (requires git)",
                    "default": True,
                },
                "dry_run": {
                    "type": "boolean",
                    "description": (
                        "Return file list and token estimate without creating output. "
                        "Recommended to run this first to check output size."
                    ),
                    "default": True,
                },
            },
            "required": ["extensions"],
        }

    def _is_binary(self, path: Path) -> bool:
        """Check if file is binary by looking for null bytes in first 8KB.

        Args:
            path: Path to the file to check.

        Returns:
            True if file appears to be binary or cannot be read.
        """
        try:
            with open(path, "rb") as f:
                chunk = f.read(8192)
                return b"\x00" in chunk
        except OSError:
            return True  # Treat unreadable files as binary

    def _should_exclude(self, path: Path, exclude: list[str] | None) -> bool:
        """Check if a path should be excluded based on patterns.

        Args:
            path: Path to check.
            exclude: Additional user-provided exclusion patterns.

        Returns:
            True if the path should be excluded.
        """
        parts = path.parts

        # Check against DEFAULT_EXCLUDES
        for excl in DEFAULT_EXCLUDES:
            if IS_WINDOWS:
                excl_lower = excl.lower()
                if any(part.lower() == excl_lower for part in parts):
                    return True
                # Handle glob-style patterns like "*.egg-info"
                if excl.startswith("*"):
                    suffix = excl[1:].lower()
                    if any(part.lower().endswith(suffix) for part in parts):
                        return True
            else:
                if excl in parts:
                    return True
                if excl.startswith("*"):
                    suffix = excl[1:]
                    if any(part.endswith(suffix) for part in parts):
                        return True

        # Check against user-provided exclusions
        if exclude:
            path_str = str(path)
            for excl in exclude:
                # Support fnmatch glob patterns
                if IS_WINDOWS:
                    if fnmatch.fnmatch(path_str.lower(), excl.lower()):
                        return True
                    # Also check if any path component matches
                    if any(fnmatch.fnmatch(part.lower(), excl.lower()) for part in parts):
                        return True
                else:
                    if fnmatch.fnmatch(path_str, excl):
                        return True
                    if any(fnmatch.fnmatch(part, excl) for part in parts):
                        return True

        return False

    # =========================================================================
    # Phase 4: Git Integration
    # =========================================================================

    async def _git_available(self, path: Path) -> bool:
        """Check if git is available and path is in a git repository.

        Args:
            path: Path to check (should be a directory).

        Returns:
            True if git is available and path is inside a git worktree.
        """
        try:
            # Check if inside a git worktree
            # Use separate code paths for Windows vs Unix for proper flag handling
            if IS_WINDOWS:
                proc = await asyncio.create_subprocess_exec(
                    "git", "rev-parse", "--is-inside-work-tree",
                    cwd=path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    creationflags=WINDOWS_CREATIONFLAGS,
                )
            else:
                proc = await asyncio.create_subprocess_exec(
                    "git", "rev-parse", "--is-inside-work-tree",
                    cwd=path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    start_new_session=True,
                )

            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)

            if proc.returncode == 0 and stdout.strip() == b"true":
                return True
            return False

        except (OSError, FileNotFoundError):
            # git not installed
            return False
        except TimeoutError:
            # git command timed out
            return False

    async def _find_files_git(
        self,
        base_path: Path,
        extensions: list[str],
        exclude: list[str] | None,
    ) -> list[Path]:
        """Find files using git to respect .gitignore rules.

        Falls back to glob-based search if git fails.

        Args:
            base_path: Directory to search in.
            extensions: File extensions to match (without dots).
            exclude: Additional patterns to exclude.

        Returns:
            List of matching file paths.
        """
        try:
            # Build glob patterns for git ls-files
            patterns = [f"*.{ext}" for ext in extensions]

            # Get tracked files
            # Use separate code paths for Windows vs Unix for proper flag handling
            if IS_WINDOWS:
                proc_tracked = await asyncio.create_subprocess_exec(
                    "git", "ls-files", "-z", "--", *patterns,
                    cwd=base_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    creationflags=WINDOWS_CREATIONFLAGS,
                )
            else:
                proc_tracked = await asyncio.create_subprocess_exec(
                    "git", "ls-files", "-z", "--", *patterns,
                    cwd=base_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    start_new_session=True,
                )
            stdout_tracked, _ = await asyncio.wait_for(
                proc_tracked.communicate(), timeout=30.0
            )

            # Get untracked but not ignored files
            if IS_WINDOWS:
                proc_untracked = await asyncio.create_subprocess_exec(
                    "git", "ls-files", "-z", "--others", "--exclude-standard", "--", *patterns,
                    cwd=base_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    creationflags=WINDOWS_CREATIONFLAGS,
                )
            else:
                proc_untracked = await asyncio.create_subprocess_exec(
                    "git", "ls-files", "-z", "--others", "--exclude-standard", "--", *patterns,
                    cwd=base_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    start_new_session=True,
                )
            stdout_untracked, _ = await asyncio.wait_for(
                proc_untracked.communicate(), timeout=30.0
            )

            # Check for errors
            if proc_tracked.returncode != 0 or proc_untracked.returncode != 0:
                # Fall back to glob
                return await self._find_files_glob(base_path, extensions, exclude)

            # Combine and deduplicate
            all_files: set[str] = set()
            for output in [stdout_tracked, stdout_untracked]:
                # Null-separated output handles filenames with spaces
                decoded = output.decode("utf-8", errors="replace")
                for filename in decoded.split("\0"):
                    if filename:
                        all_files.add(filename)

            # Convert to paths and filter
            def process_files() -> list[Path]:
                results: list[Path] = []
                for filename in all_files:
                    path = base_path / filename

                    try:
                        if not path.is_file():
                            continue

                        # Check exclusions (default + user)
                        if self._should_exclude(path, exclude):
                            continue

                        # Validate against sandbox if active
                        if self._allowed_paths is not None:
                            try:
                                validate_path(path, allowed_paths=self._allowed_paths)
                            except PathSecurityError:
                                continue  # Skip files outside sandbox

                        results.append(path)
                    except (OSError, PermissionError):
                        continue

                return results

            return await asyncio.to_thread(process_files)

        except (OSError, TimeoutError):
            # Fall back to glob on any git failure
            return await self._find_files_glob(base_path, extensions, exclude)

    # =========================================================================
    # Phase 1: File Discovery (Glob-based)
    # =========================================================================

    async def _find_files_glob(
        self,
        base_path: Path,
        extensions: list[str],
        exclude: list[str] | None,
    ) -> list[Path]:
        """Find files matching extensions using glob.

        Args:
            base_path: Directory to search in.
            extensions: File extensions to match (without dots).
            exclude: Additional patterns to exclude.

        Returns:
            List of matching file paths.
        """
        def do_find() -> list[Path]:
            results: list[Path] = []

            for ext in extensions:
                pattern = f"**/*.{ext}"
                try:
                    for path in base_path.glob(pattern):
                        if not path.is_file():
                            continue

                        # Check exclusions
                        if self._should_exclude(path, exclude):
                            continue

                        # Validate against sandbox if active
                        if self._allowed_paths is not None:
                            try:
                                validate_path(path, allowed_paths=self._allowed_paths)
                            except PathSecurityError:
                                continue  # Skip files outside sandbox

                        results.append(path)
                except (OSError, PermissionError):
                    # Skip directories we can't access
                    continue

            return results

        return await asyncio.to_thread(do_find)

    # =========================================================================
    # Phase 2: File Info Collection, Sorting, Dry Run
    # =========================================================================

    async def _collect_file_info(self, files: list[Path]) -> tuple[list[FileInfo], int]:
        """Collect file information, filtering out binary files.

        Args:
            files: List of file paths to process.

        Returns:
            Tuple of (list of FileInfo for non-binary files, count of binary files skipped).
        """
        def do_collect() -> tuple[list[FileInfo], int]:
            results: list[FileInfo] = []
            binary_count = 0

            for path in files:
                # Check if binary
                if self._is_binary(path):
                    binary_count += 1
                    continue

                try:
                    stat = path.stat()
                    with open(path, encoding="utf-8", errors="replace", newline="") as f:
                        content = f.read()

                    # Count lines - handle all line ending styles
                    lines = self._count_lines(content)

                    results.append(FileInfo(
                        path=path,
                        lines=lines,
                        chars=len(content),
                        mtime=stat.st_mtime,
                        size=stat.st_size,
                    ))
                except (OSError, PermissionError):
                    # Treat unreadable files as binary/skipped
                    binary_count += 1
                    continue

            return results, binary_count

        return await asyncio.to_thread(do_collect)

    def _count_lines(self, content: str) -> int:
        """Count lines in content, handling Unix, Windows, and old Mac line endings.

        Args:
            content: File content string.

        Returns:
            Number of lines in the content.
        """
        if not content:
            return 0
        # Normalize line endings and count
        lines = content.replace("\r\n", "\n").replace("\r", "\n")
        count = lines.count("\n")
        # Add 1 if content doesn't end with newline (partial last line)
        if lines and not lines.endswith("\n"):
            count += 1
        return count

    def _sort_files(self, files: list[FileInfo], sort_by: str) -> list[FileInfo]:
        """Sort files by the specified criteria.

        Args:
            files: List of FileInfo objects to sort.
            sort_by: Sort order - "alpha", "mtime", or "size".

        Returns:
            Sorted list of FileInfo objects.
        """
        if sort_by == "alpha":
            # Case-insensitive on Windows for consistent behavior
            if IS_WINDOWS:
                return sorted(files, key=lambda f: str(f.path).lower())
            return sorted(files, key=lambda f: str(f.path))
        elif sort_by == "mtime":
            # Most recently modified first
            return sorted(files, key=lambda f: f.mtime, reverse=True)
        elif sort_by == "size":
            # Largest first
            return sorted(files, key=lambda f: f.size, reverse=True)
        # Default to unsorted
        return files

    def _compute_dry_run(
        self,
        files: list[FileInfo],
        binary_skipped: int,
        lines_limit: int,
        max_total: int,
        output_format: str,
        output_path: str,
    ) -> DryRunResult:
        """Compute dry run statistics with token estimation.

        Args:
            files: List of FileInfo objects.
            binary_skipped: Number of binary files that were skipped.
            lines_limit: Maximum lines per file (0 = unlimited).
            max_total: Maximum total lines across all files (0 = unlimited).
            output_format: Output format (plain/markdown/xml).
            output_path: Generated output file path.

        Returns:
            DryRunResult with file-by-file breakdown and token estimation.
        """
        total_lines = 0
        total_chars = 0
        file_details: list[tuple[str, int, int]] = []

        for info in files:
            included_lines = info.lines

            # Apply per-file limit
            if lines_limit > 0 and included_lines > lines_limit:
                # Estimate chars for limited lines
                avg_chars = info.chars / (info.lines + 1) if info.lines > 0 else 0
                included_lines = lines_limit
                file_chars = int(avg_chars * included_lines)
            else:
                file_chars = info.chars

            # Check total limit
            if max_total > 0:
                remaining = max_total - total_lines
                if remaining <= 0:
                    break
                if included_lines > remaining:
                    included_lines = remaining
                    # Adjust chars estimate for partial inclusion
                    avg_chars = info.chars / (info.lines + 1) if info.lines > 0 else 0
                    file_chars = int(avg_chars * included_lines)

            total_lines += included_lines
            total_chars += file_chars
            # Normalize path display (forward slashes on all platforms)
            path_display = str(info.path).replace("\\", "/")
            file_details.append((path_display, info.lines, included_lines))

        # Add format-specific overhead estimates
        overhead_per_file = {"plain": 200, "markdown": 150, "xml": 250}
        base_overhead = {"plain": 500, "markdown": 300, "xml": 400}
        total_chars += len(file_details) * overhead_per_file.get(output_format, 200)
        total_chars += base_overhead.get(output_format, 500)

        # Estimate tokens: roughly 4 chars per token
        estimated_tokens = (total_chars + 3) // 4

        return DryRunResult(
            file_count=len(file_details),
            binary_skipped=binary_skipped,
            total_lines=total_lines,
            total_chars=total_chars,
            estimated_tokens=estimated_tokens,
            files=file_details,
            output_path=output_path,
        )

    def _generate_output_path(
        self,
        base_path: Path,
        extensions: list[str],
        output_format: str,
    ) -> Path:
        """Generate a descriptive output filename.

        Args:
            base_path: Base directory being searched.
            extensions: List of file extensions being concatenated.
            output_format: Output format (plain/markdown/xml).

        Returns:
            Path to the output file (with numeric suffix if file exists).
        """
        # Get directory name
        if base_path == Path("."):
            try:
                dir_name = Path.cwd().name
            except OSError:
                dir_name = "output"
        else:
            dir_name = base_path.name or "output"

        # Sanitize directory name: replace spaces with dashes, remove special chars
        dir_name = re.sub(r"[^\w\-]", "", dir_name.replace(" ", "-").replace("_", "-"))
        if not dir_name:
            dir_name = "output"

        # Build extension string
        ext_str = "-".join(extensions[:3])  # Limit to first 3 extensions for readability
        if len(extensions) > 3:
            ext_str += f"-etc{len(extensions) - 3}"

        # File extension based on format
        file_ext = {"plain": "txt", "markdown": "md", "xml": "xml"}.get(output_format, "txt")

        # Build base filename
        base_name = f"{dir_name}-{ext_str}-concat"

        # Find unique filename
        output_path = base_path / f"{base_name}.{file_ext}"
        if not output_path.exists():
            return output_path

        # Add numeric suffix if file exists
        counter = 1
        while True:
            output_path = base_path / f"{base_name}-{counter}.{file_ext}"
            if not output_path.exists():
                return output_path
            counter += 1
            if counter > 1000:  # Safety limit
                # Fall back to timestamp
                import time
                ts = int(time.time())
                return base_path / f"{base_name}-{ts}.{file_ext}"

    def _format_dry_run_output(
        self,
        result: DryRunResult,
        extensions: list[str],
        base_path: Path,
        sort_by: str,
    ) -> str:
        """Format dry run results as a readable string.

        Args:
            result: DryRunResult with statistics.
            extensions: List of extensions searched.
            base_path: Base directory searched.
            sort_by: Sort order used.

        Returns:
            Formatted string for display.
        """
        lines = []
        lines.append("=== Dry Run Results ===")
        lines.append("")
        lines.append(f"Files found:      {result.file_count}")
        if result.binary_skipped > 0:
            lines.append(f"Binary (skipped): {result.binary_skipped}")
        lines.append(f"Extensions:       {' '.join(extensions)}")
        lines.append(f"Search dir:       {str(base_path).replace(chr(92), '/')}")
        lines.append(f"Sort order:       {sort_by}")
        lines.append("")
        lines.append("Estimated output:")
        lines.append(f"  Lines:          {result.total_lines}")
        lines.append(f"  Characters:     {result.total_chars}")
        lines.append(f"  Tokens (est):   ~{result.estimated_tokens}")
        lines.append("")
        lines.append(f"Output file:      {result.output_path}")
        lines.append("")
        lines.append("Files to include:")
        for path, original, included in result.files:
            if original != included:
                lines.append(f"  {path} ({original} lines, truncated to {included})")
            else:
                lines.append(f"  {path} ({original} lines)")

        return "\n".join(lines)

    # =========================================================================
    # Phase 3: Output Writing (Plain, Markdown, XML)
    # =========================================================================

    def _normalize_path_display(self, path: Path) -> str:
        """Normalize path for display (forward slashes on all platforms).

        Args:
            path: Path to normalize.

        Returns:
            Path string with forward slashes for consistent cross-platform display.
        """
        return str(PurePosixPath(path))

    def _get_lang_for_file(self, path: Path) -> str:
        """Get language identifier for markdown code fence.

        Args:
            path: Path to the file.

        Returns:
            Language identifier (e.g., "python", "typescript") or extension as-is.
        """
        # Handle special filenames first
        name_lower = path.name.lower()
        if name_lower == "dockerfile":
            return "dockerfile"
        if name_lower in ("makefile", "gnumakefile"):
            return "makefile"

        # Get extension (without dot, lowercase)
        ext = path.suffix.lstrip(".").lower()
        if not ext:
            return "text"

        # Look up in mapping, fall back to extension as-is
        return EXT_TO_LANG.get(ext, ext)

    def _xml_escape(self, text: str) -> str:
        """Escape special XML characters.

        Args:
            text: Text to escape.

        Returns:
            XML-escaped text.
        """
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )

    def _escape_cdata(self, content: str) -> str:
        """Escape content for CDATA section.

        CDATA sections cannot contain the sequence ']]>' so we need to split it.

        Args:
            content: Content to escape.

        Returns:
            Content safe for CDATA section.
        """
        # Replace ]]> with ]]]]><![CDATA[>
        # This closes the CDATA, adds >, then reopens CDATA
        return content.replace("]]>", "]]]]><![CDATA[>")

    def _read_file_lines(
        self, path: Path, max_lines: int = 0
    ) -> tuple[str, int]:
        """Read file content, optionally limiting to max_lines.

        Args:
            path: Path to the file.
            max_lines: Maximum lines to read (0 = unlimited).

        Returns:
            Tuple of (content, total_line_count).
        """
        with open(path, encoding="utf-8", errors="replace", newline="") as f:
            if max_lines <= 0:
                content = f.read()
                lines = self._count_lines(content)
                return content, lines

            # Read limited lines - handle different line endings
            lines_read: list[str] = []
            total_lines = 0

            # Read character by character to handle all line ending styles
            buffer: list[str] = []
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
                total_lines += self._count_lines(remaining)

            # Join with Unix newlines for consistent output
            return "\n".join(lines_read) + ("\n" if lines_read else ""), total_lines

    async def _write_concatenated(
        self,
        files: list[FileInfo],
        output_path: Path,
        output_format: str,
        lines_limit: int,
        max_total: int,
    ) -> tuple[int, int]:
        """Write concatenated files to output path.

        Args:
            files: List of FileInfo objects to concatenate.
            output_path: Path to write output file.
            output_format: Output format (plain/markdown/xml).
            lines_limit: Maximum lines per file (0 = unlimited).
            max_total: Maximum total lines (0 = unlimited).

        Returns:
            Tuple of (files_written, total_lines_written).
        """
        def do_write() -> tuple[int, int]:
            files_written = 0
            total_lines_written = 0

            with open(output_path, "w", encoding="utf-8", newline="\n") as f:
                # Write header based on format
                self._write_header(f, output_format, len(files))

                for info in files:
                    # Check total budget
                    if max_total > 0 and total_lines_written >= max_total:
                        self._write_budget_exhausted(f, output_format, max_total)
                        break

                    # Calculate lines to include
                    lines_to_include = info.lines
                    if lines_limit > 0 and lines_to_include > lines_limit:
                        lines_to_include = lines_limit

                    # Apply total limit
                    if max_total > 0:
                        remaining = max_total - total_lines_written
                        if lines_to_include > remaining:
                            lines_to_include = remaining

                    # Read file content
                    read_limit = lines_to_include if lines_to_include < info.lines else 0
                    content, _ = self._read_file_lines(info.path, read_limit)

                    # Write file entry
                    self._write_file_entry(
                        f, output_format, info.path, content, info.lines, lines_to_include
                    )

                    files_written += 1
                    total_lines_written += lines_to_include

                # Write footer
                self._write_footer(f, output_format)

            return files_written, total_lines_written

        return await asyncio.to_thread(do_write)

    def _write_header(self, f: Any, output_format: str, file_count: int) -> None:
        """Write document header.

        Args:
            f: File handle to write to.
            output_format: Output format (plain/markdown/xml).
            file_count: Number of files being concatenated.
        """
        timestamp = datetime.now(UTC).isoformat()

        if output_format == "plain":
            f.write("# Concatenated files\n")
            f.write(f"# Created: {timestamp}\n")
            f.write(f"# File count: {file_count}\n")
            f.write("# " + "=" * 75 + "\n")
            f.write("\n")

        elif output_format == "markdown":
            f.write("# Concatenated Files\n")
            f.write("\n")
            f.write(f"- **Created:** {timestamp}\n")
            f.write(f"- **Files:** {file_count}\n")
            f.write("\n")
            f.write("---\n")
            f.write("\n")

        elif output_format == "xml":
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            f.write("<concatenated_files>\n")
            f.write("  <metadata>\n")
            f.write(f"    <generated_at>{timestamp}</generated_at>\n")
            f.write(f"    <file_count>{file_count}</file_count>\n")
            f.write("  </metadata>\n")
            f.write("  <files>\n")

    def _write_file_entry(
        self,
        f: Any,
        output_format: str,
        path: Path,
        content: str,
        total_lines: int,
        showing_lines: int,
    ) -> None:
        """Write a single file entry.

        Args:
            f: File handle to write to.
            output_format: Output format (plain/markdown/xml).
            path: Path to the file.
            content: File content to write.
            total_lines: Total lines in the original file.
            showing_lines: Number of lines being shown.
        """
        path_display = self._normalize_path_display(path)
        truncated = showing_lines < total_lines

        # Normalize content line endings
        normalized_content = content.replace("\r\n", "\n").replace("\r", "\n")
        if normalized_content and not normalized_content.endswith("\n"):
            normalized_content += "\n"

        if output_format == "plain":
            f.write("\n")
            f.write("# " + "=" * 75 + "\n")
            f.write(f"# File: {path_display}\n")
            if truncated:
                f.write(f"# Lines: {total_lines} (showing {showing_lines})\n")
            else:
                f.write(f"# Lines: {total_lines}\n")
            f.write("# " + "=" * 75 + "\n")
            f.write("\n")
            f.write(normalized_content)
            if truncated:
                f.write(f"\n# ... ({total_lines - showing_lines} more lines) ...\n")

        elif output_format == "markdown":
            lang = self._get_lang_for_file(path)
            f.write(f"## {path_display}\n")
            f.write("\n")
            if truncated:
                f.write(f"*Lines: {total_lines} (showing {showing_lines})*\n")
            else:
                f.write(f"*Lines: {total_lines}*\n")
            f.write("\n")
            f.write(f"```{lang}\n")
            f.write(normalized_content)
            f.write("```\n")
            if truncated:
                f.write(f"\n*... ({total_lines - showing_lines} more lines) ...*\n")
            f.write("\n")

        elif output_format == "xml":
            escaped_path = self._xml_escape(path_display)
            escaped_content = self._escape_cdata(normalized_content)
            f.write("    <file ")
            f.write(f'path="{escaped_path}" ')
            f.write(f'lines="{total_lines}"')
            if truncated:
                f.write(f' lines_shown="{showing_lines}"')
            f.write(">\n")
            f.write(f"      <![CDATA[{escaped_content}]]>\n")
            f.write("    </file>\n")

    def _write_budget_exhausted(
        self, f: Any, output_format: str, budget: int
    ) -> None:
        """Write message when line budget is exhausted.

        Args:
            f: File handle to write to.
            output_format: Output format (plain/markdown/xml).
            budget: The total line budget that was exhausted.
        """
        if output_format == "plain":
            f.write("\n")
            f.write("# " + "=" * 75 + "\n")
            f.write(f"# NOTE: Total line budget ({budget}) exhausted\n")
            f.write("# Remaining files skipped\n")
            f.write("# " + "=" * 75 + "\n")

        elif output_format == "markdown":
            f.write("\n")
            f.write(f"> **Note:** Total line budget ({budget}) exhausted. ")
            f.write("Remaining files skipped.\n")
            f.write("\n")

        elif output_format == "xml":
            f.write(f"    <!-- Total line budget ({budget}) exhausted. ")
            f.write("Remaining files skipped. -->\n")

    def _write_footer(self, f: Any, output_format: str) -> None:
        """Write document footer.

        Args:
            f: File handle to write to.
            output_format: Output format (plain/markdown/xml).
        """
        if output_format == "xml":
            f.write("  </files>\n")
            f.write("</concatenated_files>\n")
        # Plain and markdown don't need explicit footers

    async def execute(
        self,
        extensions: list[str] | None = None,
        path: str = ".",
        exclude: list[str] | None = None,
        lines: int = 0,
        max_total: int = 0,
        format: str = "plain",  # noqa: A002
        sort: str = "alpha",
        gitignore: bool = True,
        dry_run: bool = True,
        **kwargs: Any,
    ) -> ToolResult:
        """Find files by extension and concatenate them.

        Args:
            extensions: File extensions to include (without dots).
            path: Directory to search.
            exclude: Additional patterns to exclude.
            lines: Maximum lines per file (0 = unlimited).
            max_total: Maximum total lines (0 = unlimited).
            format: Output format (plain/markdown/xml).
            sort: Sort order (alpha/mtime/size).
            gitignore: Use .gitignore rules.
            dry_run: Return stats without creating output.
            **kwargs: Additional arguments (ignored).

        Returns:
            ToolResult with concatenated content or dry run stats.
        """
        # Validate extensions
        if not extensions:
            return ToolResult(error="No extensions provided. Example: ['py', 'ts']")

        # Validate and resolve base path
        try:
            base_path = self._validate_path(path)
        except (PathSecurityError, ValueError) as e:
            return ToolResult(error=str(e))

        # Verify base path is a directory
        is_dir = await asyncio.to_thread(base_path.is_dir)
        if not is_dir:
            if await asyncio.to_thread(base_path.exists):
                return ToolResult(error=f"Not a directory: {path}")
            return ToolResult(error=f"Directory not found: {path}")

        # Find files - use git if available and gitignore=True, else glob
        use_git = False
        if gitignore:
            use_git = await self._git_available(base_path)

        if use_git:
            file_paths = await self._find_files_git(base_path, extensions, exclude)
        else:
            file_paths = await self._find_files_glob(base_path, extensions, exclude)

        if not file_paths:
            ext_str = ", ".join(extensions)
            return ToolResult(output=f"No files with extensions ({ext_str}) found in {path}")

        # Collect file info and filter out binary files
        file_infos, binary_skipped = await self._collect_file_info(file_paths)

        if not file_infos:
            ext_str = ", ".join(extensions)
            if binary_skipped > 0:
                msg = (
                    f"All {binary_skipped} files with extensions ({ext_str}) "
                    f"in {path} are binary or unreadable"
                )
                return ToolResult(output=msg)
            return ToolResult(
                output=f"No readable files with extensions ({ext_str}) found in {path}"
            )

        # Sort files
        file_infos = self._sort_files(file_infos, sort)

        # Generate output path
        output_path = self._generate_output_path(base_path, extensions, format)

        if dry_run:
            # Compute and return dry run statistics
            result = self._compute_dry_run(
                files=file_infos,
                binary_skipped=binary_skipped,
                lines_limit=lines,
                max_total=max_total,
                output_format=format,
                output_path=str(output_path).replace("\\", "/"),
            )
            output = self._format_dry_run_output(result, extensions, base_path, sort)
            return ToolResult(output=output)

        # Write concatenated output
        try:
            files_written, total_lines = await self._write_concatenated(
                files=file_infos,
                output_path=output_path,
                output_format=format,
                lines_limit=lines,
                max_total=max_total,
            )
        except OSError as e:
            return ToolResult(error=f"Failed to write output file: {e}")

        # Format success message
        output_display = self._normalize_path_display(output_path)
        msg_lines = [
            "=== Concatenation Complete ===",
            "",
            f"Output file:    {output_display}",
            f"Files written:  {files_written}",
            f"Total lines:    {total_lines}",
        ]
        if binary_skipped > 0:
            msg_lines.append(f"Binary skipped: {binary_skipped}")

        return ToolResult(output="\n".join(msg_lines))


# Factory for dependency injection
concat_files_factory = file_skill_factory(ConcatFilesSkill)
