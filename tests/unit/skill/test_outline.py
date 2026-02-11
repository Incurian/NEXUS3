"""Tests for outline skill."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from nexus3.skill.builtin.outline import (
    EXT_TO_PARSER,
    FILENAME_TO_PARSER,
    PARSERS,
    OutlineEntry,
    _annotate_diff_markers,
    _annotate_token_estimates,
    _compute_end_lines,
    _detect_language,
    _extract_symbol,
    _format_outline,
    _get_diff_ranges,
    _get_preview,
    _read_file_lines,
    outline_factory,
    parse_c_cpp,
    parse_css,
    parse_dockerfile,
    parse_go,
    parse_html,
    parse_javascript,
    parse_json,
    parse_makefile,
    parse_markdown,
    parse_python,
    parse_rust,
    parse_sql,
    parse_toml,
    parse_typescript,
    parse_yaml,
)
from nexus3.skill.services import ServiceContainer


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def services(tmp_path):
    """Create ServiceContainer with tmp_path as cwd."""
    services = ServiceContainer()
    services.register("cwd", str(tmp_path))
    return services


@pytest.fixture
def skill(services):
    """Create outline skill instance."""
    return outline_factory(services)


# =============================================================================
# Helper Function Tests
# =============================================================================


class TestDetectLanguage:
    def test_python_extension(self):
        assert _detect_language(Path("foo.py")) == "python"

    def test_pyi_extension(self):
        assert _detect_language(Path("foo.pyi")) == "python"

    def test_javascript_extension(self):
        assert _detect_language(Path("foo.js")) == "javascript"

    def test_typescript_extension(self):
        assert _detect_language(Path("foo.ts")) == "typescript"

    def test_tsx_extension(self):
        assert _detect_language(Path("foo.tsx")) == "typescript"

    def test_rust_extension(self):
        assert _detect_language(Path("foo.rs")) == "rust"

    def test_go_extension(self):
        assert _detect_language(Path("foo.go")) == "go"

    def test_c_extension(self):
        assert _detect_language(Path("foo.c")) == "c"

    def test_cpp_extension(self):
        assert _detect_language(Path("foo.cpp")) == "cpp"

    def test_json_extension(self):
        assert _detect_language(Path("foo.json")) == "json"

    def test_yaml_extension(self):
        assert _detect_language(Path("foo.yaml")) == "yaml"

    def test_yml_extension(self):
        assert _detect_language(Path("foo.yml")) == "yaml"

    def test_toml_extension(self):
        assert _detect_language(Path("foo.toml")) == "toml"

    def test_markdown_extension(self):
        assert _detect_language(Path("foo.md")) == "markdown"

    def test_html_extension(self):
        assert _detect_language(Path("foo.html")) == "html"

    def test_css_extension(self):
        assert _detect_language(Path("foo.css")) == "css"

    def test_sql_extension(self):
        assert _detect_language(Path("foo.sql")) == "sql"

    def test_makefile_by_name(self):
        assert _detect_language(Path("Makefile")) == "makefile"

    def test_dockerfile_by_name(self):
        assert _detect_language(Path("Dockerfile")) == "dockerfile"

    def test_unknown_returns_none(self):
        assert _detect_language(Path("foo.xyz")) is None

    def test_no_extension_no_name_match(self):
        assert _detect_language(Path("random_file")) is None

    def test_filename_takes_priority(self):
        # Makefile has no extension but should be detected by name
        assert _detect_language(Path("Makefile")) == "makefile"


class TestReadFileLines:
    def test_reads_all_lines(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("line1\nline2\nline3\n")
        lines = _read_file_lines(f)
        assert lines == ["line1", "line2", "line3"]

    def test_respects_max_lines(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("\n".join(f"line{i}" for i in range(100)))
        lines = _read_file_lines(f, max_lines=10)
        assert len(lines) == 10

    def test_strips_newlines(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello\nworld\n")
        lines = _read_file_lines(f)
        assert lines[0] == "hello"
        assert lines[1] == "world"


class TestGetPreview:
    def test_no_preview(self):
        assert _get_preview(["a", "b", "c"], 0, 0) == []

    def test_one_preview_line(self):
        assert _get_preview(["a", "b", "c"], 0, 1) == ["b"]

    def test_preview_at_end(self):
        assert _get_preview(["a", "b"], 1, 3) == []

    def test_preview_clipped(self):
        lines = ["a", "b", "c"]
        assert _get_preview(lines, 1, 5) == ["c"]


class TestComputeEndLines:
    def test_sequential_entries(self):
        entries = [
            OutlineEntry(line=1, depth=0, kind="f", name="a"),
            OutlineEntry(line=10, depth=0, kind="f", name="b"),
            OutlineEntry(line=20, depth=0, kind="f", name="c"),
        ]
        _compute_end_lines(entries, 30)
        assert entries[0].end_line == 9
        assert entries[1].end_line == 19
        assert entries[2].end_line == 30

    def test_nested_entries(self):
        entries = [
            OutlineEntry(line=1, depth=0, kind="class", name="A"),
            OutlineEntry(line=5, depth=1, kind="method", name="m1"),
            OutlineEntry(line=10, depth=1, kind="method", name="m2"),
            OutlineEntry(line=20, depth=0, kind="function", name="f"),
        ]
        _compute_end_lines(entries, 30)
        assert entries[0].end_line == 19  # Class ends before function
        assert entries[1].end_line == 9   # m1 ends before m2
        assert entries[2].end_line == 19  # m2 ends before function
        assert entries[3].end_line == 30  # Last entry goes to end

    def test_single_entry(self):
        entries = [OutlineEntry(line=1, depth=0, kind="f", name="a")]
        _compute_end_lines(entries, 50)
        assert entries[0].end_line == 50


class TestFormatOutline:
    def test_basic_format_with_line_numbers(self):
        entries = [
            OutlineEntry(
                line=10, depth=0, kind="function", name="foo",
                signature="def foo(x: int) -> str",
            ),
        ]
        output = _format_outline(entries, True, "test.py", "python")
        assert "# Outline: test.py (python)" in output
        assert "L   10 function: def foo(x: int) -> str" in output

    def test_format_without_line_numbers(self):
        entries = [
            OutlineEntry(
                line=10, depth=0, kind="function", name="foo",
            ),
        ]
        output = _format_outline(entries, False, "test.py", "python")
        assert "L" not in output
        assert "function: foo" in output

    def test_format_with_depth_indent(self):
        entries = [
            OutlineEntry(
                line=1, depth=0, kind="class", name="A",
            ),
            OutlineEntry(
                line=5, depth=1, kind="method", name="run",
            ),
        ]
        output = _format_outline(entries, False, "t.py", "python")
        lines = output.split("\n")
        # Class at depth 0
        assert "class: A" in lines[2]
        # Method at depth 1 (indented)
        assert "  method: run" in lines[3]

    def test_format_with_token_estimates(self):
        entries = [
            OutlineEntry(
                line=1, depth=0, kind="function", name="f",
                token_estimate=150,
            ),
        ]
        output = _format_outline(
            entries, True, "t.py", "python",
            show_tokens=True,
        )
        assert "(~150 tokens)" in output

    def test_format_tokens_not_shown_by_default(self):
        entries = [
            OutlineEntry(
                line=1, depth=0, kind="function", name="f",
                token_estimate=150,
            ),
        ]
        output = _format_outline(entries, True, "t.py", "python")
        assert "tokens" not in output

    def test_format_with_diff_marker(self):
        entries = [
            OutlineEntry(
                line=1, depth=0, kind="function", name="f",
                has_diff=True,
            ),
        ]
        output = _format_outline(
            entries, True, "t.py", "python",
            show_diff=True,
        )
        assert "[CHANGED]" in output

    def test_diff_not_shown_by_default(self):
        entries = [
            OutlineEntry(
                line=1, depth=0, kind="function", name="f",
                has_diff=True,
            ),
        ]
        output = _format_outline(entries, True, "t.py", "python")
        assert "[CHANGED]" not in output

    def test_format_with_preview_lines(self):
        entries = [
            OutlineEntry(
                line=1, depth=0, kind="function", name="f",
                preview_lines=["    x = 1", "    return x"],
            ),
        ]
        output = _format_outline(entries, True, "t.py", "python")
        assert "| " in output
        assert "x = 1" in output


# =============================================================================
# Parser Tests
# =============================================================================


class TestMarkdownParser:
    def test_heading_hierarchy(self):
        lines = [
            "# Title",
            "Some text",
            "## Section",
            "More text",
            "### Subsection",
        ]
        entries = parse_markdown(lines, 999, True, 0)
        assert len(entries) == 3
        assert entries[0].kind == "h1"
        assert entries[0].name == "Title"
        assert entries[0].depth == 0
        assert entries[1].kind == "h2"
        assert entries[1].depth == 1
        assert entries[2].kind == "h3"
        assert entries[2].depth == 2

    def test_depth_filtering(self):
        lines = ["# Title", "## Section", "### Sub"]
        entries = parse_markdown(lines, 2, True, 0)
        assert len(entries) == 2  # h1 and h2 only

    def test_preview_lines(self):
        lines = ["# Title", "First paragraph", "Second line"]
        entries = parse_markdown(lines, 999, True, 2)
        assert len(entries) == 1
        assert entries[0].preview_lines == ["First paragraph", "Second line"]

    def test_no_false_positives(self):
        lines = [
            "Not a heading",
            "  # Also not (indented)",
            "# Real heading",
        ]
        entries = parse_markdown(lines, 999, True, 0)
        assert len(entries) == 1
        assert entries[0].name == "Real heading"


class TestPythonParser:
    def test_class_and_methods(self):
        lines = [
            "class MyClass:",
            "    def method_a(self):",
            "        pass",
            "    def method_b(self, x: int):",
            "        pass",
        ]
        entries = parse_python(lines, 999, True, 0)
        assert len(entries) == 3
        assert entries[0].kind == "class"
        assert entries[0].name == "MyClass"
        assert entries[0].depth == 0
        assert entries[1].kind == "method"
        assert entries[1].name == "method_a"
        assert entries[1].depth == 1
        assert entries[2].kind == "method"

    def test_depth_1_top_level_only(self):
        lines = [
            "class MyClass:",
            "    def method(self):",
            "        pass",
            "def top_func():",
            "    pass",
        ]
        entries = parse_python(lines, 1, True, 0)
        assert len(entries) == 2
        assert entries[0].name == "MyClass"
        assert entries[1].name == "top_func"

    def test_decorators(self):
        lines = [
            "@staticmethod",
            "def foo():",
            "    pass",
        ]
        entries = parse_python(lines, 999, True, 0)
        assert len(entries) == 1
        assert "@staticmethod" in entries[0].signature

    def test_async_function(self):
        lines = [
            "async def fetch_data(url: str) -> dict:",
            "    pass",
        ]
        entries = parse_python(lines, 999, True, 0)
        assert len(entries) == 1
        assert entries[0].name == "fetch_data"
        assert "async def" in entries[0].signature

    def test_module_constants(self):
        lines = [
            "MAX_SIZE = 100",
            "API_KEY: str = 'test'",
            "regular_var = 42",  # lowercase, not captured
        ]
        entries = parse_python(lines, 999, True, 0)
        assert len(entries) == 2
        assert entries[0].kind == "constant"
        assert entries[0].name == "MAX_SIZE"
        assert entries[1].name == "API_KEY"

    def test_signatures_off(self):
        lines = [
            "def foo(x: int, y: str) -> bool:",
            "    pass",
        ]
        entries = parse_python(lines, 999, False, 0)
        assert len(entries) == 1
        assert entries[0].signature == ""

    def test_multiline_signature(self):
        lines = [
            "def foo(",
            "    x: int,",
            "    y: str,",
            ") -> bool:",
            "    pass",
        ]
        entries = parse_python(lines, 999, True, 0)
        assert len(entries) == 1
        assert "x: int" in entries[0].signature
        assert "y: str" in entries[0].signature

    def test_class_with_bases(self):
        lines = [
            "class Child(Parent, Mixin):",
            "    pass",
        ]
        entries = parse_python(lines, 999, True, 0)
        assert len(entries) == 1
        assert "(Parent, Mixin)" in entries[0].signature


class TestJsonParser:
    def test_basic_keys(self):
        lines = [
            '{',
            '  "name": "test",',
            '  "version": "1.0"',
            '}',
        ]
        entries = parse_json(lines, 999, True, 0)
        assert len(entries) == 2
        names = [e.name for e in entries]
        assert "name" in names
        assert "version" in names

    def test_nested_keys_with_depth(self):
        lines = [
            '{',
            '  "outer": {',
            '    "inner": "value"',
            '  }',
            '}',
        ]
        entries = parse_json(lines, 1, True, 0)
        assert len(entries) == 1
        assert entries[0].name == "outer"

    def test_value_summary(self):
        lines = [
            '{',
            '  "items": [1, 2, 3],',
            '  "config": {"a": 1}',
            '}',
        ]
        entries = parse_json(lines, 999, True, 0)
        sigs = {e.name: e.signature for e in entries}
        assert "[3 items]" in sigs.get("items", "")
        assert "{1 keys}" in sigs.get("config", "")

    def test_invalid_json(self):
        lines = ["not valid json {"]
        entries = parse_json(lines, 999, True, 0)
        assert entries == []


class TestYamlParser:
    def test_basic_keys(self):
        lines = [
            "name: my-app",
            "version: 1.0",
            "description: A test app",
        ]
        entries = parse_yaml(lines, 999, True, 0)
        assert len(entries) == 3
        assert entries[0].name == "name"
        assert entries[0].depth == 0

    def test_nested_keys(self):
        lines = [
            "server:",
            "  host: localhost",
            "  port: 8080",
            "database:",
            "  url: postgresql://...",
        ]
        entries = parse_yaml(lines, 999, True, 0)
        assert entries[0].name == "server"
        assert entries[0].depth == 0
        assert entries[1].name == "host"
        assert entries[1].depth == 1

    def test_depth_filtering(self):
        lines = [
            "level1:",
            "  level2:",
            "    level3: value",
        ]
        entries = parse_yaml(lines, 1, True, 0)
        assert len(entries) == 1


class TestTomlParser:
    def test_tables_and_keys(self):
        lines = [
            "[package]",
            "name = 'test'",
            "version = '1.0'",
            "",
            "[dependencies]",
            "foo = '1.2'",
        ]
        entries = parse_toml(lines, 999, True, 0)
        tables = [e for e in entries if e.kind == "table"]
        keys = [e for e in entries if e.kind == "key"]
        assert len(tables) == 2
        assert len(keys) == 3

    def test_nested_tables(self):
        lines = [
            "[tool.ruff]",
            "line-length = 100",
        ]
        entries = parse_toml(lines, 999, True, 0)
        assert entries[0].kind == "table"
        assert entries[0].name == "tool.ruff"

    def test_array_tables(self):
        lines = [
            "[[servers]]",
            "host = 'a.example.com'",
        ]
        entries = parse_toml(lines, 999, True, 0)
        assert entries[0].kind == "array-table"
        assert entries[0].name == "servers"


class TestJavaScriptParser:
    def test_exports_and_functions(self):
        lines = [
            "export function handleRequest(req, res) {",
            "  // ...",
            "}",
            "",
            "function helper() {",
            "  return 42;",
            "}",
        ]
        entries = parse_javascript(lines, 999, True, 0)
        func_names = [e.name for e in entries if e.kind == "function"]
        assert "handleRequest" in func_names
        assert "helper" in func_names

    def test_class_declaration(self):
        lines = [
            "export class MyComponent extends React.Component {",
            "  render() {",
            "    return null;",
            "  }",
            "}",
        ]
        entries = parse_javascript(lines, 999, True, 0)
        classes = [e for e in entries if e.kind == "class"]
        assert len(classes) == 1
        assert classes[0].name == "MyComponent"

    def test_arrow_function(self):
        lines = [
            "export const fetchData = async (url) => {",
            "  return fetch(url);",
            "};",
        ]
        entries = parse_javascript(lines, 999, True, 0)
        assert any(e.name == "fetchData" for e in entries)

    def test_const_variable(self):
        lines = [
            "const MAX_RETRIES = 3;",
            "let count = 0;",
        ]
        entries = parse_javascript(lines, 999, True, 0)
        names = [e.name for e in entries]
        assert "MAX_RETRIES" in names
        assert "count" in names


class TestTypeScriptParser:
    def test_interface(self):
        lines = [
            "export interface User {",
            "  name: string;",
            "  age: number;",
            "}",
        ]
        entries = parse_typescript(lines, 999, True, 0)
        ifaces = [e for e in entries if e.kind == "interface"]
        assert len(ifaces) == 1
        assert ifaces[0].name == "User"

    def test_type_alias(self):
        lines = [
            "export type Status = 'active' | 'inactive';",
        ]
        entries = parse_typescript(lines, 999, True, 0)
        types = [e for e in entries if e.kind == "type"]
        assert len(types) == 1
        assert types[0].name == "Status"

    def test_includes_js_entries(self):
        lines = [
            "export function greet(name: string): void {",
            "  console.log(name);",
            "}",
            "interface Config {",
            "  debug: boolean;",
            "}",
        ]
        entries = parse_typescript(lines, 999, True, 0)
        kinds = {e.kind for e in entries}
        assert "function" in kinds
        assert "interface" in kinds


class TestRustParser:
    def test_struct(self):
        lines = [
            "pub struct Point {",
            "    x: f64,",
            "    y: f64,",
            "}",
        ]
        entries = parse_rust(lines, 999, True, 0)
        assert len(entries) == 1
        assert entries[0].kind == "struct"
        assert entries[0].name == "Point"

    def test_enum(self):
        lines = [
            "pub enum Color {",
            "    Red,",
            "    Green,",
            "    Blue,",
            "}",
        ]
        entries = parse_rust(lines, 999, True, 0)
        assert entries[0].kind == "enum"
        assert entries[0].name == "Color"

    def test_trait(self):
        lines = [
            "pub trait Drawable {",
            "    fn draw(&self);",
            "}",
        ]
        entries = parse_rust(lines, 999, True, 0)
        traits = [e for e in entries if e.kind == "trait"]
        assert len(traits) == 1
        assert traits[0].name == "Drawable"

    def test_impl_block_with_methods(self):
        lines = [
            "impl Point {",
            "    pub fn new(x: f64, y: f64) -> Self {",
            "        Self { x, y }",
            "    }",
            "}",
        ]
        entries = parse_rust(lines, 999, True, 0)
        assert entries[0].kind == "impl"
        assert entries[0].name == "Point"
        methods = [e for e in entries if e.kind == "method"]
        assert len(methods) == 1
        assert methods[0].name == "new"

    def test_async_fn(self):
        lines = ["pub async fn fetch(url: &str) -> Result<String, Error> {"]
        entries = parse_rust(lines, 999, True, 0)
        assert len(entries) == 1
        assert entries[0].name == "fetch"


class TestGoParser:
    def test_type_struct(self):
        lines = [
            "type Server struct {",
            "    Host string",
            "    Port int",
            "}",
        ]
        entries = parse_go(lines, 999, True, 0)
        assert len(entries) == 1
        assert entries[0].kind == "struct"
        assert entries[0].name == "Server"

    def test_type_interface(self):
        lines = [
            "type Handler interface {",
            "    Handle(req *Request)",
            "}",
        ]
        entries = parse_go(lines, 999, True, 0)
        assert entries[0].kind == "interface"
        assert entries[0].name == "Handler"

    def test_function(self):
        lines = [
            "func NewServer(host string, port int) *Server {",
            "    return &Server{host, port}",
            "}",
        ]
        entries = parse_go(lines, 999, True, 0)
        assert entries[0].kind == "function"
        assert entries[0].name == "NewServer"

    def test_method_with_receiver(self):
        lines = [
            "func (s *Server) Start() error {",
            "    return nil",
            "}",
        ]
        entries = parse_go(lines, 999, True, 0)
        assert entries[0].kind == "method"
        assert entries[0].name == "Start"


class TestCCppParser:
    def test_function(self):
        lines = [
            "int main(int argc, char* argv[]) {",
            "    return 0;",
            "}",
        ]
        entries = parse_c_cpp(lines, 999, True, 0)
        assert len(entries) == 1
        assert entries[0].kind == "function"
        assert entries[0].name == "main"

    def test_class(self):
        lines = [
            "class Widget {",
            "public:",
            "    void draw();",
            "};",
        ]
        entries = parse_c_cpp(lines, 999, True, 0)
        classes = [e for e in entries if e.kind == "class"]
        assert len(classes) == 1
        assert classes[0].name == "Widget"

    def test_struct(self):
        lines = ["struct Point {"]
        entries = parse_c_cpp(lines, 999, True, 0)
        assert entries[0].kind == "struct"
        assert entries[0].name == "Point"

    def test_enum(self):
        lines = ["enum Color {"]
        entries = parse_c_cpp(lines, 999, True, 0)
        assert entries[0].kind == "enum"
        assert entries[0].name == "Color"

    def test_namespace(self):
        lines = ["namespace mylib {"]
        entries = parse_c_cpp(lines, 999, True, 0)
        assert entries[0].kind == "namespace"
        assert entries[0].name == "mylib"

    def test_typedef(self):
        lines = ["typedef unsigned long size_type;"]
        entries = parse_c_cpp(lines, 999, True, 0)
        assert entries[0].kind == "typedef"
        assert entries[0].name == "size_type"

    def test_skips_preprocessor(self):
        lines = [
            "#include <stdio.h>",
            "#define MAX 100",
            "int main() {",
        ]
        entries = parse_c_cpp(lines, 999, True, 0)
        assert len(entries) == 1
        assert entries[0].name == "main"


class TestHtmlParser:
    def test_basic_elements(self):
        lines = [
            "<html>",
            "  <head>",
            "    <title>Test</title>",
            "  </head>",
            "  <body>",
            "    <div id='main' class='container'>",
            "    </div>",
            "  </body>",
            "</html>",
        ]
        entries = parse_html(lines, 999, True, 0)
        assert len(entries) > 0
        names = [e.name for e in entries]
        assert any("html" in n for n in names)

    def test_id_and_class_extraction(self):
        lines = ['<div id="main" class="container active">']
        entries = parse_html(lines, 999, True, 0)
        assert len(entries) == 1
        assert "#main" in entries[0].name
        assert ".container" in entries[0].name
        assert ".active" in entries[0].name

    def test_self_closing_tag(self):
        lines = ['<img src="photo.jpg" />']
        entries = parse_html(lines, 999, True, 0)
        assert len(entries) == 1
        assert entries[0].name == "img"


class TestCssParser:
    def test_selectors(self):
        lines = [
            ".container {",
            "  width: 100%;",
            "}",
            "",
            "#header {",
            "  background: blue;",
            "}",
        ]
        entries = parse_css(lines, 999, True, 0)
        names = [e.name for e in entries]
        assert ".container" in names
        assert "#header" in names

    def test_at_rules(self):
        lines = [
            "@media (max-width: 768px) {",
            "  .mobile {",
            "    display: block;",
            "  }",
            "}",
        ]
        entries = parse_css(lines, 999, True, 0)
        at_rules = [e for e in entries if e.kind == "at-rule"]
        assert len(at_rules) == 1
        assert "@media" in at_rules[0].name

    def test_nested_selector_in_at_rule(self):
        lines = [
            "@media screen {",
            "  .foo {",
            "    color: red;",
            "  }",
            "}",
        ]
        entries = parse_css(lines, 999, True, 0)
        selectors = [e for e in entries if e.kind == "selector"]
        assert len(selectors) == 1
        assert selectors[0].depth == 1


class TestSqlParser:
    def test_create_table(self):
        lines = [
            "CREATE TABLE users (",
            "  id INTEGER PRIMARY KEY,",
            "  name TEXT",
            ");",
        ]
        entries = parse_sql(lines, 999, True, 0)
        assert len(entries) == 1
        assert entries[0].kind == "table"
        assert entries[0].name == "users"

    def test_create_view(self):
        lines = ["CREATE VIEW active_users AS SELECT * FROM users WHERE active;"]
        entries = parse_sql(lines, 999, True, 0)
        assert entries[0].kind == "view"
        assert entries[0].name == "active_users"

    def test_create_index(self):
        lines = ["CREATE INDEX idx_users_name ON users(name);"]
        entries = parse_sql(lines, 999, True, 0)
        assert entries[0].kind == "index"
        assert entries[0].name == "idx_users_name"

    def test_if_not_exists(self):
        lines = ["CREATE TABLE IF NOT EXISTS configs ("]
        entries = parse_sql(lines, 999, True, 0)
        assert entries[0].name == "configs"


class TestMakefileParser:
    def test_targets(self):
        lines = [
            "all: build test",
            "",
            "build:",
            "\tgcc -o main main.c",
            "",
            "test:",
            "\t./run_tests.sh",
            "",
            "clean:",
            "\trm -f main",
        ]
        entries = parse_makefile(lines, 999, True, 0)
        names = [e.name for e in entries]
        assert "all" in names
        assert "build" in names
        assert "test" in names
        assert "clean" in names

    def test_skips_recipe_lines(self):
        lines = [
            "target:",
            "\techo hello",
            "\techo world",
        ]
        entries = parse_makefile(lines, 999, True, 0)
        assert len(entries) == 1


class TestDockerfileParser:
    def test_from_stages(self):
        lines = [
            "FROM python:3.12 AS builder",
            "RUN pip install deps",
            "",
            "FROM python:3.12-slim AS runtime",
            "COPY --from=builder /app /app",
        ]
        entries = parse_dockerfile(lines, 999, True, 0)
        assert len(entries) == 2
        assert entries[0].kind == "stage"
        assert entries[0].name == "builder"
        assert entries[1].name == "runtime"

    def test_from_without_alias(self):
        lines = ["FROM ubuntu:22.04"]
        entries = parse_dockerfile(lines, 999, True, 0)
        assert entries[0].name == "ubuntu:22.04"


# =============================================================================
# Token Estimation Tests
# =============================================================================


class TestTokenEstimation:
    def test_annotate_token_estimates(self):
        lines = ["line " * 20] * 10  # ~200 words = ~200 tokens
        entries = [
            OutlineEntry(line=1, depth=0, kind="f", name="a", end_line=5),
            OutlineEntry(line=6, depth=0, kind="f", name="b", end_line=10),
        ]
        _annotate_token_estimates(entries, lines)
        assert entries[0].token_estimate > 0
        assert entries[1].token_estimate > 0

    def test_zero_end_line_skipped(self):
        entries = [OutlineEntry(line=1, depth=0, kind="f", name="a")]
        _annotate_token_estimates(entries, ["hello"])
        assert entries[0].token_estimate == 0

    def test_proportional_to_size(self):
        lines = [f"x = {i}" for i in range(100)]
        entries = [
            OutlineEntry(line=1, depth=0, kind="f", name="a", end_line=10),
            OutlineEntry(line=11, depth=0, kind="f", name="b", end_line=60),
        ]
        _annotate_token_estimates(entries, lines)
        # Bigger section should have more tokens
        assert entries[1].token_estimate > entries[0].token_estimate


# =============================================================================
# Symbol Extraction Tests
# =============================================================================


class TestSymbolExtraction:
    def test_exact_match(self):
        entries = [
            OutlineEntry(
                line=1, depth=0, kind="class", name="MyClass",
                end_line=10,
            ),
        ]
        lines = [f"line {i}" for i in range(15)]
        result = _extract_symbol(entries, lines, "MyClass", "test.py")
        assert result.success
        assert "class: MyClass" in result.output
        assert "L1-10" in result.output

    def test_case_insensitive_fallback(self):
        entries = [
            OutlineEntry(
                line=1, depth=0, kind="function", name="myFunc",
                end_line=5,
            ),
        ]
        lines = [f"line {i}" for i in range(10)]
        result = _extract_symbol(entries, lines, "MYFUNC", "test.py")
        assert result.success

    def test_not_found(self):
        entries = [
            OutlineEntry(
                line=1, depth=0, kind="function", name="existing",
                end_line=5,
            ),
        ]
        result = _extract_symbol(entries, [], "missing", "test.py")
        assert not result.success
        assert "not found" in result.error
        assert "existing" in result.error

    def test_returns_numbered_lines(self):
        entries = [
            OutlineEntry(
                line=1, depth=0, kind="function", name="foo",
                end_line=3,
            ),
        ]
        lines = ["def foo():", "    return 1", ""]
        result = _extract_symbol(entries, lines, "foo", "test.py")
        assert "1: def foo():" in result.output
        assert "2:     return 1" in result.output


# =============================================================================
# Diff-Aware Tests
# =============================================================================


class TestDiffAnnotation:
    def test_overlap_marks_entry(self):
        entries = [
            OutlineEntry(
                line=10, depth=0, kind="f", name="a",
                end_line=20,
            ),
        ]
        _annotate_diff_markers(entries, [(15, 18)])
        assert entries[0].has_diff is True

    def test_no_overlap(self):
        entries = [
            OutlineEntry(
                line=10, depth=0, kind="f", name="a",
                end_line=20,
            ),
        ]
        _annotate_diff_markers(entries, [(25, 30)])
        assert entries[0].has_diff is False

    def test_boundary_overlap(self):
        entries = [
            OutlineEntry(
                line=10, depth=0, kind="f", name="a",
                end_line=20,
            ),
        ]
        _annotate_diff_markers(entries, [(20, 25)])
        assert entries[0].has_diff is True

    def test_zero_end_line_skipped(self):
        entries = [
            OutlineEntry(line=10, depth=0, kind="f", name="a"),
        ]
        _annotate_diff_markers(entries, [(10, 15)])
        assert entries[0].has_diff is False


class TestGetDiffRanges:
    def test_not_git_repo(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("hello")
        result = _get_diff_ranges(f)
        assert result is None

    def test_with_real_git_repo(self, tmp_path):
        """Integration test with a real git repo."""
        # Init a git repo
        subprocess.run(
            ["git", "init"], cwd=str(tmp_path),
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(tmp_path), capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(tmp_path), capture_output=True,
        )

        # Create and commit a file
        f = tmp_path / "test.py"
        f.write_text("line1\nline2\nline3\n")
        subprocess.run(
            ["git", "add", "test.py"], cwd=str(tmp_path),
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=str(tmp_path), capture_output=True,
        )

        # Modify the file
        f.write_text("line1\nMODIFIED\nline3\n")

        # Get diff ranges
        ranges = _get_diff_ranges(f)
        assert ranges is not None
        assert len(ranges) > 0
        # Line 2 was changed
        assert any(s <= 2 <= e for s, e in ranges)

    def test_no_changes(self, tmp_path):
        """File committed with no subsequent changes."""
        subprocess.run(
            ["git", "init"], cwd=str(tmp_path),
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(tmp_path), capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(tmp_path), capture_output=True,
        )
        f = tmp_path / "test.py"
        f.write_text("unchanged\n")
        subprocess.run(
            ["git", "add", "."], cwd=str(tmp_path),
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=str(tmp_path), capture_output=True,
        )
        ranges = _get_diff_ranges(f)
        assert ranges is not None
        assert len(ranges) == 0


# =============================================================================
# Skill-Level Tests
# =============================================================================


class TestOutlineSkill:
    @pytest.mark.asyncio
    async def test_empty_path(self, skill):
        result = await skill.execute(path="")
        assert not result.success
        assert "No path" in result.error

    @pytest.mark.asyncio
    async def test_nonexistent_file(self, skill, tmp_path):
        result = await skill.execute(path=str(tmp_path / "nope.py"))
        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_unsupported_extension(self, skill, tmp_path):
        f = tmp_path / "photo.xyz"
        f.write_text("binary stuff")
        result = await skill.execute(path=str(f))
        assert result.success
        assert "No outline parser" in result.output

    @pytest.mark.asyncio
    async def test_python_file(self, skill, tmp_path):
        f = tmp_path / "example.py"
        f.write_text(
            "class Foo:\n"
            "    def bar(self):\n"
            "        pass\n"
            "\n"
            "def baz():\n"
            "    pass\n"
        )
        result = await skill.execute(path=str(f))
        assert result.success
        assert "class: " in result.output
        assert "Foo" in result.output
        assert "baz" in result.output

    @pytest.mark.asyncio
    async def test_markdown_file(self, skill, tmp_path):
        f = tmp_path / "doc.md"
        f.write_text("# Title\n\n## Section\n\nText\n")
        result = await skill.execute(path=str(f))
        assert result.success
        assert "h1: Title" in result.output
        assert "h2: Section" in result.output

    @pytest.mark.asyncio
    async def test_json_file(self, skill, tmp_path):
        f = tmp_path / "config.json"
        f.write_text('{"name": "test", "version": "1.0"}')
        result = await skill.execute(path=str(f))
        assert result.success
        assert "name" in result.output

    @pytest.mark.asyncio
    async def test_depth_parameter(self, skill, tmp_path):
        f = tmp_path / "deep.py"
        f.write_text(
            "class A:\n"
            "    def method(self):\n"
            "        pass\n"
        )
        result = await skill.execute(path=str(f), depth=1)
        assert result.success
        assert "class" in result.output
        assert "method" not in result.output

    @pytest.mark.asyncio
    async def test_preview_parameter(self, skill, tmp_path):
        f = tmp_path / "doc.md"
        f.write_text("# Title\nFirst line\nSecond line\n")
        result = await skill.execute(path=str(f), preview=1)
        assert result.success
        assert "| First line" in result.output

    @pytest.mark.asyncio
    async def test_line_numbers_off(self, skill, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("def foo():\n    pass\n")
        result = await skill.execute(
            path=str(f), line_numbers=False,
        )
        assert result.success
        assert "L" not in result.output.split("\n")[2]

    @pytest.mark.asyncio
    async def test_signatures_off(self, skill, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("def foo(x: int) -> str:\n    pass\n")
        result = await skill.execute(
            path=str(f), signatures=False,
        )
        assert result.success
        assert "x: int" not in result.output

    @pytest.mark.asyncio
    async def test_tokens_parameter(self, skill, tmp_path):
        f = tmp_path / "test.py"
        f.write_text(
            "def foo():\n"
            + "    x = 1\n" * 20
            + "\ndef bar():\n    pass\n"
        )
        result = await skill.execute(path=str(f), tokens=True)
        assert result.success
        assert "tokens)" in result.output

    @pytest.mark.asyncio
    async def test_symbol_parameter(self, skill, tmp_path):
        f = tmp_path / "test.py"
        f.write_text(
            "class Alpha:\n"
            "    def go(self):\n"
            "        pass\n"
            "\n"
            "class Beta:\n"
            "    def stop(self):\n"
            "        pass\n"
        )
        result = await skill.execute(path=str(f), symbol="Alpha")
        assert result.success
        assert "class: Alpha" in result.output
        assert "def go" in result.output
        # Should NOT contain Beta's content
        assert "Beta" not in result.output.split("\n", 1)[1]

    @pytest.mark.asyncio
    async def test_directory_mode(self, skill, tmp_path):
        (tmp_path / "a.py").write_text("def foo():\n    pass\n")
        (tmp_path / "b.py").write_text("class Bar:\n    pass\n")
        (tmp_path / "c.txt").write_text("not parseable")
        result = await skill.execute(path=str(tmp_path))
        assert result.success
        assert "a.py" in result.output
        assert "b.py" in result.output
        assert "c.txt" not in result.output

    @pytest.mark.asyncio
    async def test_directory_skips_hidden(self, skill, tmp_path):
        (tmp_path / "visible.py").write_text("def f():\n    pass\n")
        (tmp_path / ".hidden.py").write_text("def g():\n    pass\n")
        result = await skill.execute(path=str(tmp_path))
        assert result.success
        assert "visible.py" in result.output
        assert ".hidden.py" not in result.output

    @pytest.mark.asyncio
    async def test_directory_empty(self, skill, tmp_path):
        sub = tmp_path / "empty"
        sub.mkdir()
        result = await skill.execute(path=str(sub))
        assert result.success
        assert "No supported files" in result.output

    @pytest.mark.asyncio
    async def test_empty_file(self, skill, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("")
        result = await skill.execute(path=str(f))
        assert result.success
        assert "No outline entries" in result.output

    @pytest.mark.asyncio
    async def test_binary_file_graceful(self, skill, tmp_path):
        f = tmp_path / "data.py"
        f.write_bytes(b"\x80\x81\x82\x83")
        result = await skill.execute(path=str(f))
        # Should handle gracefully (errors="replace" in read)
        assert result.success or "UTF-8" in result.error


class TestParserRegistry:
    def test_all_parsers_registered(self):
        expected = {
            "python", "markdown", "javascript", "typescript",
            "rust", "go", "c", "cpp", "json", "yaml", "toml",
            "html", "css", "sql", "makefile", "dockerfile",
        }
        assert set(PARSERS.keys()) == expected

    def test_all_ext_parsers_have_parser(self):
        for ext, lang in EXT_TO_PARSER.items():
            assert lang in PARSERS, f"Extension .{ext} maps to '{lang}' but no parser exists"

    def test_all_filename_parsers_have_parser(self):
        for fname, lang in FILENAME_TO_PARSER.items():
            assert lang in PARSERS, f"Filename '{fname}' maps to '{lang}' but no parser exists"
