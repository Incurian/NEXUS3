# Plan: `outline` Tool

## Overview

**Current state:** NEXUS3 agents must use `read_file` (full content, high token cost) or `grep` (requires knowing what to search for) to understand file structure. There is no efficient way to get a structural overview of a file without reading its full content.

**Goal:** A new `outline` skill that returns the structural skeleton of files -- headings for markdown, class/function signatures for code, key hierarchies for data files. This acts as an "IDE outline view" for agents, enabling cheap structural awareness that helps agents decide what to read in detail.

**Key insight:** This fills the gap between `read_file` and `grep` in the agent's information-gathering workflow. An agent can `outline` a file to understand its structure (100-500 tokens), then use `read_file` with targeted `offset`/`limit` to read only the relevant sections (vs. 5,000-50,000 tokens for the full file).

**Estimated size:** ~1000-1400 lines of implementation + ~600 lines of tests.

---

## Scope

### Included

| Category | What |
|----------|------|
| **Core skill** | `outline` FileSkill with path validation, available at all permission levels |
| **Parameters** | `path` (required), `depth`, `preview`, `signatures`, `line_numbers`, `tokens`, `symbol`, `diff` |
| **Directory mode** | When `path` is a directory, return per-file top-level symbols |
| **Token estimates** | Optional `tokens=true` annotates each entry with approximate token count |
| **Filtered read** | `symbol` parameter reads the body of a specific class/function/heading |
| **Diff-aware** | `diff=true` marks sections with uncommitted git changes |
| **Markdown** | Heading hierarchy with optional preview lines |
| **Python** | Classes, methods, functions, decorators, module-level assignments, return types |
| **C/C++** | Functions, classes, structs, enums, namespaces, typedefs |
| **JavaScript/TypeScript** | Exports, classes, functions, interfaces, type aliases |
| **Rust** | Structs, enums, traits, impl blocks, functions |
| **Go** | Types, interfaces, functions |
| **JSON/YAML/TOML** | Key hierarchy to depth N |
| **HTML** | Element tree with id/class attributes |
| **CSS** | Selectors (rule blocks) |
| **SQL** | Tables, views, indexes |
| **Makefile** | Targets |
| **Dockerfile** | Stages (FROM lines) |
| **Fallback** | Unsupported file types get a graceful "no parser available" message |

### Deferred to Future

| Feature | Reason |
|---------|--------|
| Tree-sitter parsing | Regex handles 90% of cases; upgrade specific languages later if needed |

### Explicitly Excluded

| Feature | Reason |
|---------|--------|
| Binary file support | Not useful for agents (images, compiled code) |
| Syntax validation/error reporting | Outline is informational, not a linter |
| Language auto-detection by content | Extension-based detection is sufficient and reliable |

---

## Design Decisions

| Question | Decision | Rationale |
|----------|----------|-----------|
| Base class? | `FileSkill` | Needs path validation, read-only file access. Same as `read_file`, `tail`, `file_info` |
| Implementation approach? | Regex-based for v1 | Covers 90% of use cases. No new dependencies. Tree-sitter can be added per-language later |
| File type detection? | Extension-based, using `EXT_TO_LANG` mapping from `concat_files.py` | Already exists, proven pattern, easy to extend |
| Parser architecture? | Registry of parser functions keyed by language string | Clean separation, easy to add languages, testable in isolation |
| Output format? | Indented text with optional line numbers | Compact, human/LLM-readable, line numbers enable targeted `read_file` follow-up |
| Where to put code? | `nexus3/skill/builtin/outline.py` (single file) | Follows existing pattern (each skill = one file). Parsers are functions, not separate modules |
| Permission level? | Available at all levels including SANDBOXED | Read-only operation, same as `read_file`, `glob`, `grep` |
| Depth parameter semantics? | 1 = top-level only, 2 = top + nested, None = unlimited | Intuitive for all file types. Depth 1 on Python = classes and module-level functions. Depth 2 = methods inside classes |
| Preview parameter? | Lines of source after each outline entry | 0 = names/signatures only (cheapest), 1-3 = useful context, max 10 |
| Line numbers default? | On (`true`) | Primary use case is follow-up with `read_file(offset=N)` |
| Token estimation approach? | `SimpleTokenCounter.count()` on the raw text between entries | Uses existing infrastructure, no new dependencies, heuristic is good enough |
| Directory outline output? | Per-file top-level symbols, respecting gitignore | Mirrors `list_directory` but with structural content |
| Filtered read scope? | Find symbol by name, return raw lines from start to end of block | Simpler and more useful than returning an outline subtree |
| Diff-aware implementation? | Run `git diff --name-only` + `git diff -U0` to get changed line ranges, mark matching entries | Lightweight, reuses existing git infrastructure from `git_context.py` |

---

## Security Considerations

1. **Read-only**: The outline tool only reads files, never modifies them. Safe at all permission levels.
2. **Path validation**: Inherits `FileSkill._validate_path()` -- symlink resolution, allowed_paths enforcement, same as `read_file`.
3. **Size limits**: Use `_read_file_lines()` with a 50,000-line cap to prevent memory DoS on huge files. This is more generous than `read_file`'s `MAX_READ_LINES` (10,000) because outline only stores entries, not full content.
4. **JSON parsing**: Uses `json.loads()` on full content. For very large JSON files (>10MB), this could be expensive. Apply `MAX_FILE_SIZE_BYTES` check before parsing, same as `read_file`.
5. **Regex safety**: All regexes are pre-compiled constants with no user input in patterns. No ReDoS risk.
6. **Directory traversal**: Directory outline mode uses `os.listdir()` + path validation per file. Does not follow symlinks. Respects gitignore when available.
7. **Git subprocess**: Diff-aware mode calls `git diff` via `subprocess.run()` with timeout (same pattern as `git_context.py`). No user input in command arguments (only file path from validated path).
8. **Filtered read**: Returns raw file content (like `read_file`), subject to same `MAX_OUTPUT_BYTES` limit.

---

## Architecture

### File Layout

```
nexus3/skill/builtin/outline.py    # ~1000-1400 lines, single file
tests/unit/skill/test_outline.py   # ~500-600 lines
```

### Parser Registry Pattern

```python
# Type alias for parser functions
# Each parser takes (lines, depth, signatures, preview) and returns list[OutlineEntry]
OutlineParser = Callable[[list[str], int, bool, int], list[OutlineEntry]]

# Registry maps language names to parser functions
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
```

### Extension-to-Language Mapping

Reuse and extend the `EXT_TO_LANG` mapping from `concat_files.py`. For the outline tool, we need a separate mapping because:
1. Some extensions map to the same parser (e.g., `.c` and `.h` both use `parse_c_cpp`)
2. Filename-based detection needed for `Makefile`, `Dockerfile` (no extension)
3. Keep it self-contained in `outline.py` to avoid coupling

```python
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
```

---

## Implementation Details

### OutlineEntry Dataclass

```python
@dataclass
class OutlineEntry:
    """A single entry in a file outline."""
    line: int              # 1-indexed line number
    end_line: int = 0      # Last line of this block (0 = unknown, used by filtered read + token estimation)
    depth: int             # Nesting depth (0 = top-level)
    kind: str              # e.g., "class", "function", "method", "heading", "key"
    name: str              # The identifier/heading text
    signature: str = ""    # Full signature (for code), empty for non-code
    preview_lines: list[str] = field(default_factory=list)  # Source context lines
    token_estimate: int = 0  # Approximate tokens in this section (0 = not computed)
    has_diff: bool = False   # True if this section has uncommitted git changes
```

### Core Skill Class

```python
class OutlineSkill(FileSkill):
    """Skill that returns the structural outline of a file or directory.

    Returns headings for markdown, class/function signatures for code,
    key hierarchies for data files. Acts as an "IDE outline view" for
    agents, enabling cheap structural awareness without reading full content.

    When given a directory path, returns per-file top-level symbols.

    When symbol parameter is provided, returns the full body of that symbol
    (filtered read mode).

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
                    "description": "Show line numbers (for follow-up with read_file). Default: true",
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

            # Detect language from extension or filename
            parser_key = _detect_language(p)
            if parser_key is None:
                return ToolResult(
                    output=f"No outline parser for file type: {p.suffix or p.name}\n"
                    f"Supported: {', '.join(sorted(set(EXT_TO_PARSER.values()) | set(FILENAME_TO_PARSER.values())))}"
                )

            parser = PARSERS.get(parser_key)
            if parser is None:
                return ToolResult(
                    output=f"No outline parser for language: {parser_key}"
                )

            # Read file lines (with size limit)
            lines = await asyncio.to_thread(_read_file_lines, p)

            # Parse outline
            max_depth = depth if depth is not None else 999
            entries = parser(lines, max_depth, signatures, preview)

            if not entries:
                return ToolResult(output=f"(No outline entries found in {p.name})")

            # Compute end_line for each entry (needed by tokens, symbol, diff)
            _compute_end_lines(entries, len(lines))

            # Filtered read mode: return body of a specific symbol
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


# Factory for dependency injection
outline_factory = file_skill_factory(OutlineSkill)
```

### Helper Functions

```python
def _detect_language(p: Path) -> str | None:
    """Detect parser language from file extension or name."""
    # Check filename first (Makefile, Dockerfile)
    if p.name in FILENAME_TO_PARSER:
        return FILENAME_TO_PARSER[p.name]
    # Then check extension
    ext = p.suffix.lstrip(".")
    if ext:
        return EXT_TO_PARSER.get(ext)
    return None


def _read_file_lines(p: Path, max_lines: int = 50000) -> list[str]:
    """Read file lines with a safety limit."""
    lines: list[str] = []
    with open(p, encoding="utf-8", errors="replace") as f:
        for line in f:
            lines.append(line.rstrip("\n"))
            if len(lines) >= max_lines:
                break
    return lines


def _compute_end_lines(entries: list[OutlineEntry], total_lines: int) -> None:
    """Compute end_line for each entry based on the start of the next same-or-lower-depth entry.

    Mutates entries in place. Each entry's end_line is set to the line before
    the next entry at the same or lesser depth, or total_lines if it's the last.
    """
    for i, entry in enumerate(entries):
        # Find the next entry at same or lesser depth
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

        # Main line: kind and name/signature
        if entry.signature:
            main = f"{line_prefix}{indent}{entry.kind}: {entry.signature}"
        else:
            main = f"{line_prefix}{indent}{entry.kind}: {entry.name}"

        # Token annotation
        if show_tokens and entry.token_estimate > 0:
            main += f"  (~{entry.token_estimate} tokens)"

        # Diff marker
        if show_diff and entry.has_diff:
            main += "  [CHANGED]"

        parts.append(main)

        # Preview lines (indented further)
        if entry.preview_lines:
            preview_indent = " " * (len(line_prefix) + len(indent) + 2)
            for pl in entry.preview_lines:
                parts.append(f"{preview_indent}| {pl}")

    return "\n".join(parts)
```

### Parser Implementations (Key Examples)

#### Markdown Parser

```python
_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")

def parse_markdown(
    lines: list[str], max_depth: int, signatures: bool, preview: int
) -> list[OutlineEntry]:
    """Parse markdown headings."""
    entries: list[OutlineEntry] = []
    for i, line in enumerate(lines):
        m = _MD_HEADING_RE.match(line)
        if m:
            level = len(m.group(1))  # 1-6
            if level > max_depth:
                continue
            heading_text = m.group(2).strip()
            preview_lines = _get_preview(lines, i, preview)
            entries.append(OutlineEntry(
                line=i + 1,
                depth=level - 1,  # h1=depth 0, h2=depth 1, etc.
                kind=f"h{level}",
                name=heading_text,
                preview_lines=preview_lines,
            ))
    return entries
```

#### Python Parser

```python
_PY_CLASS_RE = re.compile(r"^(\s*)(class)\s+(\w+)([^:]*)?:")
_PY_FUNC_RE = re.compile(r"^(\s*)(async\s+def|def)\s+(\w+)\s*\(([^)]*)\)([^:]*)?:")
_PY_DECORATOR_RE = re.compile(r"^(\s*)@(\w[\w.]*)")
_PY_ASSIGN_RE = re.compile(r"^([A-Z][A-Z_0-9]*)\s*[:]?\s*=")  # Module-level constants

def parse_python(
    lines: list[str], max_depth: int, signatures: bool, preview: int
) -> list[OutlineEntry]:
    """Parse Python classes, functions, methods, decorators, module constants."""
    entries: list[OutlineEntry] = []
    indent_stack: list[int] = []  # Track indentation to compute depth
    pending_decorators: list[str] = []

    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(stripped)
        depth = _compute_depth(indent, indent_stack)

        if depth >= max_depth:
            # Still track decorators
            dm = _PY_DECORATOR_RE.match(line)
            if dm:
                pending_decorators.append(dm.group(2))
            continue

        # Decorators
        dm = _PY_DECORATOR_RE.match(line)
        if dm:
            pending_decorators.append(dm.group(2))
            continue

        # Class
        cm = _PY_CLASS_RE.match(line)
        if cm:
            class_indent, _, class_name, bases = cm.groups()
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
            indent_stack = _update_indent_stack(indent, indent_stack)
            pending_decorators = []
            continue

        # Function/method
        fm = _PY_FUNC_RE.match(line)
        if fm:
            func_indent, keyword, func_name, params, return_ann = fm.groups()
            is_method = depth > 0  # Nested inside a class
            kind = "method" if is_method else "function"
            if signatures:
                # Build full signature, possibly multi-line
                sig_line = line.strip()
                # Handle multi-line signatures
                if not sig_line.endswith(":"):
                    j = i + 1
                    while j < len(lines) and not lines[j].rstrip().endswith(":"):
                        sig_line += " " + lines[j].strip()
                        j += 1
                    if j < len(lines):
                        sig_line += " " + lines[j].strip()
                sig = sig_line.rstrip(":")
                if pending_decorators:
                    sig = " ".join(f"@{d}" for d in pending_decorators) + " " + sig
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
            indent_stack = _update_indent_stack(indent, indent_stack)
            pending_decorators = []
            continue

        # Module-level constants (depth 0 only)
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


def _compute_depth(indent: int, indent_stack: list[int]) -> int:
    """Compute nesting depth from indentation level."""
    # Pop items that are at the same or deeper indentation
    while indent_stack and indent_stack[-1] >= indent:
        indent_stack.pop()
    return len(indent_stack)


def _update_indent_stack(indent: int, indent_stack: list[int]) -> list[int]:
    """Update indent stack after a block-opening line."""
    while indent_stack and indent_stack[-1] >= indent:
        indent_stack.pop()
    indent_stack.append(indent)
    return indent_stack


def _get_preview(lines: list[str], entry_line: int, count: int) -> list[str]:
    """Get preview lines after an outline entry (skipping the entry itself)."""
    if count <= 0:
        return []
    start = entry_line + 1  # Skip the entry line itself
    end = min(start + count, len(lines))
    return [lines[j] for j in range(start, end)]
```

#### JSON Parser

```python
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
    _walk_json(data, entries, max_depth, depth=0, prefix="", lines=lines)
    return entries


def _walk_json(
    obj: Any,
    entries: list[OutlineEntry],
    max_depth: int,
    depth: int,
    prefix: str,
    lines: list[str],
) -> None:
    """Recursively walk JSON structure."""
    if depth >= max_depth:
        return
    if isinstance(obj, dict):
        for key in obj:
            # Find line number by searching for the key
            line_num = _find_json_key_line(lines, key, prefix)
            value = obj[key]
            value_type = _json_value_summary(value)
            entries.append(OutlineEntry(
                line=line_num,
                depth=depth,
                kind="key",
                name=key,
                signature=f"{key}: {value_type}" if value_type else "",
            ))
            if isinstance(value, (dict, list)):
                _walk_json(value, entries, max_depth, depth + 1, f"{prefix}.{key}", lines)
    elif isinstance(obj, list) and obj:
        # For arrays, just note the type and length
        pass  # Don't recurse into arrays by default


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
```

#### Other Parsers (Sketched)

The remaining parsers follow the same pattern. Key regexes for each:

**C/C++:**
```python
_C_FUNC_RE = re.compile(r"^(\w[\w\s*&:<>]*?)\s+(\w+)\s*\(([^)]*)\)\s*\{?")
_C_CLASS_RE = re.compile(r"^(class|struct)\s+(\w+)")
_C_ENUM_RE = re.compile(r"^enum\s+(class\s+)?(\w+)")
_C_NAMESPACE_RE = re.compile(r"^namespace\s+(\w+)")
_C_TYPEDEF_RE = re.compile(r"^typedef\s+.+\s+(\w+)\s*;")
```

**JavaScript/TypeScript:**
```python
_JS_FUNC_RE = re.compile(r"^(export\s+)?(async\s+)?function\s+(\w+)")
_JS_CLASS_RE = re.compile(r"^(export\s+)?(abstract\s+)?class\s+(\w+)")
_JS_CONST_RE = re.compile(r"^(export\s+)?(const|let|var)\s+(\w+)")
_JS_INTERFACE_RE = re.compile(r"^(export\s+)?interface\s+(\w+)")
_JS_TYPE_RE = re.compile(r"^(export\s+)?type\s+(\w+)")
_JS_ARROW_RE = re.compile(r"^(export\s+)?(const|let)\s+(\w+)\s*=\s*(async\s+)?\(")
```

**Rust:**
```python
_RS_FN_RE = re.compile(r"^(\s*)(pub\s+)?(async\s+)?fn\s+(\w+)")
_RS_STRUCT_RE = re.compile(r"^(\s*)(pub\s+)?struct\s+(\w+)")
_RS_ENUM_RE = re.compile(r"^(\s*)(pub\s+)?enum\s+(\w+)")
_RS_TRAIT_RE = re.compile(r"^(\s*)(pub\s+)?trait\s+(\w+)")
_RS_IMPL_RE = re.compile(r"^(\s*)impl\s+(?:<[^>]+>\s+)?(\w+)")
```

**Go:**
```python
_GO_FUNC_RE = re.compile(r"^func\s+(?:\([^)]+\)\s+)?(\w+)\s*\(")
_GO_TYPE_RE = re.compile(r"^type\s+(\w+)\s+(struct|interface)")
```

**YAML:**
```python
_YAML_KEY_RE = re.compile(r"^(\s*)([^\s#:][^:]*?):\s*(.*)")
```

**TOML:**
```python
_TOML_TABLE_RE = re.compile(r"^\[([^\]]+)\]")
_TOML_KEY_RE = re.compile(r"^(\w[\w.-]*)\s*=")
```

**HTML:**
```python
_HTML_TAG_RE = re.compile(r"^(\s*)<(\w+)([^>]*?)(/?)>")
# Extract id/class from attributes
```

**CSS:**
```python
_CSS_SELECTOR_RE = re.compile(r"^([^\s{@/][^{]*)\{")
_CSS_AT_RULE_RE = re.compile(r"^(@\w+[^{]*)\{")
```

**SQL:**
```python
_SQL_TABLE_RE = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\S+)", re.I)
_SQL_VIEW_RE = re.compile(r"CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+(\S+)", re.I)
_SQL_INDEX_RE = re.compile(r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(\S+)", re.I)
```

**Makefile:**
```python
_MAKE_TARGET_RE = re.compile(r"^([a-zA-Z_][\w.-]*):\s*")
```

**Dockerfile:**
```python
_DOCKER_FROM_RE = re.compile(r"^FROM\s+(\S+)(?:\s+AS\s+(\S+))?", re.I)
```

### Directory Outline Implementation

When `path` is a directory, the outline tool returns per-file top-level symbols. This provides a structural map of a codebase directory without reading any file fully.

```python
# Constants for directory outline mode
_MAX_DIR_FILES = 100        # Maximum files to outline in one call
_MAX_DIR_OUTPUT_BYTES = 50000  # Output size cap for directory mode

async def _outline_directory(
    self,
    dir_path: Path,
    depth: int | None = None,
    tokens: bool = False,
    diff: bool = False,
) -> ToolResult:
    """Outline all supported files in a directory (non-recursive).

    Returns per-file top-level symbols (depth=1 per file), sorted by filename.
    Skips files that don't have a parser, binary files, and hidden files.
    Respects .gitignore if available.
    """
    # List directory contents
    try:
        entries_raw = await asyncio.to_thread(sorted, dir_path.iterdir())
    except PermissionError:
        return ToolResult(error=f"Permission denied: {dir_path}")

    # Filter to supported files only
    file_paths: list[Path] = []
    for entry in entries_raw:
        if entry.name.startswith("."):
            continue  # Skip hidden files/dirs
        if not entry.is_file():
            continue
        if _detect_language(entry) is None:
            continue
        file_paths.append(entry)
        if len(file_paths) >= _MAX_DIR_FILES:
            break

    if not file_paths:
        return ToolResult(
            output=f"No supported files found in {dir_path.name}/\n"
            f"Supported extensions: {', '.join(sorted(set(EXT_TO_PARSER.values())))}"
        )

    # Get diff info for whole directory if requested
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

        # Parse top-level only (depth=1) for directory mode
        file_entries = parser(lines, depth or 1, True, 0)
        if not file_entries:
            continue

        # Compute end_lines for token estimates
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
                continue  # Only top-level for directory mode
            line_part = f"  L{entry.line:>5} {entry.kind}: "
            if entry.signature:
                line_part += entry.signature
            else:
                line_part += entry.name
            if tokens and entry.token_estimate > 0:
                line_part += f"  (~{entry.token_estimate} tokens)"
            parts.append(line_part)

        parts.append("")  # Blank line between files

        total_bytes += sum(len(p.encode("utf-8")) for p in parts[-len(file_entries) - 2:])
        if total_bytes > _MAX_DIR_OUTPUT_BYTES:
            parts.append(f"(truncated - {len(file_paths) - file_paths.index(fp) - 1} more files)")
            break

    return ToolResult(output="\n".join(parts))


def _get_diff_files(dir_path: Path) -> set[str] | None:
    """Get set of filenames with uncommitted changes in a directory.

    Returns None if not a git repo or git unavailable.
    """
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
        # Also include unstaged changes
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
```

### Token Estimation Implementation

Token estimates use the existing `SimpleTokenCounter` from `nexus3/context/token_counter.py`. Each entry's token count covers the raw text from its start line to its end line.

```python
from nexus3.context.token_counter import SimpleTokenCounter

_TOKEN_COUNTER = SimpleTokenCounter()


def _annotate_token_estimates(entries: list[OutlineEntry], lines: list[str]) -> None:
    """Annotate each entry with an approximate token count for its body.

    Mutates entries in place. Uses the text between entry.line and entry.end_line
    to estimate tokens.

    Args:
        entries: List of outline entries with end_line already computed.
        lines: Full file lines (0-indexed).
    """
    for entry in entries:
        if entry.end_line <= 0:
            continue
        # Extract raw text for this section (line numbers are 1-indexed)
        start_idx = entry.line - 1
        end_idx = min(entry.end_line, len(lines))
        section_text = "\n".join(lines[start_idx:end_idx])
        entry.token_estimate = _TOKEN_COUNTER.count(section_text)
```

### Filtered Read (Symbol Extraction) Implementation

The `symbol` parameter enables reading the full body of a specific class, function, or heading without knowing exact line numbers. The agent calls `outline path.py --symbol ClassName` and gets back the raw source lines for that symbol.

```python
from nexus3.core.constants import MAX_OUTPUT_BYTES


def _extract_symbol(
    entries: list[OutlineEntry],
    lines: list[str],
    symbol_name: str,
    filename: str,
) -> ToolResult:
    """Extract the full body of a named symbol from the file.

    Searches entries by name (case-sensitive). Returns the raw source lines
    from the symbol's start to its end_line.

    Args:
        entries: Parsed outline entries with end_line computed.
        lines: Full file lines (0-indexed).
        symbol_name: Name to search for (e.g., "MyClass", "my_function").
        filename: Original filename for error messages.

    Returns:
        ToolResult with the symbol's source code, or error if not found.
    """
    # Find matching entry (exact match first, then case-insensitive)
    match: OutlineEntry | None = None
    for entry in entries:
        if entry.name == symbol_name:
            match = entry
            break

    if match is None:
        # Try case-insensitive
        for entry in entries:
            if entry.name.lower() == symbol_name.lower():
                match = entry
                break

    if match is None:
        # List available symbols to help the agent
        available = [e.name for e in entries if e.depth == 0]
        if len(available) > 20:
            available = available[:20] + [f"... and {len(available) - 20} more"]
        return ToolResult(
            error=f"Symbol '{symbol_name}' not found in {filename}.\n"
            f"Available top-level symbols: {', '.join(available)}"
        )

    # Extract lines
    start_idx = match.line - 1  # Convert to 0-indexed
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
        body += f"\n(truncated at {MAX_OUTPUT_BYTES} bytes - use read_file with offset/limit for the rest)"

    return ToolResult(output=header + body)
```

### Diff-Aware Outline Implementation

The diff-aware mode marks outline entries whose line ranges overlap with uncommitted git changes. This helps agents focus on recently modified code.

```python
def _get_diff_ranges(file_path: Path) -> list[tuple[int, int]] | None:
    """Get line ranges with uncommitted changes for a file.

    Runs `git diff -U0` (staged + unstaged) and parses the @@ hunk headers
    to extract changed line ranges.

    Args:
        file_path: Absolute path to the file.

    Returns:
        List of (start_line, end_line) tuples (1-indexed, inclusive).
        Returns None if not in a git repo or git unavailable.
        Returns empty list if file has no changes.
    """
    cwd = str(file_path.parent)
    fname = file_path.name

    try:
        # Get both staged and unstaged changes
        # --no-ext-diff avoids external diff tools
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
            # Might not be tracked, try without HEAD
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

    # Parse @@ hunk headers: @@ -old_start,old_count +new_start,new_count @@
    hunk_re = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
    ranges: list[tuple[int, int]] = []

    for line in result.stdout.splitlines():
        m = hunk_re.match(line)
        if m:
            start = int(m.group(1))
            count = int(m.group(2)) if m.group(2) else 1
            if count == 0:
                continue  # Pure deletion, no lines in new file
            end = start + count - 1
            ranges.append((start, end))

    return ranges


def _annotate_diff_markers(
    entries: list[OutlineEntry],
    changed_ranges: list[tuple[int, int]],
) -> None:
    """Mark outline entries whose line ranges overlap with changed ranges.

    Mutates entries in place, setting has_diff=True for any entry whose
    [line, end_line] range overlaps with any changed range.

    Args:
        entries: List of outline entries with end_line computed.
        changed_ranges: List of (start, end) tuples from git diff.
    """
    for entry in entries:
        if entry.end_line <= 0:
            continue
        for change_start, change_end in changed_ranges:
            # Check for overlap: entry.line..entry.end_line overlaps change_start..change_end
            if entry.line <= change_end and entry.end_line >= change_start:
                entry.has_diff = True
                break
```

---

## Testing Strategy

### Unit Tests (`tests/unit/skill/test_outline.py`)

**Parser tests (isolated, no FileSkill infrastructure):**

| Test | What it verifies |
|------|-----------------|
| `test_parse_markdown_headings` | h1-h6 hierarchy, depth filtering |
| `test_parse_markdown_preview` | Preview lines after headings |
| `test_parse_python_classes_and_methods` | Class/method nesting, depth 1 vs 2 |
| `test_parse_python_decorators` | Decorators attached to functions/classes |
| `test_parse_python_module_constants` | `MY_CONST = value` at module level |
| `test_parse_python_async_functions` | `async def` detection |
| `test_parse_python_multiline_signature` | Signature spanning multiple lines |
| `test_parse_python_signatures_off` | `signatures=False` returns names only |
| `test_parse_json_hierarchy` | Nested keys with depth limit |
| `test_parse_json_value_summary` | Type annotations (dict, list, string, etc.) |
| `test_parse_yaml_keys` | Indentation-based hierarchy |
| `test_parse_toml_tables` | `[section]` and keys |
| `test_parse_javascript_exports` | `export function`, `export class`, arrow functions |
| `test_parse_typescript_interfaces` | `interface` and `type` aliases |
| `test_parse_rust_impl_blocks` | `impl Trait for Struct` |
| `test_parse_go_types` | `type X struct`, `func (r *X) Method()` |
| `test_parse_c_functions` | Return type + name + params |
| `test_parse_html_elements` | Tag tree with id/class |
| `test_parse_css_selectors` | Rule blocks, @media |
| `test_parse_sql_tables` | CREATE TABLE/VIEW/INDEX |
| `test_parse_makefile_targets` | Target names |
| `test_parse_dockerfile_stages` | FROM lines with AS aliases |
| `test_format_outline_with_line_numbers` | Output format correctness |
| `test_format_outline_without_line_numbers` | Output without line prefix |
| `test_detect_language_by_extension` | Extension mapping |
| `test_detect_language_by_filename` | Makefile, Dockerfile |
| `test_detect_language_unknown` | Returns None for unknown |

**Skill-level tests (with ServiceContainer):**

| Test | What it verifies |
|------|-----------------|
| `test_outline_skill_empty_path` | Returns error for empty path |
| `test_outline_skill_nonexistent_file` | Returns error for missing file |
| `test_outline_skill_directory` | Returns per-file outlines for directory |
| `test_outline_skill_unsupported_extension` | Returns informative message |
| `test_outline_skill_python_file` | End-to-end with real Python file |
| `test_outline_skill_markdown_file` | End-to-end with real markdown file |
| `test_outline_skill_json_file` | End-to-end with real JSON file |
| `test_outline_skill_path_validation` | Respects sandboxed allowed_paths |
| `test_outline_skill_binary_file` | Handles UnicodeDecodeError gracefully |
| `test_outline_skill_depth_parameter` | Depth filtering works end-to-end |
| `test_outline_skill_preview_parameter` | Preview lines in output |

**Token estimation tests:**

| Test | What it verifies |
|------|-----------------|
| `test_compute_end_lines_sequential` | End lines computed correctly for sequential entries |
| `test_compute_end_lines_nested` | End lines respect depth for nested entries |
| `test_annotate_token_estimates` | Token counts are positive, proportional to section size |
| `test_token_estimates_in_output` | `(~N tokens)` appears in formatted output when `tokens=true` |
| `test_token_estimates_not_shown_by_default` | No token info when `tokens=false` |

**Filtered read (symbol extraction) tests:**

| Test | What it verifies |
|------|-----------------|
| `test_extract_symbol_exact_match` | Finds symbol by exact name |
| `test_extract_symbol_case_insensitive` | Falls back to case-insensitive match |
| `test_extract_symbol_not_found` | Returns error with list of available symbols |
| `test_extract_symbol_returns_body` | Output includes numbered source lines |
| `test_extract_symbol_truncation` | Large symbol bodies are truncated at MAX_OUTPUT_BYTES |
| `test_outline_skill_symbol_param` | End-to-end: `outline file.py --symbol MyClass` |

**Directory outline tests:**

| Test | What it verifies |
|------|-----------------|
| `test_outline_directory_lists_files` | Returns per-file top-level symbols |
| `test_outline_directory_skips_hidden` | Hidden files (`.foo`) are excluded |
| `test_outline_directory_skips_unsupported` | Files without parsers are skipped |
| `test_outline_directory_empty` | Returns informative message for empty/unsupported dir |
| `test_outline_directory_max_files` | Stops at _MAX_DIR_FILES limit |
| `test_outline_directory_with_tokens` | Token estimates shown in directory mode |

**Diff-aware outline tests:**

| Test | What it verifies |
|------|-----------------|
| `test_get_diff_ranges_no_changes` | Returns empty list for clean file |
| `test_get_diff_ranges_with_changes` | Correctly parses hunk headers |
| `test_get_diff_ranges_not_git_repo` | Returns None outside git repo |
| `test_annotate_diff_markers_overlap` | Marks entry when change range overlaps entry range |
| `test_annotate_diff_markers_no_overlap` | Does not mark entry for non-overlapping changes |
| `test_diff_marker_in_output` | `[CHANGED]` appears in formatted output when `diff=true` |
| `test_diff_not_shown_by_default` | No markers when `diff=false` |

### Integration Tests

Outline is a read-only skill. The unit tests with real files (via `tmp_path`) are sufficient for most features. No separate integration test file needed -- the skill-level unit tests already create real files and execute the full skill pipeline including path validation.

For diff-aware tests, a small integration test using a real git repo (via `tmp_path` + `git init`) verifies end-to-end behavior.

### Live Testing Plan

```bash
# Start NEXUS3 REPL
nexus3 --fresh

# Test file outline with various file types
> outline nexus3/skill/base.py
> outline nexus3/skill/base.py --depth 1
> outline CLAUDE.md
> outline CLAUDE.md --preview 2
> outline nexus3/config/schema.py --signatures false
> outline package.json  # or any JSON file

# Test directory outline
> outline nexus3/skill/builtin/
> outline nexus3/core/

# Test token estimates
> outline nexus3/skill/base.py --tokens true
> outline nexus3/skill/builtin/ --tokens true

# Test filtered read
> outline nexus3/skill/base.py --symbol FileSkill
> outline nexus3/skill/base.py --symbol execute
> outline CLAUDE.md --symbol "Architecture"

# Test diff-aware mode
> outline nexus3/skill/base.py --diff true
> outline nexus3/skill/builtin/ --diff true

# Test error cases
> outline nonexistent.py
> outline image.png  # unsupported file type

# Verify tool appears in agent tool list and works in conversation flow
```

---

## Output Examples

### Python (depth=2, signatures=true, line_numbers=true)

```
# Outline: base.py (python)

L   40 function: handle_file_errors(func: Callable[..., Coroutine[Any, Any, ToolResult]]) -> Callable[..., Coroutine[Any, Any, ToolResult]]
L   70 function: validate_skill_parameters(strict: bool = False) -> Callable[...]
L  268 class: Skill (Protocol)
L  306   method: name(self) -> str
L  315   method: description(self) -> str
L  348   method: execute(self, **kwargs: Any) -> ToolResult
L  362 class: BaseSkill(ABC)
L  423   method: execute(self, **kwargs: Any) -> ToolResult
L  439 class: FileSkill(ABC)
L  507   method: _validate_path(self, path: str) -> Path
L  554   method: execute(self, **kwargs: Any) -> ToolResult
L  564 function: file_skill_factory(cls: type[_T]) -> Callable[[ServiceContainer], _T]
```

### Markdown (depth=2, line_numbers=true)

```
# Outline: CLAUDE.md (markdown)

L    1 h1: CLAUDE.md
L   10 h2: Project Overview
L   18 h2: Architecture
L   20 h3: Module Structure
L   50 h3: Key Interfaces
L   80 h3: Skill Type Hierarchy
L  150 h2: CLI Modes
```

### JSON (depth=2, line_numbers=true)

```
# Outline: config.json (json)

L    2 key: provider: {3 keys}
L    3   key: type: "openrouter"
L    4   key: model: "anthropic/claude-sonnet-4"
L    5   key: api_key_env: "OPENROUTER_API_KEY"
L    7 key: models: {4 keys}
L   15 key: server: {3 keys}
L   20 key: compaction: {5 keys}
```

### Python with token estimates (tokens=true)

```
# Outline: base.py (python)

L   40 function: handle_file_errors(func: ...)  (~75 tokens)
L   70 function: validate_skill_parameters(...)  (~480 tokens)
L  268 class: Skill (Protocol)  (~230 tokens)
L  362 class: BaseSkill(ABC)  (~190 tokens)
L  439 class: FileSkill(ABC)  (~310 tokens)
L  564 function: file_skill_factory(...)  (~120 tokens)
```

### Python with diff markers (diff=true)

```
# Outline: session.py (python)

L   15 class: SessionManager
L   42   method: __init__(self, config: Config)
L   78   method: save(self, path: Path)  [CHANGED]
L  120   method: load(self, path: Path)
L  180   method: compact(self)  [CHANGED]
L  250 function: create_session(config: Config) -> SessionManager
```

### Filtered read (symbol="FileSkill")

```
# class: FileSkill (base.py, L439-L562)

439: class FileSkill(ABC):
440:     """Abstract base class for skills that operate on files.
441:
442:     Provides path validation, symlink resolution, and allowed_paths
443:     enforcement. Subclasses implement execute() with validated paths.
444:     """
445:
446:     def __init__(self, container: ServiceContainer) -> None:
...
562:         return result
```

### Directory outline

```
# Directory outline: builtin/

## read_file.py (python)
  L   69 class: ReadFileSkill
  L  165 function: read_file_factory

## write_file.py (python)
  L   18 class: WriteFileSkill
  L  120 function: write_file_factory

## edit_file.py (python)
  L   22 class: EditFileSkill
  L  250 function: edit_file_factory

## glob_search.py (python)
  L   15 class: GlobSkill
  L   98 function: glob_factory
```

---

## Open Questions

None -- all design decisions resolved in the discussion with the user.

---

## Codebase Validation Notes

*Validated against NEXUS3 codebase on 2026-02-11*

### Confirmed Patterns

| Aspect | Status | Notes |
|--------|--------|-------|
| `FileSkill` base class | Confirmed | In `nexus3/skill/base.py`, line 439. Has `_validate_path()`, `_allowed_paths`, `_services` |
| `file_skill_factory` function | Confirmed | In `nexus3/skill/base.py`, line 564. Called as `factory_var = file_skill_factory(SkillClass)` at module level (NOT as class decorator) |
| `ToolResult(output=...)` / `ToolResult(error=...)` | Confirmed | Frozen dataclass in `nexus3/core/types.py`, line 57. `output: str = ""`, `error: str = ""` |
| Registration pattern | Confirmed | `nexus3/skill/builtin/registration.py` imports factory, calls `registry.register("name", factory)` |
| Skill parameter schema | Confirmed | JSON Schema with `type: "object"`, `properties`, `required` |
| Error handling pattern | Confirmed | `except (PathSecurityError, ValueError) as e: return ToolResult(error=str(e))` |
| `asyncio.to_thread` for blocking I/O | Confirmed | Used in `read_file.py`, `tail.py`, `file_info.py`, `glob_search.py` |
| `EXT_TO_LANG` mapping | Confirmed | In `nexus3/skill/builtin/concat_files.py`, line 70. Comprehensive mapping |
| File read with `encoding="utf-8", errors="replace"` | Confirmed | Consistent across all file-reading skills |
| MAX_FILE_SIZE_BYTES check | Confirmed | `10 * 1024 * 1024` (10MB) in `nexus3/core/constants.py` |
| MAX_OUTPUT_BYTES | Confirmed | In `nexus3/core/constants.py`, used by `read_file.py` for output truncation |
| Test fixture pattern | Confirmed | `tmp_path` + `ServiceContainer` with permissions, see `tests/integration/test_file_editing_skills.py` |
| `SimpleTokenCounter` | Confirmed | In `nexus3/context/token_counter.py`, line 22. Has `count(text: str) -> int` with `CHARS_PER_TOKEN = 4` heuristic |
| Git subprocess pattern | Confirmed | In `nexus3/context/git_context.py`. Uses `subprocess.run()` with `timeout=5`, `encoding="utf-8"`, `errors="replace"` |
| `_run_git()` helper | Confirmed | In `nexus3/context/git_context.py`, line 49. Returns `str | None` |

### Key Compatibility Notes

1. **Registration in `registration.py`**: Must add `from nexus3.skill.builtin.outline import outline_factory` and `registry.register("outline", outline_factory)` in the "File operations (read-only)" section.

2. **NEXUS-DEFAULT.md tool table**: Must add `outline` to the "File Operations (Read)" table.

3. **CLAUDE.md Built-in Skills table**: Must add `outline` row.

4. **No permission changes needed**: Read-only file skills have no restrictions in any preset. The skill will be available at SANDBOXED, TRUSTED, and YOLO levels without any changes to `nexus3/core/presets.py`.

5. **The `file_skill_factory` function** is called at module level as `outline_factory = file_skill_factory(OutlineSkill)`, NOT used as a `@file_skill_factory` class decorator. Every builtin skill follows this pattern (e.g., `read_file_factory = file_skill_factory(ReadFileSkill)`). The factory wraps `execute` with parameter validation, so the skill class should NOT also use `@validate_skill_parameters()` decorator.

6. **SimpleTokenCounter import**: Available from `nexus3.context.token_counter`. No new dependencies needed for token estimation.

7. **Git diff integration**: The `subprocess.run()` + timeout pattern from `git_context.py` is the established pattern. Do not import `_run_git()` from there (private function); replicate the pattern locally in `outline.py`.

### Corrections Applied

1. **`file_skill_factory` usage**: The plan originally used `@file_skill_factory` as a class decorator AND `outline_factory = file_skill_factory(OutlineSkill)` at module level, which would double-wrap. Fixed to match the actual codebase pattern: no decorator, only `outline_factory = file_skill_factory(OutlineSkill)` at module level. All 20+ builtin FileSkill implementations use this pattern consistently.

---

## Implementation Checklist

### Phase 1: Core Infrastructure (Required First)

- [ ] **P1.1** Create `nexus3/skill/builtin/outline.py` with imports, constants (`EXT_TO_PARSER`, `FILENAME_TO_PARSER`, `PARSERS` dict), and `OutlineEntry` dataclass
- [ ] **P1.2** Implement `_detect_language()`, `_read_file_lines()`, `_get_preview()`, `_compute_end_lines()`, `_format_outline()` helper functions
- [ ] **P1.3** Implement `OutlineSkill` class (FileSkill subclass) with `name`, `description`, `parameters`, `execute` method, and `outline_factory` at bottom
- [ ] **P1.4** Register the skill: add import and `registry.register("outline", outline_factory)` in `nexus3/skill/builtin/registration.py`

### Phase 2: Parsers - High Priority Languages (After Phase 1)

- [ ] **P2.1** Implement `parse_markdown` (can parallel with P2.2-P2.4)
- [ ] **P2.2** Implement `parse_python` with `_compute_depth`, `_update_indent_stack` helpers (can parallel with P2.1, P2.3-P2.4)
- [ ] **P2.3** Implement `parse_json` with `_walk_json`, `_json_value_summary`, `_find_json_key_line` helpers (can parallel with P2.1-P2.2, P2.4)
- [ ] **P2.4** Implement `parse_yaml` and `parse_toml` (can parallel with P2.1-P2.3)

### Phase 3: Parsers - Systems Languages (After Phase 1, can parallel with Phase 2)

- [ ] **P3.1** Implement `parse_javascript` and `parse_typescript` (can parallel with P3.2-P3.4)
- [ ] **P3.2** Implement `parse_rust` (can parallel with P3.1, P3.3-P3.4)
- [ ] **P3.3** Implement `parse_c_cpp` (can parallel with P3.1-P3.2, P3.4)
- [ ] **P3.4** Implement `parse_go` (can parallel with P3.1-P3.3)

### Phase 4: Parsers - Remaining File Types (After Phase 1, can parallel with Phases 2-3)

- [ ] **P4.1** Implement `parse_html` (can parallel with P4.2-P4.4)
- [ ] **P4.2** Implement `parse_css` (can parallel with P4.1, P4.3-P4.4)
- [ ] **P4.3** Implement `parse_sql` (can parallel with P4.1-P4.2, P4.4)
- [ ] **P4.4** Implement `parse_makefile` and `parse_dockerfile` (can parallel with P4.1-P4.3)

### Phase 5: Unit Tests - Core + Parsers (After Phases 2-4)

- [ ] **P5.1** Create `tests/unit/skill/test_outline.py` with test fixtures (ServiceContainer, tmp_path helpers)
- [ ] **P5.2** Parser unit tests for markdown, Python, JSON, YAML, TOML
- [ ] **P5.3** Parser unit tests for JavaScript, TypeScript, Rust, Go, C/C++
- [ ] **P5.4** Parser unit tests for HTML, CSS, SQL, Makefile, Dockerfile
- [ ] **P5.5** Skill-level tests (empty path, nonexistent file, unsupported extension, path validation, depth/preview parameters)
- [ ] **P5.6** Output format tests (line numbers on/off, signatures on/off)

### Phase 6: Lint and Test Verification (After Phase 5)

- [ ] **P6.1** Run `ruff check nexus3/skill/builtin/outline.py` -- zero errors
- [ ] **P6.2** Run `pytest tests/unit/skill/test_outline.py -v` -- all pass
- [ ] **P6.3** Run `pytest tests/ -v` -- no regressions (all 3489+ tests still pass)

### Phase 7: Token Estimation (After Phase 6)

- [ ] **P7.1** Implement `_annotate_token_estimates()` in `outline.py` using `SimpleTokenCounter` (requires P1.2 for `_compute_end_lines`)
- [ ] **P7.2** Update `_format_outline()` to include `(~N tokens)` annotation when `tokens=true`
- [ ] **P7.3** Wire `tokens` parameter through `execute()` method
- [ ] **P7.4** Add unit tests for token estimation (`test_compute_end_lines_*`, `test_annotate_token_estimates`, `test_token_estimates_in_output`, `test_token_estimates_not_shown_by_default`)

### Phase 8: Filtered Read / Symbol Extraction (After Phase 6, can parallel with Phase 7)

- [ ] **P8.1** Implement `_extract_symbol()` in `outline.py` with exact and case-insensitive name matching
- [ ] **P8.2** Wire `symbol` parameter through `execute()` method (early return before formatting)
- [ ] **P8.3** Add unit tests for filtered read (`test_extract_symbol_exact_match`, `test_extract_symbol_case_insensitive`, `test_extract_symbol_not_found`, `test_extract_symbol_returns_body`, `test_extract_symbol_truncation`, `test_outline_skill_symbol_param`)

### Phase 9: Directory Outline (After Phase 6, can parallel with Phases 7-8)

- [ ] **P9.1** Implement `_outline_directory()` method on `OutlineSkill` and `_get_diff_files()` helper
- [ ] **P9.2** Update `execute()` to detect directory path and delegate to `_outline_directory()`
- [ ] **P9.3** Add unit tests for directory outline (`test_outline_directory_lists_files`, `test_outline_directory_skips_hidden`, `test_outline_directory_skips_unsupported`, `test_outline_directory_empty`, `test_outline_directory_max_files`, `test_outline_directory_with_tokens`)

### Phase 10: Diff-Aware Outline (After Phase 6, can parallel with Phases 7-9)

- [ ] **P10.1** Implement `_get_diff_ranges()` in `outline.py` using `subprocess.run()` + hunk header parsing
- [ ] **P10.2** Implement `_annotate_diff_markers()` for range overlap detection
- [ ] **P10.3** Update `_format_outline()` to include `[CHANGED]` markers when `diff=true`
- [ ] **P10.4** Wire `diff` parameter through `execute()` method
- [ ] **P10.5** Add unit tests for diff-aware outline (`test_get_diff_ranges_*`, `test_annotate_diff_markers_*`, `test_diff_marker_in_output`, `test_diff_not_shown_by_default`)
- [ ] **P10.6** Add integration test with real git repo (via `tmp_path` + `git init` + file modification)

### Phase 11: Lint and Full Test Pass (After Phases 7-10)

- [ ] **P11.1** Run `ruff check nexus3/skill/builtin/outline.py` -- zero errors
- [ ] **P11.2** Run `pytest tests/unit/skill/test_outline.py -v` -- all pass (including new extension tests)
- [ ] **P11.3** Run `pytest tests/ -v` -- no regressions

### Phase 12: Documentation (After Phase 11)

- [ ] **P12.1** Update `CLAUDE.md` Built-in Skills table: add `outline` row with all parameters (`path`, `depth`, `preview`, `signatures`, `line_numbers`, `tokens`, `symbol`, `diff`) and description
- [ ] **P12.2** Update `nexus3/defaults/NEXUS-DEFAULT.md` "File Operations (Read)" table: add `outline` row with full parameter documentation
- [ ] **P12.3** Update `nexus3/skill/README.md` if it lists all skills (verify first)

### Phase 13: Live Testing (After Phase 12)

- [ ] **P13.1** Start NEXUS3 REPL with `nexus3 --fresh`
- [ ] **P13.2** Test `outline` on Python files in the codebase (e.g., `nexus3/skill/base.py`)
- [ ] **P13.3** Test `outline` on CLAUDE.md (markdown)
- [ ] **P13.4** Test `outline` on JSON config files
- [ ] **P13.5** Test depth, preview, signatures, line_numbers parameters
- [ ] **P13.6** Test `outline` on a directory (e.g., `nexus3/core/`)
- [ ] **P13.7** Test `outline` with `--tokens true` on files and directories
- [ ] **P13.8** Test `outline` with `--symbol ClassName` on Python files
- [ ] **P13.9** Test `outline` with `--symbol "Architecture"` on CLAUDE.md
- [ ] **P13.10** Test `outline` with `--diff true` (modify a file first, then outline)
- [ ] **P13.11** Test on unsupported file type (e.g., `.png`) -- verify graceful message
- [ ] **P13.12** Verify the tool appears in agent tool list and works in conversation flow

---

## Effort Estimate

| Phase | Description | LOC |
|-------|-------------|-----|
| 1 | Core infrastructure (skill class, helpers) | ~150 |
| 2 | High-priority parsers (md, py, json, yaml, toml) | ~200 |
| 3 | Systems language parsers (js/ts, rust, c/cpp, go) | ~120 |
| 4 | Remaining parsers (html, css, sql, make, docker) | ~80 |
| 5-6 | Unit tests for core + parsers | ~300 |
| 7 | Token estimation | ~40 |
| 8 | Filtered read / symbol extraction | ~80 |
| 9 | Directory outline | ~100 |
| 10 | Diff-aware outline | ~80 |
| 11 | Lint/test verification | ~0 |
| 12 | Documentation | ~20 |
| 13 | Live testing | ~0 |
| Tests 7-10 | Additional unit tests for extensions | ~200 |
| **Total** | | **~1370 LOC** |

---

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Regex parsers miss edge cases (nested strings, multiline) | Accept 90% accuracy for v1. Users can always `read_file` for exact content. Log "no entries found" case clearly |
| Python indentation tracking gets complex | Keep `_compute_depth` simple (indent-stack approach). Don't try to handle tabs vs spaces mixing -- use indent character count |
| JSON/YAML parsing could be slow on huge files | Apply `MAX_FILE_SIZE_BYTES` check before parsing. 10MB JSON parse is <1s on modern hardware |
| Large number of parsers in one file (~1000+ lines) | Manageable since each parser is a standalone function. If it grows beyond 1400 lines, split into `outline_parsers.py` |
| C/C++ regex misidentifies macros as functions | Accept some false positives. Macros like `#define FOO(x)` can be filtered by checking for `#` prefix |
| `_compute_end_lines` inaccurate for interleaved depth levels | End-line is approximate (next same-or-lower-depth entry). Accurate enough for token estimates and filtered read. Worst case: includes trailing blank lines or comments |
| Directory outline on large directories is slow | Capped at `_MAX_DIR_FILES` (100 files). Each file only parsed to depth 1. Total output capped at `_MAX_DIR_OUTPUT_BYTES` |
| Git subprocess calls add latency when `diff=true` | Single `git diff -U0` call (fast, < 100ms). Timeout at 5 seconds. Returns `None` gracefully on failure |
| Token estimates are approximate | `SimpleTokenCounter` uses 4 chars/token heuristic. Good enough for "is this section 50 tokens or 500 tokens?" decisions. Documented as approximate |

---

## Quick Reference: File Locations

| Component | File Path |
|-----------|-----------|
| Outline skill implementation | `nexus3/skill/builtin/outline.py` (new) |
| Skill registration | `nexus3/skill/builtin/registration.py` (modify) |
| FileSkill base class | `nexus3/skill/base.py` (reference) |
| Tool documentation (agent-facing) | `nexus3/defaults/NEXUS-DEFAULT.md` (modify) |
| User documentation | `CLAUDE.md` (modify) |
| Unit tests | `tests/unit/skill/test_outline.py` (new) |
| SimpleTokenCounter | `nexus3/context/token_counter.py` (reference) |
| Git context patterns | `nexus3/context/git_context.py` (reference) |
| Core constants | `nexus3/core/constants.py` (reference for MAX_FILE_SIZE_BYTES, MAX_OUTPUT_BYTES) |
| Reference: read_file skill | `nexus3/skill/builtin/read_file.py` (pattern) |
| Reference: glob skill | `nexus3/skill/builtin/glob_search.py` (pattern) |
| Reference: concat_files EXT_TO_LANG | `nexus3/skill/builtin/concat_files.py` (reference) |
| Reference: list_directory skill | `nexus3/skill/builtin/list_directory.py` (pattern for directory mode) |

---

### Critical Files for Implementation
- `/home/inc/repos/NEXUS3/nexus3/skill/builtin/outline.py` - New file: all skill logic, parsers, and extension features (primary implementation target)
- `/home/inc/repos/NEXUS3/nexus3/skill/builtin/registration.py` - Add import and register call for the new outline skill
- `/home/inc/repos/NEXUS3/nexus3/skill/base.py` - FileSkill base class and file_skill_factory pattern to follow
- `/home/inc/repos/NEXUS3/nexus3/skill/builtin/read_file.py` - Reference pattern for a read-only FileSkill (error handling, asyncio.to_thread, size limits)
- `/home/inc/repos/NEXUS3/nexus3/context/token_counter.py` - SimpleTokenCounter for token estimation feature
- `/home/inc/repos/NEXUS3/nexus3/context/git_context.py` - Git subprocess pattern for diff-aware feature
- `/home/inc/repos/NEXUS3/tests/unit/skill/test_outline.py` - New file: comprehensive unit tests for all parsers, skill-level behavior, and extension features
