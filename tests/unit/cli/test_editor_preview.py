"""Tests for REPL external-editor preview helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from nexus3.cli import editor_preview


def test_get_system_editor_parses_editor_env(monkeypatch) -> None:
    monkeypatch.setattr(editor_preview.sys, "platform", "darwin")
    monkeypatch.setenv("EDITOR", "code --wait")
    monkeypatch.delenv("VISUAL", raising=False)

    assert editor_preview.get_system_editor() == ["code", "--wait"]


def test_get_system_editor_prefers_textedit_on_darwin(monkeypatch) -> None:
    monkeypatch.setattr(editor_preview.sys, "platform", "darwin")
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setattr(editor_preview, "is_wsl", lambda: False)
    monkeypatch.setattr(
        editor_preview.shutil,
        "which",
        lambda cmd: "/usr/bin/open" if cmd == "open" else None,
    )

    assert editor_preview.get_system_editor() == ["open", "-W", "-n", "-a", "TextEdit"]


def test_open_in_editor_uses_blocking_textedit_on_darwin(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(editor_preview.sys, "platform", "darwin")
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setattr(editor_preview, "is_wsl", lambda: False)
    monkeypatch.setattr(
        editor_preview.Path,
        "home",
        classmethod(lambda cls: tmp_path),
    )
    monkeypatch.setattr(
        editor_preview.shutil,
        "which",
        lambda cmd: "/usr/bin/open" if cmd == "open" else None,
    )

    seen_args: list[str] = []
    seen_content: str | None = None

    def fake_run(args: list[str]) -> None:
        nonlocal seen_content
        path = Path(args[-1])
        seen_args.extend(args)
        seen_content = path.read_text(encoding="utf-8")

    with patch("nexus3.cli.editor_preview.subprocess.run", side_effect=fake_run):
        assert editor_preview.open_in_editor("hello from preview", "Preview Title") is True

    assert seen_args[:5] == ["open", "-W", "-n", "-a", "TextEdit"]
    assert seen_args[5].endswith(".txt")
    assert seen_content == "=== Preview Title ===\n\nhello from preview\n"
