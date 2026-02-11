from __future__ import annotations

from nexus3.ide.connection import Diagnostic, EditorInfo
from nexus3.ide.context import _MAX_IDE_CONTEXT_LENGTH, format_ide_context


class TestFormatIdeContext:
    def test_no_data_returns_none(self) -> None:
        result = format_ide_context("VS Code")
        assert result is None

    def test_empty_lists_returns_none(self) -> None:
        result = format_ide_context("VS Code", open_editors=[], diagnostics=[])
        assert result is None

    def test_open_editors(self) -> None:
        editors = [
            EditorInfo(file_path="/home/user/project/main.py", is_active=True),
            EditorInfo(file_path="/home/user/project/utils.py"),
        ]
        result = format_ide_context("VS Code", open_editors=editors)
        assert result is not None
        assert "IDE connected: VS Code" in result
        assert "main.py" in result
        assert "utils.py" in result

    def test_diagnostics_errors(self) -> None:
        diagnostics = [
            Diagnostic(file_path="/a.py", line=10, message="undefined var", severity="error"),
            Diagnostic(file_path="/b.py", line=5, message="unused import", severity="warning"),
        ]
        result = format_ide_context("VS Code", diagnostics=diagnostics)
        assert result is not None
        assert "1 errors" in result
        assert "1 warnings" in result
        assert "a.py:10: undefined var" in result

    def test_warnings_only(self) -> None:
        diagnostics = [
            Diagnostic(file_path="/a.py", line=1, message="warn", severity="warning"),
        ]
        result = format_ide_context("VS Code", diagnostics=diagnostics)
        assert result is not None
        assert "1 warnings" in result
        # Warning details are not shown (only errors get line details)
        assert "a.py:1" not in result

    def test_inject_flags_disable(self) -> None:
        editors = [EditorInfo(file_path="/a.py")]
        diagnostics = [Diagnostic(file_path="/a.py", line=1, message="err", severity="error")]

        result = format_ide_context(
            "VS Code",
            open_editors=editors,
            diagnostics=diagnostics,
            inject_diagnostics=False,
            inject_open_editors=False,
        )
        assert result is None  # Nothing injected

    def test_truncation(self) -> None:
        diagnostics = [
            Diagnostic(
                file_path=f"/very/long/path/file_{i}.py",
                line=i, message="x" * 50, severity="error",
            )
            for i in range(100)
        ]
        result = format_ide_context("VS Code", diagnostics=diagnostics)
        assert result is not None
        assert len(result) <= _MAX_IDE_CONTEXT_LENGTH
        assert result.endswith("...")

    def test_max_10_editors(self) -> None:
        editors = [EditorInfo(file_path=f"/file_{i}.py") for i in range(20)]
        result = format_ide_context("VS Code", open_editors=editors)
        assert result is not None
        # Should only show first 10
        assert "file_0.py" in result
        assert "file_9.py" in result
        assert "file_10.py" not in result
