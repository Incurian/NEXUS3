"""Tests for command-scoped executable identity normalization."""

from pathlib import Path

from nexus3.core.executable_identity import resolve_executable_identity


def test_resolves_relative_program_against_cwd(tmp_path: Path) -> None:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script_path = scripts_dir / "tool"

    identity = resolve_executable_identity("./scripts/tool", cwd=tmp_path)

    assert identity == str(script_path)


def test_resolves_bare_program_via_path(monkeypatch: object) -> None:
    monkeypatch.setattr(
        "nexus3.core.executable_identity.shutil.which",
        lambda program, path=None: "/usr/bin/grep" if program == "grep" else None,
    )

    identity = resolve_executable_identity("grep")

    assert identity == "/usr/bin/grep"


def test_falls_back_to_normalized_program_when_path_resolution_fails(monkeypatch: object) -> None:
    monkeypatch.setattr(
        "nexus3.core.executable_identity.shutil.which",
        lambda program, path=None: None,
    )

    identity = resolve_executable_identity("custom-tool")

    assert identity == "custom-tool"


def test_rejects_empty_program() -> None:
    try:
        resolve_executable_identity("   ")
    except ValueError as exc:
        assert str(exc) == "Program is required"
    else:
        raise AssertionError("Expected ValueError for empty program")
