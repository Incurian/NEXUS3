"""Outline skill for structural file overview.

Returns headings for markdown, class/function signatures for code,
key hierarchies for data files. Acts as an "IDE outline view" for agents,
enabling cheap structural awareness without reading full content.
"""

import asyncio
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nexus3.core.constants import MAX_FILE_SIZE_BYTES, MAX_OUTPUT_BYTES
from nexus3.core.errors import PathSecurityError
from nexus3.core.types import ToolResult
from nexus3.skill.base import FileSkill, file_skill_factory

# =============================================================================
# Constants
# =============================================================================

_MAX_OUTLINE_LINES = 50000  # More generous than read_file; outline only stores entries
_MAX_DIR_FILES = 100
_MAX_DIR_OUTPUT_BYTES = 50000

# Extension to parser language key
EXT_TO_PARSER: dict[str, str] = {
    # Python
    "py": "python", "pyi": "python", "pyx": "python",
    # JavaScript/TypeScript
    "js": "javascript", "mjs": "javascript", "cjs": "javascript", "jsx": "javascript",
    "ts": "typescript", "mts": "typescript", "cts": "typescript", "tsx": "typescript",
    # Systems
    "rs": "rust",
    "go": "go",
    "c": "c", "h": "c",
    "cpp": "cpp", "cc": "cpp", "cxx": "cpp", "hpp": "cpp", "hxx": "cpp",
    # Data/config
    "json": "json", "jsonc": "json", "json5": "json",
    "yaml": "yaml", "yml": "yaml",
    "toml": "toml",
    # Markup
    "md": "markdown", "markdown": "markdown",
    "html": "html", "htm": "html",
    "css": "css", "scss": "css", "less": "css",
    # Other
    "sql": "sql",
}

# Filename-based detection (no extension)
FILENAME_TO_PARSER: dict[str, str] = {
    "Makefile": "makefile",
    "GNUmakefile": "makefile",
    "makefile": "makefile",
    "Dockerfile": "dockerfile",
}


# =============================================================================
# Data Types
# =============================================================================

@dataclass
class OutlineEntry:
    """A single entry in a file outline."""
    line: int              # 1-indexed line number
    depth: int             # Nesting depth (0 = top-level)
    kind: str              # e.g., "class", "function", "method", "heading", "key"
    name: str              # The identifier/heading text
    end_line: int = 0      # Last line of this block (0 = unknown)
    signature: str = ""    # Full signature (for code), empty for non-code
    preview_lines: list[str] = field(default_factory=list)
    token_estimate: int = 0
    has_diff: bool = False


# Parser function type
OutlineParser = Callable[[list[str], int, bool, int], list[OutlineEntry]]


# =============================================================================
# Helper Functions
# =============================================================================

def _detect_language(p: Path) -> str | None:
    """Detect parser language from file extension or name."""
    if p.name in FILENAME_TO_PARSER:
        return FILENAME_TO_PARSER[p.name]
    ext = p.suffix.lstrip(".")
    if ext:
        return EXT_TO_PARSER.get(ext)
    return None


def _read_file_lines(p: Path, max_lines: int = _MAX_OUTLINE_LINES) -> list[str]:
    """Read file lines with a safety limit."""
    lines: list[str] = []
    with open(p, encoding="utf-8", errors="replace") as f:
        for line in f:
            lines.append(line.rstrip("\n"))
            if len(lines) >= max_lines:
                break
    return lines


def _get_preview(lines: list[str], entry_line: int, count: int) -> list[str]:
    """Get preview lines after an outline entry (skipping the entry itself)."""
    if count <= 0:
        return []
    start = entry_line + 1
    end = min(start + count, len(lines))
    return [lines[j] for j in range(start, end)]


def _compute_end_lines(entries: list[OutlineEntry], total_lines: int) -> None:
    """Compute end_line for each entry based on next same-or-lower-depth entry."""
    for i, entry in enumerate(entries):
        end = total_lines
        for j in range(i + 1, len(entries)):
            if entries[j].depth <= entry.depth:
                end = entries[j].line - 1
                break
        entry.end_line = end


def _format_outline(
    entries: list[OutlineEntry],
    line_numbers: bool,
    filename: str,
    language: str,
    show_tokens: bool = False,
    show_diff: bool = False,
) -> str:
    """Format outline entries into readable text output."""
    parts: list[str] = []
    parts.append(f"# Outline: {filename} ({language})")
    parts.append("")

    for entry in entries:
        indent = "  " * entry.depth
        line_prefix = f"L{entry.line:>5} " if line_numbers else ""

        if entry.signature:
            main = f"{line_prefix}{indent}{entry.kind}: {entry.signature}"
        else:
            main = f"{line_prefix}{indent}{entry.kind}: {entry.name}"

        if show_tokens and entry.token_estimate > 0:
            main += f"  (~{entry.token_estimate} tokens)"

        if show_diff and entry.has_diff:
            main += "  [CHANGED]"

        parts.append(main)

        if entry.preview_lines:
            preview_indent = " " * (len(line_prefix) + len(indent) + 2)
            for pl in entry.preview_lines:
                parts.append(f"{preview_indent}| {pl}")

    return "\n".join(parts)


# =============================================================================
# Token Estimation (Phase 7)
# =============================================================================

def _annotate_token_estimates(entries: list[OutlineEntry], lines: list[str]) -> None:
    """Annotate each entry with approximate token count for its body."""
    from nexus3.context.token_counter import SimpleTokenCounter
    counter = SimpleTokenCounter()

    for entry in entries:
        if entry.end_line <= 0:
            continue
        start_idx = entry.line - 1
        end_idx = min(entry.end_line, len(lines))
        section_text = "\n".join(lines[start_idx:end_idx])
        entry.token_estimate = counter.count(section_text)


# =============================================================================
# Filtered Read / Symbol Extraction (Phase 8)
# =============================================================================

def _extract_symbol(
    entries: list[OutlineEntry],
    lines: list[str],
    symbol_name: str,
    filename: str,
) -> ToolResult:
    """Extract the full body of a named symbol from the file."""
    match: OutlineEntry | None = None
    for entry in entries:
        if entry.name == symbol_name:
            match = entry
            break

    if match is None:
        for entry in entries:
            if entry.name.lower() == symbol_name.lower():
                match = entry
                break

    if match is None:
        available = [e.name for e in entries if e.depth == 0]
        if len(available) > 20:
            available = available[:20] + [f"... and {len(available) - 20} more"]
        return ToolResult(
            error=f"Symbol '{symbol_name}' not found in {filename}.\n"
            f"Available top-level symbols: {', '.join(available)}"
        )

    start_idx = match.line - 1
    end_idx = min(match.end_line, len(lines))

    extracted_lines: list[str] = []
    total_bytes = 0
    truncated = False
    for i in range(start_idx, end_idx):
        numbered_line = f"{i + 1}: {lines[i]}\n"
        line_bytes = len(numbered_line.encode("utf-8"))
        if total_bytes + line_bytes > MAX_OUTPUT_BYTES:
            truncated = True
            break
        extracted_lines.append(numbered_line)
        total_bytes += line_bytes

    header = f"# {match.kind}: {match.name} ({filename}, L{match.line}-{match.end_line})\n\n"
    body = "".join(extracted_lines)
    if truncated:
        body += (
            f"\n(truncated at {MAX_OUTPUT_BYTES} bytes"
            " - use read_file with offset/limit for the rest)"
        )

    return ToolResult(output=header + body)


# =============================================================================
# Diff-Aware (Phase 10)
# =============================================================================

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _get_diff_ranges(file_path: Path) -> list[tuple[int, int]] | None:
    """Get line ranges with uncommitted changes for a file."""
    cwd = str(file_path.parent)
    fname = file_path.name

    try:
        result = subprocess.run(
            ["git", "diff", "-U0", "--no-ext-diff", "HEAD", "--", fname],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            result = subprocess.run(
                ["git", "diff", "-U0", "--no-ext-diff", "--", fname],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=5,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode != 0:
                return None
    except (OSError, subprocess.TimeoutExpired):
        return None

    ranges: list[tuple[int, int]] = []
    for line in result.stdout.splitlines():
        m = _HUNK_RE.match(line)
        if m:
            start = int(m.group(1))
            count = int(m.group(2)) if m.group(2) else 1
            if count == 0:
                continue
            end = start + count - 1
            ranges.append((start, end))

    return ranges


def _annotate_diff_markers(
    entries: list[OutlineEntry],
    changed_ranges: list[tuple[int, int]],
) -> None:
    """Mark outline entries whose line ranges overlap with changed ranges."""
    for entry in entries:
        if entry.end_line <= 0:
            continue
        for change_start, change_end in changed_ranges:
            if entry.line <= change_end and entry.end_line >= change_start:
                entry.has_diff = True
                break


def _get_diff_files(dir_path: Path) -> set[str] | None:
    """Get set of filenames with uncommitted changes in a directory."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD", "--", str(dir_path)],
            cwd=str(dir_path),
            capture_output=True,
            text=True,
            timeout=5,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            return None
        result2 = subprocess.run(
            ["git", "diff", "--name-only", "--", str(dir_path)],
            cwd=str(dir_path),
            capture_output=True,
            text=True,
            timeout=5,
            encoding="utf-8",
            errors="replace",
        )
        files: set[str] = set()
        for line in (result.stdout + "\n" + result2.stdout).splitlines():
            line = line.strip()
            if line:
                files.add(Path(line).name)
        return files
    except (OSError, subprocess.TimeoutExpired):
        return None


# =============================================================================
# Markdown Parser
# =============================================================================

_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")


def parse_markdown(
    lines: list[str], max_depth: int, signatures: bool, preview: int
) -> list[OutlineEntry]:
    """Parse markdown headings."""
    entries: list[OutlineEntry] = []
    for i, line in enumerate(lines):
        m = _MD_HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            if level > max_depth:
                continue
            heading_text = m.group(2).strip()
            entries.append(OutlineEntry(
                line=i + 1,
                depth=level - 1,
                kind=f"h{level}",
                name=heading_text,
                preview_lines=_get_preview(lines, i, preview),
            ))
    return entries


# =============================================================================
# Python Parser
# =============================================================================

_PY_CLASS_RE = re.compile(r"^(\s*)(class)\s+(\w+)([^:]*)?:")
_PY_FUNC_RE = re.compile(r"^(\s*)(async\s+def|def)\s+(\w+)\s*\(([^)]*)\)([^:]*)?:")
_PY_FUNC_MULTILINE_RE = re.compile(r"^(\s*)(async\s+def|def)\s+(\w+)\s*\(")
_PY_DECORATOR_RE = re.compile(r"^(\s*)@(\w[\w.]*)")
_PY_ASSIGN_RE = re.compile(r"^([A-Z][A-Z_0-9]*)\s*(?::[^=]*)?\s*=")


def _compute_py_depth(indent: int, indent_stack: list[int]) -> int:
    """Compute nesting depth from indentation level."""
    while indent_stack and indent_stack[-1] >= indent:
        indent_stack.pop()
    return len(indent_stack)


def _update_py_indent_stack(indent: int, indent_stack: list[int]) -> list[int]:
    """Update indent stack after a block-opening line."""
    while indent_stack and indent_stack[-1] >= indent:
        indent_stack.pop()
    indent_stack.append(indent)
    return indent_stack


def parse_python(
    lines: list[str], max_depth: int, signatures: bool, preview: int
) -> list[OutlineEntry]:
    """Parse Python classes, functions, methods, decorators, module constants."""
    entries: list[OutlineEntry] = []
    indent_stack: list[int] = []
    pending_decorators: list[str] = []

    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(stripped)
        depth = _compute_py_depth(indent, list(indent_stack))

        if depth >= max_depth:
            dm = _PY_DECORATOR_RE.match(line)
            if dm:
                pending_decorators.append(dm.group(2))
            continue

        dm = _PY_DECORATOR_RE.match(line)
        if dm:
            pending_decorators.append(dm.group(2))
            continue

        cm = _PY_CLASS_RE.match(line)
        if cm:
            _class_indent, _, class_name, bases = cm.groups()
            sig = f"class {class_name}{bases or ''}" if signatures else class_name
            if pending_decorators and signatures:
                sig = " ".join(f"@{d}" for d in pending_decorators) + " " + sig
            entries.append(OutlineEntry(
                line=i + 1,
                depth=depth,
                kind="class",
                name=class_name,
                signature=sig if signatures else "",
                preview_lines=_get_preview(lines, i, preview),
            ))
            indent_stack = _update_py_indent_stack(indent, indent_stack)
            pending_decorators = []
            continue

        fm = _PY_FUNC_RE.match(line)
        if not fm:
            # Try multiline: def foo( with params on next lines
            fm = _PY_FUNC_MULTILINE_RE.match(line)
            if fm:
                _func_indent, keyword, func_name = fm.groups()
                is_method = depth > 0
                kind = "method" if is_method else "function"
                if signatures:
                    sig_line = line.strip()
                    j = i + 1
                    while j < len(lines):
                        sig_line += " " + lines[j].strip()
                        if lines[j].rstrip().endswith(":"):
                            break
                        j += 1
                    sig = sig_line.rstrip(":")
                    if pending_decorators:
                        sig = (
                            " ".join(f"@{d}" for d in pending_decorators)
                            + " " + sig
                        )
                else:
                    sig = ""
                entries.append(OutlineEntry(
                    line=i + 1,
                    depth=depth,
                    kind=kind,
                    name=func_name,
                    signature=sig,
                    preview_lines=_get_preview(lines, i, preview),
                ))
                indent_stack = _update_py_indent_stack(indent, indent_stack)
                pending_decorators = []
                continue
        if fm:
            _func_indent, keyword, func_name, params, return_ann = fm.groups()
            is_method = depth > 0
            kind = "method" if is_method else "function"
            if signatures:
                sig_line = line.strip()
                if not sig_line.endswith(":"):
                    j = i + 1
                    while j < len(lines) and not lines[j].rstrip().endswith(":"):
                        sig_line += " " + lines[j].strip()
                        j += 1
                    if j < len(lines):
                        sig_line += " " + lines[j].strip()
                sig = sig_line.rstrip(":")
                if pending_decorators:
                    sig = (
                        " ".join(f"@{d}" for d in pending_decorators)
                        + " " + sig
                    )
            else:
                sig = ""
            entries.append(OutlineEntry(
                line=i + 1,
                depth=depth,
                kind=kind,
                name=func_name,
                signature=sig,
                preview_lines=_get_preview(lines, i, preview),
            ))
            indent_stack = _update_py_indent_stack(indent, indent_stack)
            pending_decorators = []
            continue

        if depth == 0:
            am = _PY_ASSIGN_RE.match(line)
            if am:
                entries.append(OutlineEntry(
                    line=i + 1,
                    depth=0,
                    kind="constant",
                    name=am.group(1),
                    signature=line.strip() if signatures else "",
                    preview_lines=_get_preview(lines, i, preview),
                ))
                pending_decorators = []

    return entries


# =============================================================================
# JSON Parser
# =============================================================================

def _find_json_key_line(lines: list[str], key: str, depth: int) -> int:
    """Find line number for a JSON key (best-effort search)."""
    # Search for "key": pattern at appropriate depth
    pattern = f'"{key}"'
    for i, line in enumerate(lines):
        if pattern in line:
            return i + 1
    return 1


def _json_value_summary(value: Any) -> str:
    """Summarize a JSON value type."""
    if isinstance(value, dict):
        return f"{{{len(value)} keys}}"
    elif isinstance(value, list):
        return f"[{len(value)} items]"
    elif isinstance(value, str):
        if len(value) > 40:
            return f'"{value[:37]}..."'
        return f'"{value}"'
    elif isinstance(value, bool):
        return str(value).lower()
    elif value is None:
        return "null"
    else:
        return str(value)


def _walk_json(
    obj: Any,
    entries: list[OutlineEntry],
    max_depth: int,
    depth: int,
    lines: list[str],
    seen_keys: set[str],
) -> None:
    """Recursively walk JSON structure."""
    if depth >= max_depth:
        return
    if isinstance(obj, dict):
        for key in obj:
            line_num = _find_json_key_line(lines, key, depth)
            value = obj[key]
            value_type = _json_value_summary(value)
            # Track seen key+line combos to avoid duplicates
            combo = f"{key}:{line_num}"
            if combo not in seen_keys:
                seen_keys.add(combo)
                entries.append(OutlineEntry(
                    line=line_num,
                    depth=depth,
                    kind="key",
                    name=key,
                    signature=f"{key}: {value_type}" if value_type else "",
                ))
                if isinstance(value, (dict, list)):
                    _walk_json(value, entries, max_depth, depth + 1, lines, seen_keys)


def parse_json(
    lines: list[str], max_depth: int, signatures: bool, preview: int
) -> list[OutlineEntry]:
    """Parse JSON key hierarchy."""
    import json as json_mod

    text = "\n".join(lines)
    try:
        data = json_mod.loads(text)
    except json_mod.JSONDecodeError:
        return []

    entries: list[OutlineEntry] = []
    seen_keys: set[str] = set()
    _walk_json(data, entries, max_depth, depth=0, lines=lines, seen_keys=seen_keys)
    return entries


# =============================================================================
# YAML Parser
# =============================================================================

_YAML_KEY_RE = re.compile(r"^(\s*)([^\s#:][^:]*?):\s*(.*)")


def parse_yaml(
    lines: list[str], max_depth: int, signatures: bool, preview: int
) -> list[OutlineEntry]:
    """Parse YAML key hierarchy."""
    entries: list[OutlineEntry] = []
    indent_stack: list[int] = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("-"):
            continue

        m = _YAML_KEY_RE.match(line)
        if m:
            indent_str, key, value = m.groups()
            indent = len(indent_str)

            # Compute depth from indentation
            while indent_stack and indent_stack[-1] >= indent:
                indent_stack.pop()
            depth = len(indent_stack)

            if depth >= max_depth:
                continue

            indent_stack.append(indent)

            value_summary = ""
            if signatures and value.strip():
                val = value.strip()
                if len(val) > 60:
                    val = val[:57] + "..."
                value_summary = f"{key}: {val}"

            entries.append(OutlineEntry(
                line=i + 1,
                depth=depth,
                kind="key",
                name=key,
                signature=value_summary,
                preview_lines=_get_preview(lines, i, preview),
            ))

    return entries


# =============================================================================
# TOML Parser
# =============================================================================

_TOML_TABLE_RE = re.compile(r"^\[([^\]]+)\]")
_TOML_ARRAY_TABLE_RE = re.compile(r"^\[\[([^\]]+)\]\]")
_TOML_KEY_RE = re.compile(r"^(\w[\w.-]*)\s*=\s*(.*)")


def parse_toml(
    lines: list[str], max_depth: int, signatures: bool, preview: int
) -> list[OutlineEntry]:
    """Parse TOML tables and keys."""
    entries: list[OutlineEntry] = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Array of tables [[section]]
        m = _TOML_ARRAY_TABLE_RE.match(stripped)
        if m:
            table_name = m.group(1).strip()
            depth = table_name.count(".")
            if depth < max_depth:
                entries.append(OutlineEntry(
                    line=i + 1,
                    depth=depth,
                    kind="array-table",
                    name=table_name,
                    preview_lines=_get_preview(lines, i, preview),
                ))
            continue

        # Table [section]
        m = _TOML_TABLE_RE.match(stripped)
        if m:
            table_name = m.group(1).strip()
            depth = table_name.count(".")
            if depth < max_depth:
                entries.append(OutlineEntry(
                    line=i + 1,
                    depth=depth,
                    kind="table",
                    name=table_name,
                    preview_lines=_get_preview(lines, i, preview),
                ))
            continue

        # Key = value (only at depth 0 in root, or under current table)
        m = _TOML_KEY_RE.match(stripped)
        if m:
            key_name = m.group(1)
            value = m.group(2).strip()
            # Top-level keys or keys under a table
            depth = 0
            if entries and entries[-1].kind in ("table", "array-table"):
                depth = entries[-1].depth + 1
            if depth < max_depth:
                value_sig = f"{key_name} = {value}" if signatures and value else ""
                entries.append(OutlineEntry(
                    line=i + 1,
                    depth=depth,
                    kind="key",
                    name=key_name,
                    signature=value_sig,
                    preview_lines=_get_preview(lines, i, preview),
                ))

    return entries


# =============================================================================
# JavaScript Parser
# =============================================================================

_JS_FUNC_RE = re.compile(r"^(export\s+)?(async\s+)?function\s+(\w+)")
_JS_CLASS_RE = re.compile(r"^(export\s+)?(abstract\s+)?class\s+(\w+)")
_JS_CONST_RE = re.compile(r"^(export\s+)?(const|let|var)\s+(\w+)")
_JS_INTERFACE_RE = re.compile(r"^(export\s+)?interface\s+(\w+)")
_JS_TYPE_RE = re.compile(r"^(export\s+)?type\s+(\w+)")
_JS_ARROW_RE = re.compile(r"^(export\s+)?(const|let)\s+(\w+)\s*=\s*(async\s+)?\(")


def parse_javascript(
    lines: list[str], max_depth: int, signatures: bool, preview: int
) -> list[OutlineEntry]:
    """Parse JavaScript/JSX exports, classes, functions."""
    entries: list[OutlineEntry] = []
    in_class = False
    class_indent = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("//") or stripped.startswith("/*"):
            continue

        indent = len(line) - len(line.lstrip())

        # Track class scope (simple brace counting)
        if in_class and indent <= class_indent and stripped.startswith("}"):
            in_class = False
            continue

        # Top-level only for max_depth=1
        if max_depth == 1 and indent > 0 and not in_class:
            continue

        depth = 1 if in_class else 0
        if depth >= max_depth:
            continue

        # Class
        m = _JS_CLASS_RE.match(stripped)
        if m:
            class_name = m.group(3)
            sig = stripped.split("{")[0].strip() if signatures else ""
            entries.append(OutlineEntry(
                line=i + 1, depth=0, kind="class", name=class_name,
                signature=sig, preview_lines=_get_preview(lines, i, preview),
            ))
            in_class = True
            class_indent = indent
            continue

        # Function declaration
        m = _JS_FUNC_RE.match(stripped)
        if m:
            func_name = m.group(3)
            sig = stripped.split("{")[0].strip() if signatures else ""
            entries.append(OutlineEntry(
                line=i + 1, depth=depth, kind="function", name=func_name,
                signature=sig, preview_lines=_get_preview(lines, i, preview),
            ))
            continue

        # Arrow function: const name = (async) (...) =>
        m = _JS_ARROW_RE.match(stripped)
        if m:
            func_name = m.group(3)
            sig = stripped.split("=>")[0].strip() + " =>" if signatures else ""
            entries.append(OutlineEntry(
                line=i + 1, depth=depth, kind="function", name=func_name,
                signature=sig, preview_lines=_get_preview(lines, i, preview),
            ))
            continue

        # Only capture top-level const/let/var when not an arrow function
        if depth == 0:
            m = _JS_CONST_RE.match(stripped)
            if m:
                var_name = m.group(3)
                entries.append(OutlineEntry(
                    line=i + 1, depth=0, kind="variable", name=var_name,
                    signature=stripped.split("=")[0].strip() if signatures else "",
                    preview_lines=_get_preview(lines, i, preview),
                ))

    return entries


# =============================================================================
# TypeScript Parser (extends JavaScript with interfaces/types)
# =============================================================================

def parse_typescript(
    lines: list[str], max_depth: int, signatures: bool, preview: int
) -> list[OutlineEntry]:
    """Parse TypeScript (JavaScript + interfaces + type aliases)."""
    entries = parse_javascript(lines, max_depth, signatures, preview)

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue

        # Interface
        m = _JS_INTERFACE_RE.match(stripped)
        if m:
            iface_name = m.group(2)
            sig = stripped.split("{")[0].strip() if signatures else ""
            entries.append(OutlineEntry(
                line=i + 1, depth=0, kind="interface", name=iface_name,
                signature=sig, preview_lines=_get_preview(lines, i, preview),
            ))
            continue

        # Type alias
        m = _JS_TYPE_RE.match(stripped)
        if m:
            type_name = m.group(2)
            sig = stripped if signatures else ""
            entries.append(OutlineEntry(
                line=i + 1, depth=0, kind="type", name=type_name,
                signature=sig, preview_lines=_get_preview(lines, i, preview),
            ))

    # Sort by line number since we appended TS-specific entries after JS entries
    entries.sort(key=lambda e: e.line)
    return entries


# =============================================================================
# Rust Parser
# =============================================================================

_RS_FN_RE = re.compile(r"^(\s*)(pub\s+)?(?:pub\(crate\)\s+)?(async\s+)?fn\s+(\w+)")
_RS_STRUCT_RE = re.compile(r"^(\s*)(pub\s+)?struct\s+(\w+)")
_RS_ENUM_RE = re.compile(r"^(\s*)(pub\s+)?enum\s+(\w+)")
_RS_TRAIT_RE = re.compile(r"^(\s*)(pub\s+)?trait\s+(\w+)")
_RS_IMPL_RE = re.compile(r"^(\s*)impl\s+(?:<[^>]+>\s+)?(\w+)")


def parse_rust(
    lines: list[str], max_depth: int, signatures: bool, preview: int
) -> list[OutlineEntry]:
    """Parse Rust structs, enums, traits, impl blocks, functions."""
    entries: list[OutlineEntry] = []
    in_impl = False
    impl_indent = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue

        indent = len(line) - len(line.lstrip())

        # Track impl block scope
        if in_impl and indent <= impl_indent and stripped == "}":
            in_impl = False
            continue

        depth = 1 if in_impl and indent > impl_indent else 0
        if depth >= max_depth:
            continue

        # Struct
        m = _RS_STRUCT_RE.match(line)
        if m:
            name = m.group(3)
            sig = stripped.split("{")[0].split("(")[0].strip() if signatures else ""
            entries.append(OutlineEntry(
                line=i + 1, depth=0, kind="struct", name=name,
                signature=sig, preview_lines=_get_preview(lines, i, preview),
            ))
            continue

        # Enum
        m = _RS_ENUM_RE.match(line)
        if m:
            name = m.group(3)
            sig = stripped.split("{")[0].strip() if signatures else ""
            entries.append(OutlineEntry(
                line=i + 1, depth=0, kind="enum", name=name,
                signature=sig, preview_lines=_get_preview(lines, i, preview),
            ))
            continue

        # Trait
        m = _RS_TRAIT_RE.match(line)
        if m:
            name = m.group(3)
            sig = stripped.split("{")[0].strip() if signatures else ""
            entries.append(OutlineEntry(
                line=i + 1, depth=0, kind="trait", name=name,
                signature=sig, preview_lines=_get_preview(lines, i, preview),
            ))
            continue

        # Impl block
        m = _RS_IMPL_RE.match(line)
        if m:
            name = m.group(2)
            sig = stripped.split("{")[0].strip() if signatures else ""
            entries.append(OutlineEntry(
                line=i + 1, depth=0, kind="impl", name=name,
                signature=sig, preview_lines=_get_preview(lines, i, preview),
            ))
            in_impl = True
            impl_indent = indent
            continue

        # Function
        m = _RS_FN_RE.match(line)
        if m:
            name = m.group(4)
            sig = stripped.split("{")[0].strip() if signatures else ""
            kind = "method" if in_impl else "function"
            entries.append(OutlineEntry(
                line=i + 1, depth=depth, kind=kind, name=name,
                signature=sig, preview_lines=_get_preview(lines, i, preview),
            ))

    return entries


# =============================================================================
# Go Parser
# =============================================================================

_GO_FUNC_RE = re.compile(r"^func\s+(?:\((\w+)\s+\*?(\w+)\)\s+)?(\w+)\s*\(")
_GO_TYPE_RE = re.compile(r"^type\s+(\w+)\s+(struct|interface)")


def parse_go(
    lines: list[str], max_depth: int, signatures: bool, preview: int
) -> list[OutlineEntry]:
    """Parse Go types, interfaces, functions."""
    entries: list[OutlineEntry] = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue

        # Type declaration
        m = _GO_TYPE_RE.match(stripped)
        if m:
            name = m.group(1)
            type_kind = m.group(2)
            sig = stripped.split("{")[0].strip() if signatures else ""
            entries.append(OutlineEntry(
                line=i + 1, depth=0, kind=type_kind, name=name,
                signature=sig, preview_lines=_get_preview(lines, i, preview),
            ))
            continue

        # Function/method
        m = _GO_FUNC_RE.match(stripped)
        if m:
            receiver_var, receiver_type, func_name = m.groups()
            if receiver_type:
                kind = "method"
                depth = 1 if max_depth > 1 else 0
            else:
                kind = "function"
                depth = 0
            if depth >= max_depth:
                continue
            sig = stripped.split("{")[0].strip() if signatures else ""
            entries.append(OutlineEntry(
                line=i + 1, depth=depth, kind=kind, name=func_name,
                signature=sig, preview_lines=_get_preview(lines, i, preview),
            ))

    return entries


# =============================================================================
# C/C++ Parser
# =============================================================================

_C_FUNC_RE = re.compile(r"^(\w[\w\s*&:<>]*?)\s+(\w+)\s*\(([^)]*)\)\s*\{?")
_C_CLASS_RE = re.compile(r"^(class|struct)\s+(\w+)")
_C_ENUM_RE = re.compile(r"^enum\s+(class\s+)?(\w+)")
_C_NAMESPACE_RE = re.compile(r"^namespace\s+(\w+)")
_C_TYPEDEF_RE = re.compile(r"^typedef\s+.+\s+(\w+)\s*;")


def parse_c_cpp(
    lines: list[str], max_depth: int, signatures: bool, preview: int
) -> list[OutlineEntry]:
    """Parse C/C++ functions, classes, structs, enums, namespaces."""
    entries: list[OutlineEntry] = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("//") or stripped.startswith("/*"):
            continue
        # Skip preprocessor
        if stripped.startswith("#"):
            continue

        # Namespace
        m = _C_NAMESPACE_RE.match(stripped)
        if m:
            name = m.group(1)
            entries.append(OutlineEntry(
                line=i + 1, depth=0, kind="namespace", name=name,
                preview_lines=_get_preview(lines, i, preview),
            ))
            continue

        # Class/struct
        m = _C_CLASS_RE.match(stripped)
        if m:
            kind = m.group(1)
            name = m.group(2)
            sig = stripped.split("{")[0].strip().rstrip(":").strip() if signatures else ""
            entries.append(OutlineEntry(
                line=i + 1, depth=0, kind=kind, name=name,
                signature=sig, preview_lines=_get_preview(lines, i, preview),
            ))
            continue

        # Enum
        m = _C_ENUM_RE.match(stripped)
        if m:
            name = m.group(2)
            sig = stripped.split("{")[0].strip() if signatures else ""
            entries.append(OutlineEntry(
                line=i + 1, depth=0, kind="enum", name=name,
                signature=sig, preview_lines=_get_preview(lines, i, preview),
            ))
            continue

        # Typedef
        m = _C_TYPEDEF_RE.match(stripped)
        if m:
            name = m.group(1)
            sig = stripped.rstrip(";") if signatures else ""
            entries.append(OutlineEntry(
                line=i + 1, depth=0, kind="typedef", name=name,
                signature=sig, preview_lines=_get_preview(lines, i, preview),
            ))
            continue

        # Function (must come after class/struct to avoid false matches)
        m = _C_FUNC_RE.match(stripped)
        if m:
            return_type = m.group(1).strip()
            func_name = m.group(2)
            # Skip common false positives
            if return_type in ("return", "if", "while", "for", "switch", "else"):
                continue
            sig = stripped.split("{")[0].strip() if signatures else ""
            entries.append(OutlineEntry(
                line=i + 1, depth=0, kind="function", name=func_name,
                signature=sig, preview_lines=_get_preview(lines, i, preview),
            ))

    return entries


# =============================================================================
# HTML Parser
# =============================================================================

_HTML_TAG_RE = re.compile(r"^(\s*)<(\w+)([^>]*?)(/?)>")
_HTML_ID_RE = re.compile(r'id=["\']([^"\']+)["\']')
_HTML_CLASS_RE = re.compile(r'class=["\']([^"\']+)["\']')


def parse_html(
    lines: list[str], max_depth: int, signatures: bool, preview: int
) -> list[OutlineEntry]:
    """Parse HTML element tree with id/class attributes."""
    entries: list[OutlineEntry] = []
    indent_stack: list[int] = []

    for i, line in enumerate(lines):
        m = _HTML_TAG_RE.match(line)
        if m:
            indent_str, tag_name, attrs, self_closing = m.groups()
            indent = len(indent_str)

            # Compute depth from indentation
            while indent_stack and indent_stack[-1] >= indent:
                indent_stack.pop()
            depth = len(indent_stack)

            if depth >= max_depth:
                continue

            # Extract id and class
            id_match = _HTML_ID_RE.search(attrs)
            class_match = _HTML_CLASS_RE.search(attrs)

            name_parts = [tag_name]
            if id_match:
                name_parts.append(f"#{id_match.group(1)}")
            if class_match:
                for cls in class_match.group(1).split():
                    name_parts.append(f".{cls}")

            entries.append(OutlineEntry(
                line=i + 1,
                depth=depth,
                kind="element",
                name=" ".join(name_parts),
                preview_lines=_get_preview(lines, i, preview),
            ))

            if not self_closing:
                indent_stack.append(indent)

    return entries


# =============================================================================
# CSS Parser
# =============================================================================

_CSS_SELECTOR_RE = re.compile(r"^([^\s{@/][^{]*)\{")
_CSS_AT_RULE_RE = re.compile(r"^(@\w+[^{]*)\{")


def parse_css(
    lines: list[str], max_depth: int, signatures: bool, preview: int
) -> list[OutlineEntry]:
    """Parse CSS selectors and at-rules."""
    entries: list[OutlineEntry] = []
    in_at_rule = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("/*"):
            continue

        # At-rule (@media, @keyframes, etc.)
        m = _CSS_AT_RULE_RE.match(stripped)
        if m:
            rule_name = m.group(1).strip()
            entries.append(OutlineEntry(
                line=i + 1, depth=0, kind="at-rule", name=rule_name,
                preview_lines=_get_preview(lines, i, preview),
            ))
            in_at_rule = True
            continue

        # Regular selector
        m = _CSS_SELECTOR_RE.match(stripped)
        if m:
            selector = m.group(1).strip()
            depth = 1 if in_at_rule else 0
            if depth >= max_depth:
                continue
            entries.append(OutlineEntry(
                line=i + 1, depth=depth, kind="selector", name=selector,
                preview_lines=_get_preview(lines, i, preview),
            ))
            continue

        # End of at-rule block
        if stripped == "}" and in_at_rule:
            in_at_rule = False

    return entries


# =============================================================================
# SQL Parser
# =============================================================================

_SQL_TABLE_RE = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\S+)", re.I)
_SQL_VIEW_RE = re.compile(r"CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+(\S+)", re.I)
_SQL_INDEX_RE = re.compile(
    r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(\S+)", re.I
)


def parse_sql(
    lines: list[str], max_depth: int, signatures: bool, preview: int
) -> list[OutlineEntry]:
    """Parse SQL tables, views, indexes."""
    entries: list[OutlineEntry] = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue

        m = _SQL_TABLE_RE.match(stripped)
        if m:
            entries.append(OutlineEntry(
                line=i + 1, depth=0, kind="table", name=m.group(1),
                signature=stripped.split("(")[0].strip() if signatures else "",
                preview_lines=_get_preview(lines, i, preview),
            ))
            continue

        m = _SQL_VIEW_RE.match(stripped)
        if m:
            entries.append(OutlineEntry(
                line=i + 1, depth=0, kind="view", name=m.group(1),
                signature=stripped.split(" AS")[0].strip() if signatures else "",
                preview_lines=_get_preview(lines, i, preview),
            ))
            continue

        m = _SQL_INDEX_RE.match(stripped)
        if m:
            entries.append(OutlineEntry(
                line=i + 1, depth=0, kind="index", name=m.group(1),
                signature=stripped if signatures else "",
                preview_lines=_get_preview(lines, i, preview),
            ))

    return entries


# =============================================================================
# Makefile Parser
# =============================================================================

_MAKE_TARGET_RE = re.compile(r"^([a-zA-Z_][\w.-]*):\s*")


def parse_makefile(
    lines: list[str], max_depth: int, signatures: bool, preview: int
) -> list[OutlineEntry]:
    """Parse Makefile targets."""
    entries: list[OutlineEntry] = []

    for i, line in enumerate(lines):
        if line.startswith("\t") or line.startswith(" "):
            continue  # Skip recipe lines
        m = _MAKE_TARGET_RE.match(line)
        if m:
            target = m.group(1)
            entries.append(OutlineEntry(
                line=i + 1, depth=0, kind="target", name=target,
                signature=line.strip() if signatures else "",
                preview_lines=_get_preview(lines, i, preview),
            ))

    return entries


# =============================================================================
# Dockerfile Parser
# =============================================================================

_DOCKER_FROM_RE = re.compile(r"^FROM\s+(\S+)(?:\s+AS\s+(\S+))?", re.I)


def parse_dockerfile(
    lines: list[str], max_depth: int, signatures: bool, preview: int
) -> list[OutlineEntry]:
    """Parse Dockerfile stages (FROM lines)."""
    entries: list[OutlineEntry] = []

    for i, line in enumerate(lines):
        m = _DOCKER_FROM_RE.match(line.strip())
        if m:
            image = m.group(1)
            alias = m.group(2)
            name = alias if alias else image
            sig = line.strip() if signatures else ""
            entries.append(OutlineEntry(
                line=i + 1, depth=0, kind="stage", name=name,
                signature=sig, preview_lines=_get_preview(lines, i, preview),
            ))

    return entries


# =============================================================================
# Parser Registry
# =============================================================================

PARSERS: dict[str, OutlineParser] = {
    "python": parse_python,
    "markdown": parse_markdown,
    "javascript": parse_javascript,
    "typescript": parse_typescript,
    "rust": parse_rust,
    "go": parse_go,
    "c": parse_c_cpp,
    "cpp": parse_c_cpp,
    "json": parse_json,
    "yaml": parse_yaml,
    "toml": parse_toml,
    "html": parse_html,
    "css": parse_css,
    "sql": parse_sql,
    "makefile": parse_makefile,
    "dockerfile": parse_dockerfile,
}


# =============================================================================
# Skill Class
# =============================================================================

class OutlineSkill(FileSkill):
    """Skill that returns the structural outline of a file or directory.

    Returns headings for markdown, class/function signatures for code,
    key hierarchies for data files. Acts as an "IDE outline view" for
    agents, enabling cheap structural awareness without reading full content.

    Inherits path validation from FileSkill.
    """

    @property
    def name(self) -> str:
        return "outline"

    @property
    def description(self) -> str:
        return (
            "Get the structural outline of a file (headings, classes, functions, keys). "
            "Use line numbers in output to target read_file for details. "
            "Pass a directory to get per-file top-level symbols. "
            "Use symbol='ClassName' to read a specific symbol's body. "
            "Use tokens=true for token estimates, diff=true for change markers."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file or directory to outline",
                },
                "depth": {
                    "type": "integer",
                    "description": (
                        "How deep to go (1=top-level only, 2=classes+methods, "
                        "etc.). Default: unlimited"
                    ),
                    "minimum": 1,
                },
                "preview": {
                    "type": "integer",
                    "description": (
                        "Number of context lines after each entry (0=names only). "
                        "Default: 0"
                    ),
                    "minimum": 0,
                    "maximum": 10,
                    "default": 0,
                },
                "signatures": {
                    "type": "boolean",
                    "description": (
                        "Include full signatures for code (parameters, return types). "
                        "Default: true"
                    ),
                    "default": True,
                },
                "line_numbers": {
                    "type": "boolean",
                    "description": (
                        "Show line numbers (for follow-up with read_file). "
                        "Default: true"
                    ),
                    "default": True,
                },
                "tokens": {
                    "type": "boolean",
                    "description": (
                        "Annotate each entry with approximate token count for its body. "
                        "Default: false"
                    ),
                    "default": False,
                },
                "symbol": {
                    "type": "string",
                    "description": (
                        "Return the full body of this symbol (class, function, heading). "
                        "Searches by name. Returns raw source lines, not an outline."
                    ),
                },
                "diff": {
                    "type": "boolean",
                    "description": (
                        "Mark sections that have uncommitted git changes. "
                        "Default: false"
                    ),
                    "default": False,
                },
            },
            "required": ["path"],
        }

    async def execute(
        self,
        path: str = "",
        depth: int | None = None,
        preview: int = 0,
        signatures: bool = True,
        line_numbers: bool = True,
        tokens: bool = False,
        symbol: str = "",
        diff: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        if not path:
            return ToolResult(error="No path provided")

        try:
            p = self._validate_path(path)

            # Directory mode
            is_dir = await asyncio.to_thread(p.is_dir)
            if is_dir:
                return await self._outline_directory(
                    p, depth=depth, tokens=tokens, diff=diff
                )

            # File mode
            is_file = await asyncio.to_thread(p.is_file)
            if not is_file:
                return ToolResult(error=f"File not found: {path}")

            # Size check
            file_size = await asyncio.to_thread(lambda: p.stat().st_size)
            if file_size > MAX_FILE_SIZE_BYTES:
                return ToolResult(
                    error=(
                        f"File too large ({file_size:,} bytes, "
                        f"max {MAX_FILE_SIZE_BYTES:,}): {path}"
                    )
                )

            # Detect language
            parser_key = _detect_language(p)
            if parser_key is None:
                supported = sorted(set(EXT_TO_PARSER.values()) | set(FILENAME_TO_PARSER.values()))
                return ToolResult(
                    output=f"No outline parser for file type: {p.suffix or p.name}\n"
                    f"Supported: {', '.join(supported)}"
                )

            parser = PARSERS.get(parser_key)
            if parser is None:
                return ToolResult(output=f"No outline parser for language: {parser_key}")

            # Read file
            lines = await asyncio.to_thread(_read_file_lines, p)

            # Parse
            max_depth = depth if depth is not None else 999
            entries = parser(lines, max_depth, signatures, preview)

            if not entries:
                return ToolResult(output=f"(No outline entries found in {p.name})")

            # Compute end_line for each entry
            _compute_end_lines(entries, len(lines))

            # Filtered read mode
            if symbol:
                return _extract_symbol(entries, lines, symbol, p.name)

            # Token estimates
            if tokens:
                _annotate_token_estimates(entries, lines)

            # Diff-aware markers
            if diff:
                changed_ranges = await asyncio.to_thread(_get_diff_ranges, p)
                if changed_ranges is not None:
                    _annotate_diff_markers(entries, changed_ranges)

            # Format output
            output = _format_outline(
                entries, line_numbers, p.name, parser_key, tokens, diff
            )
            return ToolResult(output=output)

        except (PathSecurityError, ValueError) as e:
            return ToolResult(error=str(e))
        except FileNotFoundError:
            return ToolResult(error=f"File not found: {path}")
        except PermissionError:
            return ToolResult(error=f"Permission denied: {path}")
        except UnicodeDecodeError:
            return ToolResult(error=f"File is not valid UTF-8 text: {path}")
        except Exception as e:
            return ToolResult(error=f"Error outlining file: {e}")

    async def _outline_directory(
        self,
        dir_path: Path,
        depth: int | None = None,
        tokens: bool = False,
        diff: bool = False,
    ) -> ToolResult:
        """Outline all supported files in a directory (non-recursive)."""
        try:
            entries_raw = sorted(dir_path.iterdir(), key=lambda p: p.name)
        except PermissionError:
            return ToolResult(error=f"Permission denied: {dir_path}")

        # Filter to supported files only
        file_paths: list[Path] = []
        for entry in entries_raw:
            if entry.name.startswith("."):
                continue
            if not entry.is_file():
                continue
            if _detect_language(entry) is None:
                continue
            file_paths.append(entry)
            if len(file_paths) >= _MAX_DIR_FILES:
                break

        if not file_paths:
            supported = sorted(set(EXT_TO_PARSER.values()))
            return ToolResult(
                output=f"No supported files found in {dir_path.name}/\n"
                f"Supported types: {', '.join(supported)}"
            )

        # Diff info for directory
        dir_diff_files: set[str] | None = None
        if diff:
            dir_diff_files = await asyncio.to_thread(_get_diff_files, dir_path)

        parts: list[str] = [f"# Directory outline: {dir_path.name}/", ""]
        total_bytes = 0

        for fp in file_paths:
            parser_key = _detect_language(fp)
            if parser_key is None:
                continue

            parser = PARSERS.get(parser_key)
            if parser is None:
                continue

            try:
                lines = await asyncio.to_thread(_read_file_lines, fp)
            except (UnicodeDecodeError, PermissionError):
                continue

            file_entries = parser(lines, depth or 1, True, 0)
            if not file_entries:
                continue

            if tokens:
                _compute_end_lines(file_entries, len(lines))
                _annotate_token_estimates(file_entries, lines)

            # File header
            diff_marker = ""
            if diff and dir_diff_files is not None and fp.name in dir_diff_files:
                diff_marker = " [CHANGED]"
            file_header = f"## {fp.name} ({parser_key}){diff_marker}"
            parts.append(file_header)

            # Top-level entries
            for entry in file_entries:
                if entry.depth > 0:
                    continue
                line_part = f"  L{entry.line:>5} {entry.kind}: "
                if entry.signature:
                    line_part += entry.signature
                else:
                    line_part += entry.name
                if tokens and entry.token_estimate > 0:
                    line_part += f"  (~{entry.token_estimate} tokens)"
                parts.append(line_part)

            parts.append("")

            section_text = "\n".join(parts[-len(file_entries) - 2:])
            total_bytes += len(section_text.encode("utf-8"))
            if total_bytes > _MAX_DIR_OUTPUT_BYTES:
                remaining = len(file_paths) - file_paths.index(fp) - 1
                parts.append(f"(truncated - {remaining} more files)")
                break

        return ToolResult(output="\n".join(parts))


# Factory
outline_factory = file_skill_factory(OutlineSkill)
